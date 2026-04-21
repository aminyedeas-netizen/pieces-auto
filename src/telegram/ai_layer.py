"""Conversational AI layer for the admin bot.

Wraps OpenRouter (Gemini Flash) with function calling, conversation
history, and a system prompt tailored to the PiecesAutoTN admin use case.
"""

import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("OPENROUTER_PRIMARY_MODEL", "google/gemini-2.0-flash-exp")

# ---------------------------------------------------------------------------
# Conversation history (in-memory, per chat_id)
# ---------------------------------------------------------------------------

MAX_HISTORY = 20
HISTORY_TIMEOUT = 30 * 60  # 30 minutes

# {chat_id: {"messages": [...], "last_active": timestamp}}
_conversations: dict[int, dict] = {}


def get_history(chat_id: int) -> list[dict]:
    """Return conversation history, clearing if stale."""
    entry = _conversations.get(chat_id)
    if not entry:
        return []
    if time.time() - entry["last_active"] > HISTORY_TIMEOUT:
        _conversations.pop(chat_id, None)
        return []
    return entry["messages"]


def append_message(chat_id: int, role: str, content: str) -> None:
    """Add a message to history, trimming to MAX_HISTORY."""
    if chat_id not in _conversations:
        _conversations[chat_id] = {"messages": [], "last_active": time.time()}
    entry = _conversations[chat_id]
    entry["last_active"] = time.time()
    entry["messages"].append({"role": role, "content": content})
    if len(entry["messages"]) > MAX_HISTORY:
        entry["messages"] = entry["messages"][-MAX_HISTORY:]


def reset_history(chat_id: int) -> None:
    """Clear conversation history for a chat."""
    _conversations.pop(chat_id, None)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Tu es l'assistant admin de PiecesAutoTN.

REGLE 1: Tu dois TOUJOURS appeler une fonction en premier. JAMAIS repondre du texte seul.
REGLE 2: Si tu as brand + model + part_name, appelle search_parts() IMMEDIATEMENT. Ne demande JAMAIS plus de details (generation, motorisation, carburant). search_parts gere tout automatiquement.

"sonde lambda A4" -> search_parts("AUDI", "A4", "Sonde lambda")
"filtre a huile Megane" -> search_parts("RENAULT", "Megane", "Filtre a huile")
"filtre Picanto" -> search_parts("KIA", "Picanto", "Filtre")
"pompe essence bmw serie 2" -> search_parts("BMW", "2", "Pompe a essence")
"plaquettes Clio III diesel" -> search_parts("RENAULT", "Clio III", "Plaquettes")

IMPORTANT pour le modele: passe le NUMERO seul sans "Serie"/"Série". "BMW serie 3" -> model="3", "BMW serie 2" -> model="2".

Si il manque la piece -> get_coverage(brand, model)
Si il manque le modele -> list_models(brand)
Si il manque la marque -> list_brands()
"Picanto" sans piece -> get_coverage("KIA", "Picanto")

=== MODE AJOUT (2 ou 3 etapes) ===

A) Par REFERENCE (ex: "ajouter 560118"):
   1. propose_pa24_add(reference="560118") -> apercu
   2. Utilisateur confirme -> confirm_pa24_add(url=...)

B) Par VEHICULE+PIECE (ex: "ajouter pompe a eau mercedes classe A"):
   1. propose_pa24_add(brand="MERCEDES-BENZ", model="Classe A", part_name="Pompe a eau")
      -> retourne CHOICES de motorisations
   2. Utilisateur choisit une motorisation (ex: "MERCEDES-BENZ Classe A 2.0 diesel 140CV")
      -> propose_pa24_add(vehicle_name="MERCEDES-BENZ Classe A 2.0 diesel 140CV", part_name="Pompe a eau")
      -> cherche sur PA24 -> apercu
   3. Utilisateur confirme -> confirm_pa24_add(url=...)

IMPORTANT: JAMAIS sauvegarder sans confirmation. Toujours montrer l'apercu d'abord.
Quand propose_pa24_add retourne des CHOICES, montre-les et attends le choix de l'utilisateur.

=== RECHERCHE CDG ===
search_cdg a 3 strategies automatiques:
1. Recherche directe par reference
2. Si echec: essaye les autres references en base pour le meme vehicule+piece
3. Si echec: recherche par nom de piece (designation) avec cross-reference OE

TOUJOURS passer brand, model et part_name en plus de la reference pour activer les fallbacks.
Si l'utilisateur demande "chercher par nom de piece" ou "chercher par designation":
-> Appelle search_cdg(brand=..., model=..., part_name=...) SANS reference.

