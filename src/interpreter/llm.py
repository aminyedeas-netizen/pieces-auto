"""OpenRouter LLM calls for message interpretation and OCR."""

import json
import logging
import os

import httpx
from dotenv import load_dotenv

from src.db.models import PartRequest, VehicleInfo
from src.interpreter.prompts import OCR_PREFIX, SYSTEM_INTERPRET

load_dotenv()

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PRIMARY_MODEL = os.environ.get("OPENROUTER_PRIMARY_MODEL", "google/gemini-2.0-flash-exp")
FALLBACK_MODEL = os.environ.get("OPENROUTER_FALLBACK_MODEL", "anthropic/claude-haiku-4.5")


async def call_llm(
    messages: list[dict],
    model: str | None = None,
    image_base64: str | None = None,
) -> str:
    """Call OpenRouter. Uses primary model, falls back to fallback on error."""
    model = model or PRIMARY_MODEL
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    # If image provided, modify the last user message to include it
    if image_base64:
        last_msg = messages[-1]
        messages[-1] = {
            "role": last_msg["role"],
            "content": [
                {"type": "text", "text": last_msg["content"]},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ],
        }

    payload = {"model": model, "messages": messages}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if model == PRIMARY_MODEL:
                log.warning("Primary model failed (%s), trying fallback", e)
                payload["model"] = FALLBACK_MODEL
                resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            raise


