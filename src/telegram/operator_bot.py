"""Operator-facing Telegram bot. Manages /ref (screenshot ingestion) and /vin flows."""

import json
import logging
import os
import re
import uuid

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_OPERATOR_BOT_TOKEN", "")

# --- Session state per chat ---
# /ref flow: collecting screenshots
# {chat_id: {vehicle: str, part: str, screenshots: [bytes], state: "collecting"|"confirming", extraction: dict}}
ref_sessions: dict[int, dict] = {}

# /vin flow: selecting vehicle for VIN pattern
# {chat_id: {vin: str, brand: str, year: int, explanation: [str], state: str}}
vin_sessions: dict[int, dict] = {}

# Pending confirmations for callback buttons
# {callback_id: {type: "ref"|"vin", data: dict}}
pending_confirms: dict[str, dict] = {}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "\u2699\uFE0F Bot operateur actif.\n"
        "Tapez /guide pour voir les commandes disponibles."
    )


async def cmd_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/guide — Show available commands and what they do."""
    await update.message.reply_text(
        "\U0001F4CB *Commandes disponibles*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "\U0001F4F7 /ajouter\\_ref \\-\\- Ajouter des references\n"
        "  Screenshots PiecesAuto24 \\> extraction auto\\.\n\n"
        "\U0001F522 /vin \\-\\- Associer un VIN\n"
        "  Decode le VIN et propose l'association\\.\n\n"
        "\U0001F4E6 /ref \\-\\- Consulter les references\n"
        "  Marque \\> Modele \\> Annee \\> Moteur \\> Piece\\.\n\n"
        "\U0001F50D /dispo \\-\\- Disponibilite CDG\n"
        "  Texte libre ou boutons\\. Prix et stock live\\.\n\n"
        "\U0001F4CA /stats \\-\\- Statistiques base\n\n"
        "\u2753 /guide \\-\\- Ce message",
        parse_mode="MarkdownV2",
    )


async def cmd_ajouter_ref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ajouter_ref — Start screenshot collection flow for PiecesAuto24 references."""
    chat_id = update.effective_chat.id
    ref_sessions[chat_id] = {
        "vehicle": None,
        "part": None,
        "screenshots": [],
        "state": "collecting",
        "extraction": None,
    }
    keyboard = [[InlineKeyboardButton("\u274C Annuler", callback_data="ref_stop")]]
    await update.message.reply_text(
        "\U0001F4F7 *Ajout de references PiecesAuto24*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Envoyez les screenshots de la page produit\\.\n\n"
        "Le premier screenshot doit montrer le haut de la page "
        "avec le nom complet du vehicule et de la piece\\.\n\n"
        "\U0001F4E4 Envoyez le premier screenshot maintenant\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos — part of /ref screenshot collection."""
    chat_id = update.effective_chat.id

    if chat_id not in ref_sessions:
        await update.message.reply_text("Utilisez /ajouter_ref pour commencer l'ingestion.")
        return

    session = ref_sessions[chat_id]
    if session["state"] != "collecting":
        await update.message.reply_text("Ingestion en cours. Attendez la fin.")
        return

    # Download photo
    photo = update.message.photo[-1]  # highest resolution
    file = await photo.get_file()
    photo_bytes = await file.download_as_bytearray()
    screenshot_num = len(session["screenshots"]) + 1
    session["screenshots"].append(bytes(photo_bytes))

    # First screenshot: detect vehicle + part name
    if screenshot_num == 1:
        vehicle, part = await _detect_vehicle_and_part(photo_bytes)
        if vehicle and part:
            session["vehicle"] = vehicle
            session["part"] = part
            keyboard = [
                [
                    InlineKeyboardButton("Envoyer un autre", callback_data="ref_more"),
                    InlineKeyboardButton("Lancer l'ingestion", callback_data="ref_ingest"),
                ],
                [InlineKeyboardButton("Annuler", callback_data="ref_stop")],
            ]
            await update.message.reply_text(
                f"Vehicule: {vehicle}\n"
                f"Piece: {part}\n"
                f"Screenshot {screenshot_num} recu.\n"
                "Voulez-vous envoyer d'autres screenshots ou lancer l'ingestion?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await update.message.reply_text(
                "Je ne detecte pas le nom du vehicule en haut du screenshot.\n"
                "Le premier screenshot doit montrer le titre de la page produit "
                "PiecesAuto24 avec le nom du vehicule. Reessayez."
            )
            session["screenshots"].pop()  # Remove failed screenshot
    else:
        keyboard = [
            [
                InlineKeyboardButton("Envoyer un autre", callback_data="ref_more"),
                InlineKeyboardButton("Lancer l'ingestion", callback_data="ref_ingest"),
            ],
            [InlineKeyboardButton("Annuler", callback_data="ref_stop")],
        ]
        await update.message.reply_text(
            f"Screenshot {screenshot_num} recu.\n"
            "Envoyer un autre ou lancer l'ingestion?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def handle_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ref flow button presses."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if data == "ref_stop":
        ref_sessions.pop(chat_id, None)
        await query.edit_message_text("Ingestion annulee.")
        return

    if data == "ref_more":
        keyboard = [[InlineKeyboardButton("Annuler", callback_data="ref_stop")]]
        await query.edit_message_text(
            query.message.text + "\n\nEnvoyez le screenshot suivant.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "ref_ingest":
        session = ref_sessions.get(chat_id)
        if not session or not session["screenshots"]:
            await query.edit_message_text("Pas de screenshots. Utilisez /ref.")
            return

        session["state"] = "ingesting"
        await query.edit_message_text("Extraction en cours...")

        # Send all screenshots to LLM for extraction
        extraction = await _extract_from_screenshots(session["screenshots"])
        session["extraction"] = extraction

        # Format summary
        summary = _format_extraction_summary(session["vehicle"], session["part"], extraction)

        confirm_id = str(uuid.uuid4())[:8]
        pending_confirms[confirm_id] = {
            "type": "ref",
            "chat_id": chat_id,
        }

        keyboard = [
            [
                InlineKeyboardButton("Valider et enregistrer", callback_data=f"ref_confirm:{confirm_id}"),
                InlineKeyboardButton("Annuler", callback_data=f"ref_cancel:{confirm_id}"),
            ]
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text=summary,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Confirm/cancel ingestion
    if data.startswith("ref_confirm:") or data.startswith("ref_cancel:"):
        action, confirm_id = data.split(":", 1)

        if confirm_id not in pending_confirms:
            await query.edit_message_text("Confirmation expiree.")
            return

        pending_confirms.pop(confirm_id)
        session = ref_sessions.get(chat_id)

        if action == "ref_cancel" or not session:
            ref_sessions.pop(chat_id, None)
            await query.edit_message_text("Annule.")
            return

        # Save everything to DB and local storage
        result = await _save_ref_data(session)
        ref_sessions.pop(chat_id, None)
        await query.edit_message_text(result)
        return


async def _detect_vehicle_and_part(photo_bytes: bytearray) -> tuple[str | None, str | None]:
    """Use LLM vision to detect vehicle name and part from first screenshot."""
    import base64
    from src.interpreter.llm import call_llm, _parse_json_response

    image_b64 = base64.b64encode(photo_bytes).decode()
    messages = [
        {
            "role": "system",
            "content": (
                "Extract the vehicle name and part name from this PiecesAuto24 screenshot. "
                "The vehicle name is in the page header (e.g. 'PEUGEOT 208 II 3/5 portes (UB_...) 1.2 PureTech'). "
                "The part name is the product category (e.g. 'Filtre a carburant'). "
                "Return ONLY JSON: {\"vehicle\": \"...\", \"part\": \"...\"}\n"
                "If you cannot detect both, return {\"vehicle\": null, \"part\": null}"
            ),
        },
        {"role": "user", "content": "Extract vehicle and part from this screenshot."},
    ]
    try:
        raw = await call_llm(messages, image_base64=image_b64)
        data = _parse_json_response(raw)
        return data.get("vehicle"), data.get("part")
    except Exception as e:
        log.error("Vehicle detection failed: %s", e)
        return None, None


async def _extract_from_screenshots(screenshots: list[bytes]) -> dict:
    """Send all screenshots to LLM vision for full extraction."""
    import base64
    from src.interpreter.llm import call_llm, _parse_json_response
    from src.interpreter.prompts import SYSTEM_PA24_SCREENSHOT

    # Combine all screenshots into one LLM call with multiple images
    # For simplicity, process each screenshot and merge results
    merged = {
        "vehicle": None,
        "part_searched": None,
        "product_scraped": None,
        "specs": {},
        "oe_references": [],
        "equivalents": [],
        "cross_references": [],
        "compatible_vehicles": [],
    }

    for i, photo_bytes in enumerate(screenshots):
        image_b64 = base64.b64encode(photo_bytes).decode()
        messages = [
            {"role": "system", "content": SYSTEM_PA24_SCREENSHOT},
            {"role": "user", "content": f"Screenshot {i + 1} of {len(screenshots)}. Extract all visible data."},
        ]
        try:
            raw = await call_llm(messages, image_base64=image_b64)
            data = _parse_json_response(raw)
            _merge_extraction(merged, data)
        except Exception as e:
            log.error("Extraction failed for screenshot %d: %s", i + 1, e)

    return merged


def _merge_extraction(target: dict, source: dict) -> None:
    """Merge extracted data from one screenshot into the accumulated result."""
    if source.get("vehicle") and not target["vehicle"]:
        target["vehicle"] = source["vehicle"]
    if source.get("part_searched") and not target["part_searched"]:
        target["part_searched"] = source["part_searched"]
    if source.get("product_scraped") and not target["product_scraped"]:
        target["product_scraped"] = source["product_scraped"]
    if source.get("specs"):
        target["specs"].update(source["specs"])

    # Merge lists, avoiding duplicates by ref
    for key in ("oe_references", "equivalents", "cross_references"):
        existing_refs = {_ref_key(r) for r in target[key]}
        for item in source.get(key, []) or []:
            if _ref_key(item) not in existing_refs:
                target[key].append(item)
                existing_refs.add(_ref_key(item))

    # Merge compatible vehicles
    existing_brands = {v.get("brand", "") for v in target["compatible_vehicles"]}
    for item in source.get("compatible_vehicles", []) or []:
        brand = item.get("brand", "")
        if brand not in existing_brands:
            target["compatible_vehicles"].append(item)
            existing_brands.add(brand)


def _ref_key(ref: dict) -> str:
    """Create a dedup key for a reference entry."""
    return f"{ref.get('brand', '')}:{ref.get('ref', ref.get('reference', ''))}".lower()


def _format_extraction_summary(vehicle: str, part: str, extraction: dict) -> str:
    """Format extraction results for operator confirmation."""
    lines = [f"Extraction terminee:"]
    lines.append(f"Vehicule: {vehicle or extraction.get('vehicle', '?')}")
    lines.append(f"Piece: {part or extraction.get('part_searched', '?')}")

    product = extraction.get("product_scraped")
    if product:
        price = f"{product.get('price_eur')} EUR" if product.get("price_eur") else "N/A"
        lines.append(f"Produit principal: {product.get('brand', '?')} {product.get('reference', '?')} -- {price}")

    oe_count = len(extraction.get("oe_references", []))
    eq_count = len(extraction.get("equivalents", []))
    xr_count = len(extraction.get("cross_references", []))
    compat_count = len(extraction.get("compatible_vehicles", []))
    total_refs = oe_count + eq_count + xr_count

    if oe_count:
        oe_refs = ", ".join(f"{r.get('brand', '?')} {r.get('ref', '?')}" for r in extraction["oe_references"][:5])
        lines.append(f"References OE: {oe_refs}" + (f" (+{oe_count - 5})" if oe_count > 5 else ""))
    lines.append(f"Equivalents: {eq_count}")
    lines.append(f"Cross-references: {xr_count}")
    if compat_count:
        lines.append(f"Vehicules compatibles: {compat_count}+ marques")
    lines.append(f"Total: {total_refs} references")

    return "\n".join(lines)


def _sanitize_path(name: str) -> str:
    """Sanitize a name for filesystem use. Preserves parentheses and dots."""
    name = name.lower()
    name = name.replace(" ", "_")
    name = name.replace("/", "-")
    name = re.sub(r"[^a-z0-9_\-\.\(\)]", "", name)
    return name


async def _save_ref_data(session: dict) -> str:
    """Save screenshots to disk and extraction data to DB. Returns summary."""
    from pathlib import Path
    from src.db.repository import (
        upsert_vehicle, insert_reference, insert_compatibility,
        insert_screenshot,
    )
    from src.db.models import Vehicle

    extraction = session["extraction"]
    vehicle_name = session["vehicle"] or extraction.get("vehicle", "unknown")
    part_name = session["part"] or extraction.get("part_searched", "unknown")

    # Parse vehicle name into a Vehicle for upsert
    vehicle = _parse_vehicle_name(vehicle_name)
    vehicle_id = await upsert_vehicle(vehicle)

    # Save screenshots to local filesystem
    _project_root = Path(__file__).resolve().parent.parent.parent
    base_dir = _project_root / "screenshots" / _sanitize_path(vehicle_name) / _sanitize_path(part_name)
    base_dir.mkdir(parents=True, exist_ok=True)

    for i, photo_bytes in enumerate(session["screenshots"]):
        filename = f"screenshot_{i + 1:03d}.png"
        filepath = base_dir / filename
        filepath.write_bytes(photo_bytes)
        await insert_screenshot(vehicle_id, part_name, str(filepath))

    # Save data.json
    data_path = base_dir / "data.json"
    data_path.write_text(json.dumps(extraction, indent=2, ensure_ascii=False))

    # Insert references into DB
    ref_count = 0
    ref_ids: list[int] = []

    # OE references
    for ref_entry in extraction.get("oe_references", []):
        brand = ref_entry.get("brand", "")
        ref_code = ref_entry.get("ref", "")
        if brand and ref_code:
            rid = await insert_reference(vehicle_id, part_name, brand, ref_code, True, source="oe")
            ref_ids.append(rid)
            ref_count += 1

    # Main product as aftermarket reference
    product = extraction.get("product_scraped")
    if product and product.get("brand") and product.get("reference"):
        rid = await insert_reference(
            vehicle_id, part_name, product["brand"], product["reference"],
            False, product.get("price_eur"), source="main_product",
        )
        ref_ids.append(rid)
        ref_count += 1

    # Equivalents
    for eq in extraction.get("equivalents", []):
        brand = eq.get("brand", "")
        ref_code = eq.get("reference", "")
        if brand and ref_code:
            rid = await insert_reference(
                vehicle_id, part_name, brand, ref_code, False, eq.get("price_eur"),
                source="equivalent",
            )
            ref_ids.append(rid)
            ref_count += 1

    # Cross references
    for xr in extraction.get("cross_references", []):
        brand = xr.get("brand", "")
        ref_code = xr.get("reference", "")
        if brand and ref_code:
            rid = await insert_reference(
                vehicle_id, part_name, brand, ref_code, False, xr.get("price_eur"),
                source="cross_reference",
            )
            ref_ids.append(rid)
            ref_count += 1

    # Compatible vehicles — link to all inserted references
    compat_vehicles = extraction.get("compatible_vehicles", [])
    for rid in ref_ids:
        for compat_name in compat_vehicles:
            if isinstance(compat_name, str) and compat_name.strip():
                await insert_compatibility(rid, compat_name.strip())

    return (
        f"{ref_count} references enregistrees pour\n"
        f"{vehicle_name} -- {part_name}"
    )


def _parse_vehicle_name(name: str) -> "Vehicle":
    """Parse a PiecesAuto24 vehicle name into a Vehicle object.

    Example: "PEUGEOT 208 II 3/5 portes (UB_, UP_...) 1.2 PureTech 110"
    """
    from src.db.models import Vehicle

    parts = name.split()
    brand = parts[0] if parts else ""

    # Try to extract displacement (pattern like "1.2", "1.6", "2.0")
    displacement = None
    power_hp = None
    fuel = None
    engine_code = None
    model_parts = []

    for i, p in enumerate(parts[1:], 1):
        if re.match(r"^\d+\.\d+$", p):
            displacement = p
            # Look ahead for power and fuel
            remaining = " ".join(parts[i + 1:])
            hp_match = re.search(r"(\d+)\s*CV", remaining)
            if hp_match:
                power_hp = int(hp_match.group(1))
            if "Diesel" in remaining or "HDi" in remaining or "BlueHDi" in remaining or "dCi" in remaining:
                fuel = "Diesel"
            elif "Essence" in remaining or "PureTech" in remaining or "TSI" in remaining:
                fuel = "Essence"
            # Engine code: typically last word if it's all uppercase letters
            last_words = remaining.split()
            if last_words:
                candidate = last_words[-1]
                if re.match(r"^[A-Z0-9]{3,}$", candidate) and not candidate.endswith("CV"):
                    engine_code = candidate
            break
        else:
            model_parts.append(p)

    model = " ".join(model_parts) if model_parts else ""

    return Vehicle(
        brand=brand,
        model=model,
        displacement=displacement,
        power_hp=power_hp,
        fuel=fuel,
        engine_code=engine_code,
        pa24_full_name=name,
    )


# --- /vin command ---

async def cmd_vin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/vin <VIN> — Decode VIN and associate with a vehicle in DB."""
    chat_id = update.effective_chat.id
    text = update.message.text.replace("/vin", "").strip()

    if not text or len(text) != 17:
        await update.message.reply_text(
            "Associer un VIN a un vehicule en base.\n\n"
            "Usage : /vin <numero VIN 17 caracteres>\n"
            "Exemple : /vin VF32KKFUF44254841\n\n"
            "Le VIN se trouve sur la carte grise (case E) "
            "ou sur la plaque du chassis (bas du pare-brise, portiere)."
        )
        return

    from src.vin.decoder import decode_vin, validate_vin
    try:
        vin = validate_vin(text)
    except ValueError as e:
        await update.message.reply_text(f"VIN invalide: {e}")
        return

    # Decode
    result = await decode_vin(vin)
    explanation = "\n".join(f"  > {line}" for line in result.explanation)

    # Case 1: HIGH confidence (PSA auto-detect or vin_patterns hit)
    if result.confidence.value == "high" and result.vehicle_id:
        confirm_id = str(uuid.uuid4())[:8]
        pending_confirms[confirm_id] = {
            "type": "vin_confirm",
            "vin": vin,
            "vehicle_id": result.vehicle_id,
            "pa24_name": result.pa24_full_name or f"{result.make} {result.model} {result.engine or ''}",
        }
        keyboard = [
            [
                InlineKeyboardButton("Confirmer", callback_data=f"vin_ok:{confirm_id}"),
                InlineKeyboardButton("Corriger", callback_data=f"vin_pick_brand:{confirm_id}"),
            ]
        ]
        await update.message.reply_text(
            f"VIN: {vin}\nDecodage automatique:\n{explanation}\n\n"
            f"Vehicule identifie: {result.pa24_full_name or result.make + ' ' + (result.model or '?')}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Case 2: Brand known but vehicle not identified — show vehicles from DB
    if result.make:
        vin_sessions[chat_id] = {
            "vin": vin,
            "brand": result.make,
            "year": result.year,
            "explanation": result.explanation,
            "state": "pick_vehicle",
        }
        await _show_brand_vehicles(update, chat_id, result.make, vin, explanation)
        return

    # Case 3: WMI unknown — show brand selection
    vin_sessions[chat_id] = {
        "vin": vin,
        "brand": None,
        "year": result.year,
        "explanation": result.explanation,
        "state": "pick_brand",
    }
    await _show_brand_buttons(update, vin, explanation)


async def _show_brand_buttons(update: Update, vin: str, explanation: str) -> None:
    """Show brand selection buttons from DB."""
    from src.db.repository import get_distinct_brands
    brands = await get_distinct_brands()

    if not brands:
        await update.message.reply_text(
            f"VIN: {vin}\n{explanation}\n\n"
            "Aucun vehicule en base. Ajoutez d'abord des vehicules via /ref."
        )
        return

    # Telegram limits: max 100 buttons, organize in rows of 3
    keyboard = []
    row = []
    for brand in brands:
        row.append(InlineKeyboardButton(brand, callback_data=f"vin_brand:{brand}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        f"VIN: {vin}\nDecodage:\n{explanation}\n\n"
        "Selectionnez la marque:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_brand_vehicles(
    update_or_query, chat_id: int, brand: str, vin: str, explanation: str,
) -> None:
    """Show all vehicles for a brand as inline buttons."""
    from src.db.repository import get_vehicles_by_brand
    vehicles = await get_vehicles_by_brand(brand)

    if not vehicles:
        text = (
            f"VIN: {vin}\nDecodage:\n{explanation}\n\n"
            f"Aucun vehicule {brand} en base.\n"
            "Ajoutez-le d'abord via /ref."
        )
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(text)
        else:
            await update_or_query.edit_message_text(text)
        return

    # Build buttons: show pa24_full_name, truncated if needed
    keyboard = []
    for v in vehicles:
        label = v.pa24_full_name[:60] if len(v.pa24_full_name) > 60 else v.pa24_full_name
        keyboard.append([InlineKeyboardButton(label, callback_data=f"vin_vehicle:{v.id}")])

    keyboard.append([InlineKeyboardButton("Vehicule non liste", callback_data="vin_not_listed")])

    text = (
        f"VIN: {vin}\nDecodage:\n{explanation}\n\n"
        f"Selectionnez le vehicule {brand}:"
    )
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update_or_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def handle_vin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /vin flow button presses."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # Confirm auto-detected VIN
    if data.startswith("vin_ok:"):
        confirm_id = data.split(":", 1)[1]
        info = pending_confirms.pop(confirm_id, None)
        if not info:
            await query.edit_message_text("Confirmation expiree.")
            return
        from src.db.repository import add_vin_pattern
        vin_pattern = info["vin"][:13]
        await add_vin_pattern(vin_pattern, info["vehicle_id"])
        await query.edit_message_text(
            f"Enregistre.\nPattern {vin_pattern} -> {info['pa24_name']}"
        )
        return

    # Correct: go to brand selection
    if data.startswith("vin_pick_brand:"):
        confirm_id = data.split(":", 1)[1]
        info = pending_confirms.pop(confirm_id, None)
        if info:
            vin_sessions[chat_id] = {
                "vin": info["vin"],
                "brand": None,
                "year": None,
                "explanation": [],
                "state": "pick_brand",
            }
        session = vin_sessions.get(chat_id)
        if not session:
            await query.edit_message_text("Session expiree. Utilisez /vin.")
            return
        from src.db.repository import get_distinct_brands
        brands = await get_distinct_brands()
        if not brands:
            await query.edit_message_text("Aucun vehicule en base. Utilisez /ref d'abord.")
            return
        keyboard = []
        row = []
        for brand in brands:
            row.append(InlineKeyboardButton(brand, callback_data=f"vin_brand:{brand}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(
            "Selectionnez la marque:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Brand selected
    if data.startswith("vin_brand:"):
        brand = data.split(":", 1)[1]
        session = vin_sessions.get(chat_id)
        if not session:
            await query.edit_message_text("Session expiree. Utilisez /vin.")
            return
        session["brand"] = brand
        session["state"] = "pick_vehicle"
        vin = session["vin"]
        explanation = "\n".join(f"  > {line}" for line in session.get("explanation", []))
        await _show_brand_vehicles(query, chat_id, brand, vin, explanation)
        return

    # Vehicle selected
    if data.startswith("vin_vehicle:"):
        vehicle_id = int(data.split(":", 1)[1])
        session = vin_sessions.get(chat_id)
        if not session:
            await query.edit_message_text("Session expiree. Utilisez /vin.")
            return

        from src.db.repository import get_vehicle_by_id
        vehicle = await get_vehicle_by_id(vehicle_id)
        if not vehicle:
            await query.edit_message_text("Vehicule non trouve.")
            return

        confirm_id = str(uuid.uuid4())[:8]
        pending_confirms[confirm_id] = {
            "type": "vin_confirm",
            "vin": session["vin"],
            "vehicle_id": vehicle_id,
            "pa24_name": vehicle.pa24_full_name,
        }
        keyboard = [
            [
                InlineKeyboardButton("Confirmer", callback_data=f"vin_ok:{confirm_id}"),
                InlineKeyboardButton("Annuler", callback_data=f"vin_cancel:{confirm_id}"),
            ]
        ]
        vin_pattern = session["vin"][:13]
        await query.edit_message_text(
            f"Pattern {vin_pattern} -> {vehicle.pa24_full_name}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        vin_sessions.pop(chat_id, None)
        return

    # Vehicle not listed
    if data == "vin_not_listed":
        vin_sessions.pop(chat_id, None)
        await query.edit_message_text(
            "Ce vehicule n'est pas dans la base.\n"
            "Ajoutez-le d'abord via /ref avec des screenshots PiecesAuto24."
        )
        return

    # Cancel
    if data.startswith("vin_cancel:"):
        confirm_id = data.split(":", 1)[1]
        pending_confirms.pop(confirm_id, None)
        vin_sessions.pop(chat_id, None)
        await query.edit_message_text("Annule.")
        return


# --- /get command (reference lookup) ---

# /get session: {chat_id: {state, vehicle_id, vehicle_name, brand}}
get_sessions: dict[int, dict] = {}



async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/get — Look up references for a vehicle+part from DB."""
    chat_id = update.effective_chat.id
    get_sessions[chat_id] = {"state": "pick_brand", "vehicle_id": None, "vehicle_name": None}

    from src.db.repository import get_distinct_brands
    brands = await get_distinct_brands()
    if not brands:
        await update.message.reply_text("Aucun vehicule en base.")
        return

    keyboard = []
    row = []
    for brand in brands:
        row.append(InlineKeyboardButton(brand, callback_data=f"get_brand:{brand}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "\U0001F3E2 Selectionnez la marque :", reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_get_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /get flow callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    session = get_sessions.get(chat_id)

    if data == "noop":
        return

    if not session:
        await query.edit_message_text("Session expiree. Utilisez /ref.")
        return

    # Back buttons for /get
    if data == "getback_brands":
        from src.db.repository import get_distinct_brands
        brands = await get_distinct_brands()
        keyboard = []
        row = []
        for brand in brands:
            row.append(InlineKeyboardButton(brand, callback_data=f"get_brand:{brand}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(
            "\U0001F3E2 Selectionnez la marque :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "getback_models":
        brand = session.get("brand", "")
        from src.db.repository import get_distinct_models
        models = await get_distinct_models(brand)
        session["models"] = models
        session.pop("family", None)
        from src.telegram.ui import render_model_keyboard
        keyboard, used_families = render_model_keyboard(
            brand, models, "get_model", "get_family", back_cb="getback_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"\U0001F697 Selectionnez le modele {brand} :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Family selected -> show variants
    if data.startswith("get_family:"):
        family = data.split(":", 1)[1]
        brand = session.get("brand", "")
        models = session.get("models", [])
        from src.telegram.ui import group_families, render_variants_keyboard
        groups = group_families(models)
        indices = groups.get(family, [])
        if not indices:
            await query.edit_message_text("Famille introuvable.")
            return
        session["family"] = family
        keyboard = render_variants_keyboard(
            brand, models, indices, "get_model", back_cb="getback_models",
        )
        await query.edit_message_text(
            f"\U0001F697 {brand} {family} — variante :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "getback_years":
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _get_show_years(query, session, brand, model)
        return

    if data == "getback_fuels":
        brand = session.get("brand", "")
        model = session.get("model", "")
        year_min = session.get("year_min")
        year_max = session.get("year_max")
        if year_min and year_max:
            from src.db.repository import get_fuels_for_model_years
            fuels = await get_fuels_for_model_years(brand, model, year_min, year_max)
        else:
            from src.db.repository import get_fuels_for_model
            fuels = await get_fuels_for_model(brand, model)
        if len(fuels) <= 1:
            # No fuel step — go back to years
            await _get_show_years(query, session, brand, model)
            return
        keyboard = []
        row = []
        for f in fuels:
            row.append(InlineKeyboardButton(f, callback_data=f"get_fuel:{f}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="getback_years")])
        await query.edit_message_text(
            f"{model} — carburant :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "getback_motors":
        brand = session.get("brand", "")
        model = session.get("model", "")
        fuel = session.get("fuel")
        year_min = session.get("year_min")
        year_max = session.get("year_max")
        if year_min and year_max:
            from src.db.repository import get_motorisations_for_years
            motors = await get_motorisations_for_years(brand, model, fuel, year_min, year_max)
        else:
            from src.db.repository import get_motorisations
            motors = await get_motorisations(brand, model, fuel)
        session["motors"] = motors
        keyboard = []
        for i, m in enumerate(motors):
            fuel_d = m["fuel"].lower() if m["fuel"] else ""
            label = f"{m['displacement']} {fuel_d} {m['power_hp']}CV"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"get_motor:{i}")])
        if year_min and year_max:
            from src.db.repository import get_fuels_for_model_years
            fuels = await get_fuels_for_model_years(brand, model, year_min, year_max)
        else:
            from src.db.repository import get_fuels_for_model
            fuels = await get_fuels_for_model(brand, model)
        back_cb = "getback_fuels" if len(fuels) > 1 else "getback_years"
        keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
        await query.edit_message_text(
            f"Motorisation {brand} {model} :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Brand selected
    if data.startswith("get_brand:"):
        brand = data.split(":", 1)[1]
        session["brand"] = brand
        session["state"] = "pick_model"
        from src.db.repository import get_distinct_models
        models = await get_distinct_models(brand)
        if not models:
            await query.edit_message_text(f"Aucun modele {brand} en base.")
            return
        session["models"] = models
        session.pop("family", None)
        from src.telegram.ui import render_model_keyboard
        keyboard, used_families = render_model_keyboard(
            brand, models, "get_model", "get_family", back_cb="getback_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"\U0001F697 Selectionnez le modele {brand} :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Model selected — show year ranges
    if data.startswith("get_model:"):
        idx = int(data.split(":", 1)[1])
        brand = session.get("brand", "")
        models = session.get("models", [])
        model = models[idx] if idx < len(models) else ""
        session["model"] = model
        await _get_show_years(query, session, brand, model)
        return

    # Year range selected
    if data.startswith("get_year:"):
        parts = data.split(":", 1)[1].split("-")
        year_min, year_max = int(parts[0]), int(parts[1])
        session["year_min"] = year_min
        session["year_max"] = year_max
        brand = session.get("brand", "")
        model = session.get("model", "")
        from src.db.repository import get_fuels_for_model_years
        fuels = await get_fuels_for_model_years(brand, model, year_min, year_max)
        if not fuels:
            await query.edit_message_text(f"Aucune motorisation pour {brand} {model} {year_min}-{year_max}.")
            return
        if len(fuels) > 1:
            session["state"] = "pick_fuel"
            keyboard = []
            row = []
            for f in fuels:
                row.append(InlineKeyboardButton(f, callback_data=f"get_fuel:{f}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="getback_years")])
            await query.edit_message_text(
                f"{model} ({year_min}-{year_max}) — carburant :", reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        # Single fuel — skip to motors
        fuel = fuels[0]
        session["fuel"] = fuel
        await _get_show_motors(query, session, brand, model, fuel)
        return

    # Fuel selected
    if data.startswith("get_fuel:"):
        fuel = data.split(":", 1)[1]
        session["fuel"] = fuel
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _get_show_motors(query, session, brand, model, fuel)
        return

    # Motorisation selected
    if data.startswith("get_motor:"):
        idx = int(data.split(":", 1)[1])
        motors = session.get("motors", [])
        if idx >= len(motors):
            await query.edit_message_text("Motorisation introuvable.")
            return
        m = motors[idx]
        brand = session.get("brand", "")
        model = session.get("model", "")
        year_min = session.get("year_min")
        year_max = session.get("year_max")
        if year_min and year_max:
            from src.db.repository import get_vehicle_ids_for_motorisation_years
            vids = await get_vehicle_ids_for_motorisation_years(
                brand, model, m["fuel"], m["displacement"], m["power_hp"], year_min, year_max,
            )
        else:
            from src.db.repository import get_vehicle_ids_for_motorisation
            vids = await get_vehicle_ids_for_motorisation(brand, model, m["fuel"], m["displacement"], m["power_hp"])
        if not vids:
            await query.edit_message_text("Vehicule non trouve.")
            return
        session["vehicle_ids"] = vids
        session["vehicle_id"] = vids[0]
        fuel_d = m["fuel"].lower() if m["fuel"] else ""
        session["vehicle_name"] = f"{brand} {model} {m['displacement']} {fuel_d} {m['power_hp']}CV"
        session["state"] = "pick_part"
        await _show_parts_list(query, session)
        return

    # Part category selected
    if data.startswith("get_part_cat:"):
        cat_idx = int(data.split(":", 1)[1])
        await _show_get_parts_in_category(query, session, cat_idx)
        return

    # Back to part categories
    if data == "getback_part_cats":
        await _show_parts_list(query, session)
        return

    # Part selected by index
    if data.startswith("get_part:"):
        idx = int(data.split(":", 1)[1])
        parts = session.get("parts", [])
        if idx < len(parts):
            await _display_refs(query, chat_id, parts[idx])
        else:
            await query.edit_message_text("Piece non trouvee.")
        return

    # Another part
    if data == "get_another":
        await _show_parts_list(query, session)
        return


async def _get_show_years(query, session: dict, brand: str, model: str) -> None:
    """Show year range buttons for /get flow. Skips if span <= 5 years."""
    from src.db.repository import get_year_range_for_model
    from src.telegram.ui import generate_year_ranges
    min_year, max_year = await get_year_range_for_model(brand, model)
    if not min_year or not max_year:
        # No year data — skip to fuel
        session["year_min"] = None
        session["year_max"] = None
        from src.db.repository import get_fuels_for_model
        fuels = await get_fuels_for_model(brand, model)
        if not fuels:
            await query.edit_message_text(f"Aucune motorisation pour {brand} {model}.")
            return
        if len(fuels) > 1:
            session["state"] = "pick_fuel"
            keyboard = []
            row = []
            for f in fuels:
                row.append(InlineKeyboardButton(f, callback_data=f"get_fuel:{f}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="getback_models")])
            await query.edit_message_text(
                f"{model} — carburant :", reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        fuel = fuels[0]
        session["fuel"] = fuel
        await _get_show_motors(query, session, brand, model, fuel)
        return

    ranges = generate_year_ranges(min_year, max_year)
    if len(ranges) == 1:
        # Single range — skip year step, use it directly
        session["year_min"] = ranges[0][0]
        session["year_max"] = ranges[0][1]
        from src.db.repository import get_fuels_for_model_years
        fuels = await get_fuels_for_model_years(brand, model, ranges[0][0], ranges[0][1])
        if not fuels:
            await query.edit_message_text(f"Aucune motorisation pour {brand} {model}.")
            return
        if len(fuels) > 1:
            session["state"] = "pick_fuel"
            keyboard = []
            row = []
            for f in fuels:
                row.append(InlineKeyboardButton(f, callback_data=f"get_fuel:{f}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="getback_models")])
            await query.edit_message_text(
                f"{model} — carburant :", reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        fuel = fuels[0]
        session["fuel"] = fuel
        await _get_show_motors(query, session, brand, model, fuel)
        return

    session["state"] = "pick_year"
    keyboard = []
    row = []
    for yr_min, yr_max in ranges:
        label = f"{yr_min}-{yr_max}"
        row.append(InlineKeyboardButton(label, callback_data=f"get_year:{yr_min}-{yr_max}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="getback_models")])
    await query.edit_message_text(
        f"{brand} {model} — annees :", reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _get_show_motors(query, session: dict, brand: str, model: str, fuel: str) -> None:
    """Show motorisation buttons for /get flow."""
    year_min = session.get("year_min")
    year_max = session.get("year_max")
    if year_min and year_max:
        from src.db.repository import get_motorisations_for_years, get_vehicle_ids_for_motorisation_years, get_fuels_for_model_years
        motors = await get_motorisations_for_years(brand, model, fuel, year_min, year_max)
    else:
        from src.db.repository import get_motorisations
        motors = await get_motorisations(brand, model, fuel)
    if not motors:
        await query.edit_message_text(f"Aucune motorisation pour {brand} {model}.")
        return
    if len(motors) == 1:
        m = motors[0]
        if year_min and year_max:
            from src.db.repository import get_vehicle_ids_for_motorisation_years
            vids = await get_vehicle_ids_for_motorisation_years(
                brand, model, m["fuel"], m["displacement"], m["power_hp"], year_min, year_max,
            )
        else:
            from src.db.repository import get_vehicle_ids_for_motorisation
            vids = await get_vehicle_ids_for_motorisation(brand, model, m["fuel"], m["displacement"], m["power_hp"])
        session["vehicle_ids"] = vids
        session["vehicle_id"] = vids[0] if vids else None
        fuel_d = m["fuel"].lower() if m["fuel"] else ""
        session["vehicle_name"] = f"{brand} {model} {m['displacement']} {fuel_d} {m['power_hp']}CV"
        session["state"] = "pick_part"
        await _show_parts_list(query, session)
        return
    session["state"] = "pick_motor"
    session["motors"] = motors
    keyboard = []
    for i, m in enumerate(motors):
        fuel_d = m["fuel"].lower() if m["fuel"] else ""
        label = f"{m['displacement']} {fuel_d} {m['power_hp']}CV"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"get_motor:{i}")])
    if year_min and year_max:
        from src.db.repository import get_fuels_for_model_years
        fuels = await get_fuels_for_model_years(brand, model, year_min, year_max)
    else:
        from src.db.repository import get_fuels_for_model
        fuels = await get_fuels_for_model(brand, model)
    back_cb = "getback_fuels" if len(fuels) > 1 else "getback_years"
    keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    await query.edit_message_text(
        f"Motorisation {brand} {model} :", reply_markup=InlineKeyboardMarkup(keyboard),
    )


def _short_engine_label(v) -> str:
    parts = []
    if v.displacement:
        parts.append(v.displacement)
    if v.power_hp:
        parts.append(f"{v.power_hp}CV")
    if v.fuel:
        parts.append(v.fuel)
    if v.engine_code:
        parts.append(v.engine_code)
    return " ".join(parts) if parts else v.pa24_full_name[:40]


async def _show_parts_list(query, session: dict) -> None:
    """Show part categories for the selected vehicle(s) from DB."""
    vids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    if len(vids) > 1:
        from src.db.repository import get_parts_for_vehicles
        parts = await get_parts_for_vehicles(vids)
    else:
        from src.db.repository import get_parts_for_vehicle
        parts = await get_parts_for_vehicle(vids[0]) if vids else []
    session["parts"] = parts

    if not parts:
        await query.edit_message_text(
            f"\u26A0\uFE0F {session['vehicle_name']}\n\nAucune piece en base pour ce vehicule.",
        )
        return

    from src.telegram.ui import build_category_keyboard, categorize_parts
    cat_kb = build_category_keyboard(parts, "get_part_cat", back_cb="getback_motors")
    if cat_kb:
        session["state"] = "pick_part_cat"
        await query.edit_message_text(
            f"\U0001F697 {session['vehicle_name']}\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F527 Selectionnez la categorie :",
            reply_markup=InlineKeyboardMarkup(cat_kb),
        )
    else:
        cats = categorize_parts(parts)
        await _show_get_parts_in_category(query, session, cats[0][0])


async def _show_get_parts_in_category(query, session: dict, cat_idx: int) -> None:
    """Show parts within a category for /ref flow."""
    parts = session.get("parts", [])
    from src.telegram.ui import build_category_parts_keyboard, categorize_parts
    cats = categorize_parts(parts)
    cat_name = "Autres"
    for ci, cn, _ in cats:
        if ci == cat_idx:
            cat_name = cn
            break
    back_cb = "getback_part_cats" if len(cats) > 1 else "getback_motors"
    keyboard = build_category_parts_keyboard(parts, cat_idx, "get_part", back_cb)
    await query.edit_message_text(
        f"\U0001F697 {session['vehicle_name']}\n"
        f"\U0001F527 {cat_name} :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _display_refs(query, chat_id: int, part_name: str) -> None:
    """Display references from DB for operator, grouped by type."""
    session = get_sessions.get(chat_id)
    if not session or not session["vehicle_id"]:
        await query.edit_message_text("Session expiree.")
        return

    vids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    from src.db.repository import lookup_references_grouped
    grouped = await lookup_references_grouped(vids[0], part_name)

    oe = grouped["oe"]
    main = grouped["main_product"]
    equiv = grouped["equivalent"]
    xref = grouped["cross_reference"]

    lines = [
        f"\U0001F697 {session['vehicle_name']}",
        f"\U0001F527 {part_name}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
    ]

    if oe:
        lines.append("\U0001F3ED References OE (constructeur) :")
        for r in oe:
            lines.append(f"  \u2022 {r.brand} \u2014 {r.reference}")
        lines.append("")

    combined_equiv = main + equiv
    if combined_equiv:
        lines.append("\U0001F504 References equivalentes :")
        for r in combined_equiv:
            lines.append(f"  \u2022 {r.brand} \u2014 {r.reference}")
        lines.append("")

    if xref:
        lines.append("\U0001F517 Cross-references :")
        for r in xref:
            lines.append(f"  \u2022 {r.brand} \u2014 {r.reference}")
        lines.append("")

    total = len(oe) + len(combined_equiv) + len(xref)
    if total == 0:
        lines.append("\u26A0\uFE0F Aucune reference en base pour cette piece.")
    else:
        lines.append(f"\U0001F4CA Total: {total} references")

    keyboard = [[InlineKeyboardButton("\U0001F527 Autre piece", callback_data="get_another")]]
    await query.edit_message_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard),
    )


# --- /dispo command (CDG availability check) ---

# /dispo sessions: {chat_id: {state, vehicle_id, vehicle_name, brand, models, parts, confirmed_part, pending_part, pending_reference}}
dispo_sessions: dict[int, dict] = {}


async def cmd_dispo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dispo — Check part availability and price on CDG."""
    chat_id = update.effective_chat.id
    text = update.message.text.replace("/dispo", "").strip()

    if not text:
        # No text — start vehicle selection
        dispo_sessions[chat_id] = {"state": "pick_brand", "vehicle_id": None, "vehicle_name": None}
        from src.db.repository import get_distinct_brands
        brands = await get_distinct_brands()
        if not brands:
            await update.message.reply_text("Aucun vehicule en base.")
            return
        keyboard = []
        row = []
        for brand in brands:
            row.append(InlineKeyboardButton(brand, callback_data=f"dispo_brand:{brand}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await update.message.reply_text(
            "\U0001F50D *Disponibilite CDG*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F3E2 Selectionnez la marque, ou tapez :\n"
            "`/dispo Kia Picanto filtre a huile`\n"
            "`/dispo K015578XS`",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Text provided — use same LLM parsing as client bot
    dispo_sessions[chat_id] = {"state": "parsing", "vehicle_id": None, "vehicle_name": None}
    session = dispo_sessions[chat_id]

    # Check if bare reference
    if (re.match(r"^[A-Za-z0-9][-A-Za-z0-9./]{3,25}$", text.strip())
            and not text.strip().isdigit()
            and re.search(r"\d", text.strip())):
        await update.message.reply_text(
            f"\U0001F50D Recherche CDG en cours...\n\nReference : {text.strip().upper()}"
        )
        from src.chain import search_reference
        result_text = await search_reference(text.strip().upper())
        try:
            await update.message.reply_text(result_text, parse_mode="MarkdownV2")
        except Exception:
            await update.message.reply_text(result_text.replace("\\", ""))
        dispo_sessions.pop(chat_id, None)
        return

    # Try LLM parsing for brand+model+part
    from src.interpreter.llm import parse_vehicle_query
    from src.db.repository import get_distinct_brands, get_distinct_models

    brands_list = await get_distinct_brands()
    try:
        data = await parse_vehicle_query(text, brands_list)
    except Exception:
        await update.message.reply_text("Impossible d'interpreter la demande.")
        dispo_sessions.pop(chat_id, None)
        return

    reference = data.get("reference")
    if reference:
        await update.message.reply_text(
            f"\U0001F50D Recherche CDG en cours...\n\nReference : {reference}"
        )
        from src.chain import search_reference
        result_text = await search_reference(reference)
        try:
            await update.message.reply_text(result_text, parse_mode="MarkdownV2")
        except Exception:
            await update.message.reply_text(result_text.replace("\\", ""))
        dispo_sessions.pop(chat_id, None)
        return

    brand = data.get("brand")
    model = data.get("model")
    part = data.get("part")

    if not brand:
        await update.message.reply_text(
            "\u2753 Marque non reconnue. Precisez la marque (ex: Volkswagen Polo 6) "
            "ou utilisez /dispo sans texte."
        )
        dispo_sessions.pop(chat_id, None)
        return

    matched_brand = None
    for b in brands_list:
        if b.upper() == brand.upper():
            matched_brand = b
            break
    if not matched_brand:
        await update.message.reply_text(f"Marque '{brand}' non trouvee en base.")
        dispo_sessions.pop(chat_id, None)
        return

    session["brand"] = matched_brand
    session["pending_part"] = part

    if model:
        models = await get_distinct_models(matched_brand)
        matched_model = None
        for m in models:
            if m.upper() == model.upper():
                matched_model = m
                break
        if matched_model:
            session["model"] = matched_model
            from src.db.repository import get_fuels_for_model, get_motorisations
            fuels = await get_fuels_for_model(matched_brand, matched_model)
            if not fuels:
                await update.message.reply_text(f"Aucune motorisation pour {matched_brand} {matched_model}.")
                dispo_sessions.pop(chat_id, None)
                return
            if len(fuels) > 1:
                session["state"] = "pick_fuel"
                keyboard = []
                row = []
                for f in fuels:
                    row.append(InlineKeyboardButton(f, callback_data=f"dispo_fuel:{f}"))
                    if len(row) == 2:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="dispoback_models")])
                await update.message.reply_text(
                    f"{matched_brand} {matched_model} — carburant :",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            fuel = fuels[0]
            session["fuel"] = fuel
            motors = await get_motorisations(matched_brand, matched_model, fuel)
            if not motors:
                await update.message.reply_text(f"Aucune motorisation pour {matched_brand} {matched_model}.")
                dispo_sessions.pop(chat_id, None)
                return
            if len(motors) == 1:
                m = motors[0]
                from src.db.repository import get_vehicle_ids_for_motorisation
                vehicle_ids = await get_vehicle_ids_for_motorisation(
                    matched_brand, matched_model, m["fuel"], m["displacement"], m["power_hp"],
                )
                if not vehicle_ids:
                    await update.message.reply_text("Aucun vehicule trouve.")
                    dispo_sessions.pop(chat_id, None)
                    return
                session["vehicle_ids"] = vehicle_ids
                session["vehicle_id"] = vehicle_ids[0]
                fuel_display = m["fuel"].lower() if m["fuel"] else ""
                session["vehicle_name"] = f"{matched_brand} {matched_model} {m['displacement']} {fuel_display} {m['power_hp']}CV"
                pending = session.get("pending_part")
                if pending:
                    await _dispo_resolve_and_search(update, chat_id, pending)
                else:
                    await _dispo_show_parts(update, chat_id)
                return
            session["state"] = "pick_motor"
            session["motors"] = motors
            keyboard = []
            for i, m in enumerate(motors):
                label = _dispo_format_motor_button(m["displacement"], m["fuel"], m["power_hp"])
                keyboard.append([InlineKeyboardButton(label, callback_data=f"dispo_motor:{i}")])
            keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="dispoback_models")])
            await update.message.reply_text(
                f"Motorisation {matched_brand} {matched_model} :",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

    # Brand only — show models
    session["state"] = "pick_model"
    models = await get_distinct_models(matched_brand)
    session["models"] = models
    session.pop("family", None)
    from src.telegram.ui import render_model_keyboard
    keyboard, used_families = render_model_keyboard(
        matched_brand, models, "dispo_model", "dispo_family", back_cb="dispoback_brands",
    )
    session["use_families"] = used_families
    await update.message.reply_text(
        f"\U0001F697 Selectionnez le modele {matched_brand} :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _dispo_resolve_and_search(update_or_query, chat_id: int, part_text: str) -> None:
    """Resolve part name then search CDG for the operator."""
    session = dispo_sessions.get(chat_id)
    if not session or not session.get("vehicle_ids"):
        return

    vehicle_ids = session["vehicle_ids"]

    # Use client bot's matching logic
    from src.telegram.client_bot import _match_part_to_db
    matched = await _match_part_to_db(vehicle_ids, part_text)

    # Handle __not_available__
    if len(matched) == 1 and matched[0].startswith("__not_available__:"):
        interpreted = matched[0].split(":", 1)[1]
        matched = []
        part_text = interpreted

    is_query = hasattr(update_or_query, 'edit_message_text')

    if len(matched) == 1:
        await _dispo_do_search(update_or_query, chat_id, matched[0])
        return

    if len(matched) > 1:
        session["parts"] = matched
        from src.telegram.ui import build_parts_keyboard
        keyboard = build_parts_keyboard(matched, "dispo_part")
        text = "Precisez la piece :"
        if is_query:
            await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # No match — show all parts
    from src.db.repository import get_parts_for_vehicles
    from src.telegram.ui import build_parts_keyboard
    all_parts = await get_parts_for_vehicles(vehicle_ids)
    session["parts"] = all_parts
    keyboard = build_parts_keyboard(all_parts, "dispo_part")
    msg = f"'{part_text}' non disponible.\nSelectionnez :"
    if is_query:
        await update_or_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


def _dispo_format_motor_button(displacement: str, fuel: str, power_hp: int) -> str:
    """Format motorisation button for dispo flow."""
    fuel_display = fuel.lower() if fuel else ""
    return f"{displacement} {fuel_display} {power_hp}CV"


async def _dispo_show_fuel_or_motors(query, chat_id: int, session: dict, brand: str, model: str) -> None:
    """After model selected: show fuel step if multiple fuels, else skip to motors."""
    from src.db.repository import get_fuels_for_model
    fuels = await get_fuels_for_model(brand, model)
    if len(fuels) > 1:
        session["state"] = "pick_fuel"
        keyboard = []
        row = []
        for f in fuels:
            row.append(InlineKeyboardButton(f, callback_data=f"dispo_fuel:{f}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="dispoback_models")])
        await query.edit_message_text(
            f"{brand} {model} — carburant :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        fuel = fuels[0] if fuels else None
        session["fuel"] = fuel
        await _dispo_show_motors(query, chat_id, session, brand, model, fuel)


async def _dispo_show_motors(query, chat_id: int, session: dict, brand: str, model: str, fuel: str | None) -> None:
    """Show motorisation buttons grouped by displacement+fuel+power."""
    from src.db.repository import get_motorisations
    motors = await get_motorisations(brand, model, fuel)
    if not motors:
        await query.edit_message_text(f"Aucune motorisation pour {brand} {model}.")
        return
    if len(motors) == 1:
        m = motors[0]
        await _dispo_select_motorisation(query, chat_id, session, brand, model,
                                         m["fuel"], m["displacement"], m["power_hp"])
        return
    session["state"] = "pick_motor"
    session["motors"] = motors
    keyboard = []
    for i, m in enumerate(motors):
        label = _dispo_format_motor_button(m["displacement"], m["fuel"], m["power_hp"])
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dispo_motor:{i}")])
    from src.db.repository import get_fuels_for_model
    fuels = await get_fuels_for_model(brand, model)
    back_cb = "dispoback_fuels" if fuel and len(fuels) > 1 else "dispoback_models"
    keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    await query.edit_message_text(
        f"Motorisation {brand} {model} :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _dispo_select_motorisation(
    query, chat_id: int, session: dict, brand: str, model: str,
    fuel: str, displacement: str, power_hp: int,
) -> None:
    """Resolve motorisation to vehicle IDs and proceed."""
    from src.db.repository import get_vehicle_ids_for_motorisation
    vehicle_ids = await get_vehicle_ids_for_motorisation(brand, model, fuel, displacement, power_hp)
    if not vehicle_ids:
        await query.edit_message_text("Aucun vehicule trouve.")
        return
    session["vehicle_ids"] = vehicle_ids
    session["vehicle_id"] = vehicle_ids[0]
    fuel_display = fuel.lower() if fuel else ""
    session["vehicle_name"] = f"{brand} {model} {displacement} {fuel_display} {power_hp}CV"

    pending = session.get("pending_part")
    if pending:
        await _dispo_resolve_and_search(query, chat_id, pending)
    else:
        await _dispo_show_parts(query, chat_id)


async def _dispo_show_parts(update_or_query, chat_id: int) -> None:
    """Show part categories for the dispo vehicle."""
    session = dispo_sessions.get(chat_id)
    if not session:
        return
    from src.db.repository import get_parts_for_vehicles
    vehicle_ids = session.get("vehicle_ids", [session["vehicle_id"]])
    parts = await get_parts_for_vehicles(vehicle_ids)
    session["parts"] = parts

    is_query = hasattr(update_or_query, 'edit_message_text')

    if not parts:
        text = "\u26A0\uFE0F Aucune piece en base pour ce vehicule."
        if is_query:
            await update_or_query.edit_message_text(text)
        else:
            await update_or_query.message.reply_text(text)
        return

    from src.telegram.ui import build_category_keyboard, categorize_parts
    cat_kb = build_category_keyboard(parts, "dispo_part_cat", back_cb="dispoback_motors")
    if cat_kb:
        session["state"] = "pick_part_cat"
        text = (
            f"\U0001F697 {session['vehicle_name']}\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F527 Selectionnez la categorie :"
        )
        if is_query:
            await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(cat_kb))
        else:
            await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(cat_kb))
    else:
        cats = categorize_parts(parts)
        await _dispo_show_parts_in_category(update_or_query, chat_id, cats[0][0])


async def _dispo_show_parts_in_category(update_or_query, chat_id: int, cat_idx: int) -> None:
    """Show parts within a category for /dispo flow."""
    session = dispo_sessions.get(chat_id)
    if not session:
        return
    parts = session.get("parts", [])
    from src.telegram.ui import build_category_parts_keyboard, categorize_parts
    cats = categorize_parts(parts)
    cat_name = "Autres"
    for ci, cn, _ in cats:
        if ci == cat_idx:
            cat_name = cn
            break
    back_cb = "dispoback_part_cats" if len(cats) > 1 else "dispoback_motors"
    keyboard = build_category_parts_keyboard(parts, cat_idx, "dispo_part", back_cb)
    text = (
        f"\U0001F697 {session['vehicle_name']}\n"
        f"\U0001F527 {cat_name} :"
    )
    is_query = hasattr(update_or_query, 'edit_message_text')
    if is_query:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _dispo_do_search(update_or_query, chat_id: int, part_name: str) -> None:
    """Search CDG for a vehicle+part and show results."""
    session = dispo_sessions.get(chat_id)
    if not session:
        return

    vehicle_ids = session.get("vehicle_ids", [session["vehicle_id"]])
    vehicle_name = session["vehicle_name"]
    is_query = hasattr(update_or_query, 'edit_message_text')

    loading = f"\U0001F50D Recherche CDG en cours...\n\n\U0001F697 {vehicle_name}\n\U0001F527 {part_name}"
    if is_query:
        await update_or_query.edit_message_text(loading)
    else:
        await update_or_query.message.reply_text(loading)

    from src.chain import search_part
    result_text = await search_part(vehicle_ids, vehicle_name, part_name)

    keyboard = [
        [InlineKeyboardButton("\U0001F527 Autre piece", callback_data="dispo_another")],
    ]
    if is_query:
        try:
            await update_or_query.edit_message_text(result_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await update_or_query.edit_message_text(result_text.replace("\\", ""), reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        try:
            await update_or_query.message.reply_text(result_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await update_or_query.message.reply_text(result_text.replace("\\", ""), reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_dispo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dispo flow callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    session = dispo_sessions.get(chat_id)

    if not session:
        await query.edit_message_text("Session expiree. Utilisez /dispo.")
        return

    # Back buttons for /dispo
    if data == "dispoback_brands":
        from src.db.repository import get_distinct_brands
        brands = await get_distinct_brands()
        keyboard = []
        row = []
        for brand in brands:
            row.append(InlineKeyboardButton(brand, callback_data=f"dispo_brand:{brand}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(
            "\U0001F3E2 Selectionnez la marque :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "dispoback_models":
        brand = session.get("brand", "")
        from src.db.repository import get_distinct_models
        from src.telegram.ui import render_model_keyboard
        models = await get_distinct_models(brand)
        session["models"] = models
        session.pop("family", None)
        keyboard, used_families = render_model_keyboard(
            brand, models, "dispo_model", "dispo_family", back_cb="dispoback_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"\U0001F697 Selectionnez le modele {brand} :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("dispo_family:"):
        family = data.split(":", 1)[1]
        brand = session.get("brand", "")
        models = session.get("models", [])
        from src.telegram.ui import group_families, render_variants_keyboard
        groups = group_families(models)
        indices = groups.get(family, [])
        if not indices:
            await query.edit_message_text("Famille introuvable.")
            return
        session["family"] = family
        keyboard = render_variants_keyboard(
            brand, models, indices, "dispo_model", back_cb="dispoback_models",
        )
        await query.edit_message_text(
            f"\U0001F697 {brand} {family} — variante :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "dispoback_fuels":
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _dispo_show_fuel_or_motors(query, chat_id, session, brand, model)
        return

    if data == "dispoback_motors":
        brand = session.get("brand", "")
        model = session.get("model", "")
        fuel = session.get("fuel")
        await _dispo_show_motors(query, chat_id, session, brand, model, fuel)
        return

    if data.startswith("dispo_brand:"):
        brand = data.split(":", 1)[1]
        session["brand"] = brand
        session["state"] = "pick_model"
        from src.db.repository import get_distinct_models
        from src.telegram.ui import render_model_keyboard
        models = await get_distinct_models(brand)
        if not models:
            await query.edit_message_text(f"Aucun modele {brand} en base.")
            return
        session["models"] = models
        session.pop("family", None)
        keyboard, used_families = render_model_keyboard(
            brand, models, "dispo_model", "dispo_family", back_cb="dispoback_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"\U0001F697 Selectionnez le modele {brand} :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("dispo_model:"):
        idx = int(data.split(":", 1)[1])
        brand = session.get("brand", "")
        models = session.get("models", [])
        model = models[idx] if idx < len(models) else ""
        session["model"] = model
        await _dispo_show_fuel_or_motors(query, chat_id, session, brand, model)
        return

    if data.startswith("dispo_fuel:"):
        fuel = data.split(":", 1)[1]
        brand = session.get("brand", "")
        model = session.get("model", "")
        session["fuel"] = fuel
        await _dispo_show_motors(query, chat_id, session, brand, model, fuel)
        return

    if data.startswith("dispo_motor:"):
        idx = int(data.split(":", 1)[1])
        motors = session.get("motors", [])
        if idx >= len(motors):
            await query.edit_message_text("Motorisation non trouvee.")
            return
        m = motors[idx]
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _dispo_select_motorisation(query, chat_id, session, brand, model,
                                         m["fuel"], m["displacement"], m["power_hp"])
        return

    if data.startswith("dispo_part_cat:"):
        cat_idx = int(data.split(":", 1)[1])
        await _dispo_show_parts_in_category(query, chat_id, cat_idx)
        return

    if data == "dispoback_part_cats":
        await _dispo_show_parts(query, chat_id)
        return

    if data.startswith("dispo_part:"):
        idx = int(data.split(":", 1)[1])
        parts = session.get("parts", [])
        if idx < len(parts):
            await _dispo_do_search(query, chat_id, parts[idx])
        return

    if data == "dispo_another":
        await _dispo_show_parts(query, chat_id)
        return


# --- /stats command ---

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — Show database statistics."""
    from src.db.repository import get_stats
    stats = await get_stats()
    await update.message.reply_text(
        "\U0001F4CA *Statistiques*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001F697 Vehicules: *{stats['vehicles']}*\n"
        f"\U0001F527 References: *{stats['references']}*\n"
        f"\U0001F522 Patterns VIN: *{stats['vin_patterns']}*\n"
        f"\U0001F4C8 Requetes aujourd'hui: *{stats['requests_today']}*",
        parse_mode="MarkdownV2",
    )


# --- AI layer handlers ---

import re as _choices_re_mod

_CHOICES_RE = _choices_re_mod.compile(r'^CHOICES:\s*(\[.*\])\s*$', _choices_re_mod.MULTILINE)


def _parse_choices(text: str) -> tuple[str, list[str]]:
    """Extract CHOICES:[...] from LLM response. Returns (clean_text, choices)."""
    m = _CHOICES_RE.search(text)
    if not m:
        return text, []
    try:
        choices = json.loads(m.group(1))
    except (json.JSONDecodeError, TypeError):
        return text, []
    clean = text[:m.start()].rstrip() + text[m.end():]
    return clean.strip(), choices


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset -- Clear AI conversation history."""
    from src.telegram.ai_layer import reset_history
    reset_history(update.effective_chat.id)
    await update.message.reply_text("Historique de conversation reinitialise.")


async def handle_ai_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks from AI clarification choices."""
    query = update.callback_query
    await query.answer()
    choice = query.data.removeprefix("ai_choice:")
    chat_id = update.effective_chat.id

    # Send the choice as if the user typed it
    await _process_ai_message(chat_id, choice, query, bot=context.bot)


async def _process_ai_message(chat_id: int, text: str, reply_target, bot=None) -> None:
    """Send text through AI layer and reply with result + optional buttons."""
    from src.telegram.ai_layer import handle_message

    async def send_status(msg):
        if bot:
            await bot.send_message(chat_id, msg)

    try:
        response = await handle_message(chat_id, text, on_status=send_status)
    except Exception as e:
        log.error("AI layer error: %s", e)
        if hasattr(reply_target, 'edit_message_text'):
            await reply_target.edit_message_text(f"Erreur: {e}")
        else:
            await reply_target.message.reply_text(f"Erreur: {e}")
        return

    if not response:
        response = "Pas de reponse."

    clean_text, choices = _parse_choices(response)

    reply_markup = None
    if choices:
        keyboard = []
        row = []
        for c in choices:
            row.append(InlineKeyboardButton(c, callback_data=f"ai_choice:{c}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard)

    # Truncate if too long for Telegram (4096 chars)
    if len(clean_text) > 4000:
        clean_text = clean_text[:4000] + "\n\n[tronque]"

    if hasattr(reply_target, 'edit_message_text'):
        await reply_target.edit_message_text(clean_text, reply_markup=reply_markup)
    else:
        await reply_target.message.reply_text(clean_text, reply_markup=reply_markup)


# --- Free text handler ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text: route through AI conversational layer."""
    text = (update.message.text or "").strip()
    if not text:
        return

    chat_id = update.effective_chat.id

    # Skip AI layer if operator has an active dispo/ref/get flow in progress
    for sessions in (dispo_sessions, get_sessions, ref_sessions, vin_sessions):
        existing = sessions.get(chat_id)
        if existing and existing.get("state") not in (None, "parsing"):
            await update.message.reply_text(
                "Vous avez un flux en cours. Terminez-le ou tapez /reset pour reinitialiser."
            )
            return

    await _process_ai_message(chat_id, text, update, bot=context.bot)


# --- Bot builder ---

def build_operator_app() -> Application:
    """Build and return the operator bot Application."""
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("guide", cmd_guide))
    app.add_handler(CommandHandler("ajouter_ref", cmd_ajouter_ref))
    app.add_handler(CommandHandler("vin", cmd_vin))
    app.add_handler(CommandHandler("ref", cmd_get))
    app.add_handler(CommandHandler("get", cmd_get))  # legacy alias
    app.add_handler(CommandHandler("dispo", cmd_dispo))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(handle_ref_callback, pattern=r"^ref_"))
    app.add_handler(CallbackQueryHandler(handle_vin_callback, pattern=r"^vin_"))
    app.add_handler(CallbackQueryHandler(handle_get_callback, pattern=r"^(get_|getback_)"))
    app.add_handler(CallbackQueryHandler(handle_dispo_callback, pattern=r"^(dispo_|dispoback_)"))
    app.add_handler(CallbackQueryHandler(handle_ai_choice_callback, pattern=r"^ai_choice:"))

    async def _noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.callback_query.answer()

    app.add_handler(CallbackQueryHandler(_noop_cb, pattern=r"^noop$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