=== AUTRES REGLES ===
- Comprends le langage naturel: "Megane II diesel 110" suffit
- Si la puissance exacte n'existe pas en base, propose la plus proche
- Garde le vehicule en contexte. "Et le filtre a air?" = meme vehicule
- "Meme chose pour la Clio III" = meme piece, autre vehicule
- Ne jamais inventer de references ou de prix

=== FORMATAGE ===
- Reponses concises et structurees
- References OE en premier, puis equivalents aftermarket
- Prix en EUR (base PA24) ou TND (CDG)
- Pas d'emoji
- Motorisations au format: "1.6 diesel 100CV", "2.0 essence 150CV"
- Ne montre JAMAIS de codes chassis (8E5, 8EC, B6, B7) a l'utilisateur

=== REGLE CHOICES (TRES IMPORTANT) ===
Quand un resultat de fonction contient CHOICES:[...]:
1. RECOPIE le resultat TEL QUEL dans ta reponse, y compris la ligne CHOICES:[...]
2. NE CHOISIS PAS toi-meme une option. NE RAPPELLE PAS une autre fonction.
3. ARRETE-TOI et laisse l'utilisateur choisir.
Exemple: si search_parts retourne "Pieces en base:\nCHOICES:[\"A\",\"B\"]", tu reponds exactement ce texte. Tu ne rappelles PAS search_parts avec "A" ou "B".
"""

# ---------------------------------------------------------------------------
# Function (tool) declarations for the LLM
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_parts",
            "description": "FONCTION PRINCIPALE. Cherche les references pour un vehicule et une piece. Gere TOUTES les motorisations et generations automatiquement. Appeler EN PREMIER des que tu as brand+model+part_name. 'filtre Megane' -> search_parts('RENAULT','Megane','Filtre'). Ne demande JAMAIS de precisions avant d'appeler cette fonction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "fuel": {"type": "string"},
                    "power_hp": {"type": "integer", "description": "Approximate, +/-5 tolerance"},
                    "part_name": {"type": "string"},
                },
                "required": ["brand", "model", "part_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_brands",
            "description": "Liste les marques en base. Utiliser SEULEMENT si la marque est inconnue.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_models",
            "description": "Liste les modeles pour une marque. Utiliser SEULEMENT si le modele est inconnu.",
            "parameters": {
                "type": "object",
                "properties": {"brand": {"type": "string"}},
                "required": ["brand"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_engines",
            "description": "Liste les motorisations. Rarement necessaire car search_parts gere tout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "fuel": {"type": "string"},
                },
                "required": ["brand", "model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_reference",
            "description": "Cherche une reference specifique en base. Retourne la fiche + vehicules compatibles.",
            "parameters": {
                "type": "object",
                "properties": {"reference": {"type": "string"}},
                "required": ["reference"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_coverage",
            "description": "Montre quelles pieces sont couvertes en base pour un vehicule, et lesquelles manquent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "fuel": {"type": "string"},
                    "power_hp": {"type": "integer"},
                },
                "required": ["brand", "model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_compatible_vehicles",
            "description": "Liste tous les vehicules compatibles avec une reference donnee.",
            "parameters": {
                "type": "object",
                "properties": {"reference": {"type": "string"}},
                "required": ["reference"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_vehicles",
            "description": "Verifie si deux vehicules partagent les memes references pour une piece.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle1": {"type": "string"},
                    "vehicle2": {"type": "string"},
                    "part_name": {"type": "string"},
                },
                "required": ["vehicle1", "vehicle2", "part_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "identify_vehicle",
            "description": "Identifie un vehicule a partir d'un VIN ou d'une description textuelle.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "VIN 17 chars or text description"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_cdg",
            "description": "Cherche chez le grossiste CDG. Peut chercher par reference, par nom de piece, ou les deux. Si reference non trouvee, essaye automatiquement les autres references en base et la recherche par designation. TOUJOURS passer brand+model+part_name quand disponibles pour activer les fallbacks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "Reference a chercher. Optionnel si on cherche par nom de piece."},
                    "brand": {"type": "string", "description": "Marque du vehicule (pour trouver les refs OE en base)"},
                    "model": {"type": "string", "description": "Modele du vehicule"},
                    "part_name": {"type": "string", "description": "Nom de la piece (pour recherche par designation CDG)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_db_stats",
            "description": "Retourne les statistiques de la base: nombre de vehicules, references, patterns VIN.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_pa24_add",
            "description": "Cherche un produit sur PiecesAuto24 et montre un apercu. NE SAUVEGARDE PAS en base. 2 modes: A) par reference directe, B) par vehicule+piece (retourne d'abord CHOICES de motorisations, puis cherche PA24 apres validation). Passe vehicle_name quand l'utilisateur a choisi une motorisation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "Reference produit a chercher sur PA24"},
                    "brand": {"type": "string", "description": "Marque du vehicule"},
                    "model": {"type": "string", "description": "Modele du vehicule"},
                    "part_name": {"type": "string", "description": "Nom de la piece"},
                    "vehicle_name": {"type": "string", "description": "Nom complet du vehicule valide par l'utilisateur (ex: 'MERCEDES-BENZ Classe A 2.0 diesel 140CV'). Passer quand l'utilisateur a choisi depuis les CHOICES."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_pa24_add",
            "description": "Sauvegarde en base les donnees PA24 extraites par propose_pa24_add. Appeler UNIQUEMENT apres confirmation de l'utilisateur.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL du produit PA24 retournee par propose_pa24_add"},
                },
                "required": ["url"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# LLM call with function calling
# ---------------------------------------------------------------------------


async def call_llm_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> dict:
    """Call OpenRouter with tool/function calling support.

    Returns the raw message dict from the API response (may contain
    tool_calls or content or both).
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]