def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json and ``` markers
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


# Common model -> brand hints. Used to rescue queries where the user types only
# a model name ("polo 6", "picanto 2018"). The LLM gets these as hints and we
# also apply them as a post-LLM fallback if the brand is missing.
MODEL_BRAND_HINTS: dict[str, str] = {
    "polo": "Volkswagen", "golf": "Volkswagen", "passat": "Volkswagen", "tiguan": "Volkswagen",
    "picanto": "Kia", "rio": "Kia", "sportage": "Kia", "ceed": "Kia", "cerato": "Kia",
    "i10": "Hyundai", "i20": "Hyundai", "i30": "Hyundai", "tucson": "Hyundai", "accent": "Hyundai", "elantra": "Hyundai",
    "clio": "Renault", "megane": "Renault", "captur": "Renault", "kangoo": "Renault", "symbol": "Renault", "twingo": "Renault",
    "logan": "Dacia", "sandero": "Dacia", "duster": "Dacia", "lodgy": "Dacia",
    "208": "Peugeot", "308": "Peugeot", "2008": "Peugeot", "3008": "Peugeot", "301": "Peugeot", "partner": "Peugeot",
    "c3": "Citroen", "c4": "Citroen", "c5": "Citroen", "berlingo": "Citroen",
    "yaris": "Toyota", "corolla": "Toyota", "hilux": "Toyota", "rav4": "Toyota",
    "fiesta": "Ford", "focus": "Ford", "fusion": "Ford", "kuga": "Ford",
    "500": "Fiat", "panda": "Fiat", "tipo": "Fiat", "doblo": "Fiat",
}


def _is_plausible_reference(ref: str | None) -> bool:
    """A real part reference has both a letter and a digit and is at least 5 chars.

    Filters out LLM artefacts like bare numbers ("6" from "polo 6") or
    single words ("amortisseur").
    """
    if not ref:
        return False
    s = ref.strip()
    if len(s) < 5:
        return False
    has_letter = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)
    return has_letter and has_digit


def _infer_brand_from_model(model: str | None) -> str | None:
    """Best-effort brand guess from a model token ('polo' -> 'Volkswagen')."""
    if not model:
        return None
    first = model.strip().split()[0].lower()
    return MODEL_BRAND_HINTS.get(first)


async def parse_vehicle_query(text: str, known_brands: list[str]) -> dict:
    """Parse free text into {brand, model, year, part, reference}.

    - Gives the LLM the list of known DB brands so it can match fuzzily.
    - Filters implausible references (bare digits, single words).
    - If brand is missing but model is a known hint ('polo' -> VW), fills it in.
    - Maps the returned brand to a known DB brand (case-insensitive).

    Returns a dict with keys brand, model, year, part, reference (any may be None).
    """
    brand_list = ", ".join(known_brands) if known_brands else ""
    prompt = (
        "Extract vehicle brand, model, year, part name, and part reference from this message.\n"
        f"Known brands in our database: {brand_list}.\n"
        "Brand matching rules:\n"
        "  - If the user writes a model name without a brand (e.g. 'polo', 'picanto', '208',\n"
        "    'clio', 'logan', 'yaris'), INFER the brand (Volkswagen, Kia, Peugeot, Renault,\n"
        "    Dacia, Toyota, ...) and return it in 'brand'.\n"
        "  - Always return one of the known brands when possible.\n"
        "Reference rules:\n"
        "  - A reference is a MANUFACTURER PART CODE (e.g. 'K015578XS', '1148200010',\n"
        "    'VKMA06108'). It mixes letters and digits and is usually 6+ characters.\n"
        "  - Bare numbers like '6', '2020', '110' are NEVER references — they are a\n"
        "    model generation, year, or power. Return null for reference in that case.\n"
        "Year is the production start year (4 digits like 2019), not a model generation.\n"
        "Return ONLY JSON: {\"brand\": \"...\", \"model\": \"...\", \"year\": ..., \"part\": \"...\", \"reference\": \"...\"}\n"
        "If any field is missing, set it to null. year should be an integer or null."
    )

    raw = await call_llm(
        [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        model="anthropic/claude-haiku-4.5",
    )
    data = _parse_json_response(raw)

    # Drop bogus references (bare numbers, single words, too short).
    if not _is_plausible_reference(data.get("reference")):
        data["reference"] = None

    # Fallback: user typed a model with no brand — infer from hint table.
    if not data.get("brand"):
        data["brand"] = _infer_brand_from_model(data.get("model"))

    # Normalize brand to the DB's exact casing.
    if data.get("brand") and known_brands:
        for b in known_brands:
            if b.lower() == data["brand"].lower():
                data["brand"] = b
                break

    return data


async def interpret_message(text: str, image_base64: str | None = None) -> PartRequest:
    """Interpret a customer message into a structured PartRequest."""
    system = SYSTEM_INTERPRET
    if image_base64:
        system = OCR_PREFIX + system

    user_content = text or "See attached image"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    raw = await call_llm(messages, image_base64=image_base64)
    data = _parse_json_response(raw)

    vehicle = None
    if data.get("vehicle"):
        v = data["vehicle"]
        if v.get("make"):
            vehicle = VehicleInfo(
                make=v["make"],
                model=v.get("model") or "Unknown",
                year=v.get("year"),
                engine=v.get("engine"),
                fuel=v.get("fuel"),
                vin=data.get("vin"),
            )

    # If VIN found, decode with local tables + DB
    if data.get("vin"):
        from src.vin.decoder import decode_vin
        vin_info = await decode_vin(data["vin"])
        if not vehicle:
            vehicle = vin_info
        elif vehicle.make == "Unknown" or not vehicle.model or vehicle.model == "Unknown":
            # Enrich from VIN decode
            if vin_info.make:
                vehicle.make = vin_info.make
            if vin_info.model:
                vehicle.model = vin_info.model
            if vin_info.year and not vehicle.year:
                vehicle.year = vin_info.year
            if vin_info.engine and not vehicle.engine:
                vehicle.engine = vin_info.engine
            if vin_info.fuel and not vehicle.fuel:
                vehicle.fuel = vin_info.fuel
            vehicle.confidence = vin_info.confidence

    return PartRequest(
        vehicle=vehicle,
        part_name=data.get("part_name"),
        part_name_raw=data.get("part_name_raw", text),
        direct_reference=data.get("direct_reference"),
    )