async def chat(chat_id: int, user_message: str) -> dict:
    """Process a user message through the AI layer.

    Returns {"text": str, "tool_calls": list | None} where tool_calls
    contains any function calls the LLM wants to make. The caller
    (ai_functions.py in Step 2) will execute them and call chat_continue().

    For Step 1, this just returns the raw LLM response so we can verify
    the function calling works.
    """
    append_message(chat_id, "user", user_message)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id)

    result = await call_llm_with_tools(messages, tools=TOOLS)

    # Extract text content
    text = result.get("content") or ""

    # Extract tool calls if any
    tool_calls = result.get("tool_calls")

    # Save assistant response to history
    if text:
        append_message(chat_id, "assistant", text)

    return {
        "text": text,
        "tool_calls": tool_calls,
        "raw": result,
    }


MAX_TOOL_ROUNDS = 5


async def handle_message(chat_id: int, user_message: str, on_status=None) -> str:
    """Full conversation turn: LLM call, tool execution loop, final text.

    Handles up to MAX_TOOL_ROUNDS of tool calls before returning.
    on_status: optional async callback(str) to send status messages to the user.
    Returns the final text response from the LLM.
    """
    from src.telegram.ai_functions import execute_tool_call

    append_message(chat_id, "user", user_message)

    for _round in range(MAX_TOOL_ROUNDS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id)
        result = await call_llm_with_tools(messages, tools=TOOLS)

        text = result.get("content") or ""
        tool_calls = result.get("tool_calls")

        if not tool_calls:
            if text:
                append_message(chat_id, "assistant", text)
            return text

        # Save the assistant message with tool calls to history
        # (OpenRouter expects the assistant tool_calls message before tool results)
        assistant_msg = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        _entry = _conversations.setdefault(chat_id, {"messages": [], "last_active": time.time()})
        _entry["last_active"] = time.time()
        _entry["messages"].append(assistant_msg)

        # Execute each tool call and add results
        choices_result = None
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
            except (json.JSONDecodeError, TypeError):
                args = {}

            # Announce long-running searches
            if fn_name == "search_cdg" and on_status:
                ref = args.get("reference", "")
                pname = args.get("part_name", "")
                if ref:
                    await on_status(f"Recherche CDG en cours pour {ref.upper()}...")
                elif pname:
                    await on_status(f"Recherche CDG par designation '{pname}'...")
            elif fn_name == "propose_pa24_add" and on_status:
                await on_status("Recherche sur PiecesAuto24 en cours...")
            elif fn_name == "confirm_pa24_add" and on_status:
                await on_status("Sauvegarde en base en cours...")

            log.info("Tool call: %s(%s)", fn_name, args)
            tool_result = await execute_tool_call(fn_name, args)
            log.info("Tool result (%s): %s", fn_name, tool_result[:200])

            # If result contains CHOICES, short-circuit: return directly
            if "CHOICES:" in tool_result:
                choices_result = tool_result
                append_message(chat_id, "assistant", tool_result)
                break

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": tool_result,
            }
            _entry["messages"].append(tool_msg)

        if choices_result:
            return choices_result

        # Trim history
        if len(_entry["messages"]) > MAX_HISTORY:
            _entry["messages"] = _entry["messages"][-MAX_HISTORY:]

    # Exhausted rounds — return whatever text we have
    return text or "Je n'ai pas pu completer la recherche. Reessayez."
