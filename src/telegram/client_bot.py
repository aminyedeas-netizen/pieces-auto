"""Customer-facing Telegram bot. 3 identification paths + part search."""

import logging
import os
import re

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

BOT_TOKEN = os.environ.get("TELEGRAM_CLIENT_BOT_TOKEN", "")

VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")

# Session states
STATE_IDLE = "idle"
STATE_AWAITING_VIN = "awaiting_vin"
STATE_AWAITING_PHOTO = "awaiting_photo"
STATE_PICK_BRAND = "pick_brand"
STATE_PICK_MODEL = "pick_model"
STATE_PICK_FUEL = "pick_fuel"
STATE_PICK_MOTOR = "pick_motor"
STATE_VEHICLE_CONFIRMED = "vehicle_confirmed"
STATE_AWAITING_PART = "awaiting_part"
STATE_PICK_PART_CAT = "pick_part_cat"

# In-memory sessions: user_id -> {state, brand, model, fuel, vehicle_ids, vehicle_name, vin, ...}
sessions: dict[int, dict] = {}


def _get_session(user_id: int) -> dict:
    if user_id not in sessions:
        sessions[user_id] = {
            "state": STATE_IDLE,
            "vehicle_id": None,
            "vehicle_name": None,
            "vin": None,
            "retry_count": 0,
        }
    return sessions[user_id]


from src.telegram.ui import escape_md as _escape_md


# --- /start ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    sessions.pop(user_id, None)
    session = _get_session(user_id)
    session["state"] = STATE_PICK_BRAND

    from src.db.repository import get_distinct_brands
    brands = await get_distinct_brands()
    keyboard = []
    row = []
    for brand in brands:
        row.append(InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("\U0001F522 Entrer VIN", callback_data="id_vin")])
    await update.message.reply_text(
        "Bienvenue !\n\nSelectionnez la marque de votre voiture :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# --- Identification path callbacks ---

async def handle_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle identification path selection."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = _get_session(user_id)
    data = query.data

    if data == "id_photo":
        session["state"] = STATE_AWAITING_PHOTO
        if session.get("retry_count") is None:
            session["retry_count"] = 0
        await query.edit_message_text(
            "\U0001F4F7 Envoyez une photo de votre carte grise."
        )
        return

    if data == "id_vin":
        session["state"] = STATE_AWAITING_VIN
        await query.edit_message_text(
            "\U0001F522 Tapez votre numero VIN (17 caracteres).\n\n"
            "Il se trouve sur la carte grise ou sur le chassis du vehicule."
        )
        return

    if data == "id_model":
        session["state"] = STATE_PICK_BRAND
        await _show_brands(query, user_id)
        return


# --- Photo carte grise (Path 1) ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo: extract VIN from carte grise via LLM vision."""
    user_id = update.effective_user.id
    session = _get_session(user_id)

    if session["state"] != STATE_AWAITING_PHOTO:
        await update.message.reply_text("Envoyez /start pour commencer.")
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_bytes = await file.download_as_bytearray()

    import base64
    from src.interpreter.llm import call_llm, _parse_json_response
    from src.interpreter.prompts import OCR_PREFIX

    image_b64 = base64.b64encode(photo_bytes).decode()
    messages = [
        {"role": "system", "content": OCR_PREFIX + "\nReturn ONLY JSON: {\"vin\": \"...\"}. If unreadable, return {\"vin\": null}"},
        {"role": "user", "content": "Extract VIN from this carte grise photo."},
    ]
    try:
        raw = await call_llm(messages, image_base64=image_b64)
        data = _parse_json_response(raw)
        vin_str = data.get("vin")
    except Exception as e:
        log.error("Photo OCR failed: %s", e)
        vin_str = None

    if vin_str and VIN_PATTERN.search(vin_str.upper()):
        await _process_vin(update, user_id, vin_str.upper())
    else:
        session["retry_count"] += 1
        if session["retry_count"] >= 2:
            # Force to Path 3
            session["state"] = STATE_PICK_BRAND
            keyboard = [
                [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
            ]
            await update.message.reply_text(
                "\u26A0\uFE0F Photo non lisible apres 2 tentatives.\n"
                "Selectionnez votre vehicule manuellement.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            keyboard = [
                [InlineKeyboardButton("\U0001F4F7 Reprendre photo", callback_data="id_photo")],
                [InlineKeyboardButton("\U0001F522 Entrer VIN", callback_data="id_vin")],
                [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
            ]
            await update.message.reply_text(
                "\u26A0\uFE0F Photo non lisible. Reessayez ou choisissez une autre methode.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )


# --- VIN entry (Path 2) ---

async def _handle_vin_text(update: Update, user_id: int, text: str) -> None:
    """Handle text when awaiting VIN input."""
    session = _get_session(user_id)
    vin_match = VIN_PATTERN.search(text.upper())

    if not vin_match:
        session["retry_count"] += 1
        if session["retry_count"] >= 2:
            session["state"] = STATE_PICK_BRAND
            keyboard = [
                [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
            ]
            await update.message.reply_text(
                "\u26A0\uFE0F VIN invalide apres 2 tentatives.\n"
                "Selectionnez votre vehicule manuellement.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            keyboard = [
                [InlineKeyboardButton("\U0001F504 Reessayer", callback_data="id_vin")],
                [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
            ]
            await update.message.reply_text(
                "\u26A0\uFE0F Le VIN saisi semble incorrect\\.\n"
                "Verifiez qu'il contient 17 caracteres\n"
                "\\(lettres et chiffres, sans I, O ou Q\\)\\.\n\n"
                "Reessayez ou choisissez une autre methode\\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        return

    await _process_vin(update, user_id, vin_match.group(0))


async def _process_vin(update: Update, user_id: int, vin: str) -> None:
    """Decode VIN and show result with confirmation."""
    session = _get_session(user_id)
    from src.vin.decoder import decode_vin

    result = await decode_vin(vin)
    session["vin"] = vin

    # Format explanation
    explanation = "\n".join(f"  \\> {_escape_md(line)}" for line in result.explanation)

    if result.vehicle_id and result.confidence.value == "high":
        # Auto-identified
        session["vehicle_id"] = result.vehicle_id
        session["vehicle_name"] = result.pa24_full_name or f"{result.make} {result.model}"
        session["state"] = STATE_VEHICLE_CONFIRMED

        vehicle_display = _escape_md(session["vehicle_name"])
        keyboard = [
            [
                InlineKeyboardButton("\u2705 Oui", callback_data="vin_yes"),
                InlineKeyboardButton("\u274C Non", callback_data="id_model"),
            ]
        ]
        await update.message.reply_text(
            f"\U0001F50D *Decodage VIN*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"VIN : `{_escape_md(vin)}`\n"
            f"{explanation}\n\n"
            f"\U0001F697 Vehicule : *{vehicle_display}*\n\n"
            f"C'est correct ?",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif result.make:
        # Brand known, need model selection
        session["state"] = STATE_PICK_BRAND
        await update.message.reply_text(
            f"\U0001F50D *Decodage VIN*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"VIN : `{_escape_md(vin)}`\n"
            f"{explanation}\n\n"
            f"Veuillez selectionner votre motorisation\\.",
            parse_mode="MarkdownV2",
        )
        await _show_models_for_brand(update, user_id, result.make)
    else:
        # Unknown
        session["state"] = STATE_PICK_BRAND
        await update.message.reply_text(
            f"\U0001F50D *Decodage VIN*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"VIN : `{_escape_md(vin)}`\n"
            f"{explanation}\n\n"
            f"Selectionnez votre vehicule\\.",
            parse_mode="MarkdownV2",
        )
        await _send_brand_buttons(update, user_id)


# --- Model selection (Path 3) ---

async def _show_brands(query_or_update, user_id: int) -> None:
    """Show brand selection buttons."""
    from src.db.repository import get_distinct_brands
    brands = await get_distinct_brands()

    if not brands:
        text = "Aucun vehicule en base pour le moment."
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(text)
        else:
            await query_or_update.message.reply_text(text)
        return

    keyboard = []
    row = []
    for brand in brands:
        row.append(InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    text = "\U0001F3E2 Selectionnez la marque :"
    if hasattr(query_or_update, "edit_message_text"):
        await query_or_update.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query_or_update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _send_brand_buttons(update: Update, user_id: int) -> None:
    """Send brand buttons as a new message."""
    from src.db.repository import get_distinct_brands
    brands = await get_distinct_brands()
    if not brands:
        await update.message.reply_text("Aucun vehicule en base pour le moment.")
        return
    keyboard = []
    row = []
    for brand in brands:
        row.append(InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await update.message.reply_text(
        "\U0001F3E2 Selectionnez la marque :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_models_for_brand(update: Update, user_id: int, brand: str) -> None:
    """Show model buttons for a brand."""
    session = _get_session(user_id)
    session["brand"] = brand
    from src.db.repository import get_distinct_models
    models = await get_distinct_models(brand)
    if not models:
        await update.message.reply_text(f"Aucun modele {brand} en base.")
        return
    session["models"] = models
    session.pop("family", None)
    from src.telegram.ui import render_model_keyboard
    extra = [[InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")]]
    keyboard, used_families = render_model_keyboard(
        brand, models, "model", "family", back_cb="back_brands", extra_rows=extra,
    )
    session["use_families"] = used_families
    await update.message.reply_text(
        f"\U0001F697 Selectionnez le modele {brand} :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def _format_motor_button(displacement: str, fuel: str, power_hp: int) -> str:
    """Format motorisation button: '1.0 essence 67CV'."""
    fuel_display = fuel.lower() if fuel else ""
    return f"{displacement} {fuel_display} {power_hp}CV"


async def _show_fuel_or_motors(query, session: dict, brand: str, model: str) -> None:
    """After model selected: show fuel step if multiple fuels, else skip to motors."""
    from src.db.repository import get_fuels_for_model
    fuels = await get_fuels_for_model(brand, model)
    if len(fuels) > 1:
        session["state"] = STATE_PICK_FUEL
        keyboard = []
        row = []
        for f in fuels:
            row.append(InlineKeyboardButton(f, callback_data=f"fuel:{f}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="back_models")])
        await query.edit_message_text(
            f"Votre {model} est :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        fuel = fuels[0] if fuels else None
        session["fuel"] = fuel
        await _show_motors(query, session, brand, model, fuel)


async def _show_motors(query, session: dict, brand: str, model: str, fuel: str | None) -> None:
    """Show motorisation buttons grouped by displacement+fuel+power."""
    from src.db.repository import get_motorisations
    motors = await get_motorisations(brand, model, fuel)
    if not motors:
        await query.edit_message_text(f"Aucune motorisation pour {brand} {model}.")
        return
    if len(motors) == 1:
        m = motors[0]
        await _select_motorisation(query, session, brand, model,
                                   m["fuel"], m["displacement"], m["power_hp"])
        return
    session["state"] = STATE_PICK_MOTOR
    session["motors"] = motors
    keyboard = []
    for i, m in enumerate(motors):
        label = _format_motor_button(m["displacement"], m["fuel"], m["power_hp"])
        keyboard.append([InlineKeyboardButton(label, callback_data=f"motor:{i}")])
    back_cb = "back_fuels" if session.get("fuel") and len(await _get_fuels(brand, model)) > 1 else "back_models"
    keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    await query.edit_message_text(
        f"Quelle motorisation {brand} {model} ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _get_fuels(brand: str, model: str) -> list[str]:
    from src.db.repository import get_fuels_for_model
    return await get_fuels_for_model(brand, model)


async def _select_motorisation(
    query, session: dict, brand: str, model: str,
    fuel: str, displacement: str, power_hp: int,
) -> None:
    """Resolve motorisation to vehicle IDs and proceed to parts."""
    from src.db.repository import get_vehicle_ids_for_motorisation
    vehicle_ids = await get_vehicle_ids_for_motorisation(brand, model, fuel, displacement, power_hp)
    if not vehicle_ids:
        await query.edit_message_text("Aucun vehicule trouve.")
        return
    session["vehicle_ids"] = vehicle_ids
    session["vehicle_id"] = vehicle_ids[0]
    session["fuel"] = fuel
    session["displacement"] = displacement
    session["power_hp"] = power_hp
    fuel_display = fuel.lower() if fuel else ""
    session["vehicle_name"] = f"{brand} {model} {displacement} {fuel_display} {power_hp}CV"
    session["state"] = STATE_AWAITING_PART

    if session.get("vin") and len(vehicle_ids) == 1:
        await _auto_store_vin_pattern(session["vin"], vehicle_ids[0], session["vehicle_name"])

    pending_part = session.pop("pending_part", None)
    if pending_part:
        await _resolve_part(query, session, pending_part)
        return

    await _show_vehicle_confirmed(query, session)


async def handle_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle brand/model/fuel/motor selection callbacks."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = _get_session(user_id)
    data = query.data

    # Back to brands
    if data == "back_brands":
        from src.db.repository import get_distinct_brands
        brands = await get_distinct_brands()
        keyboard = []
        row = []
        for brand in brands:
            row.append(InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")])
        await query.edit_message_text(
            "Selectionnez la marque de votre voiture :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Back to models
    if data == "back_models":
        brand = session.get("brand", "")
        from src.db.repository import get_distinct_models
        models = await get_distinct_models(brand)
        session["models"] = models
        session.pop("family", None)
        from src.telegram.ui import render_model_keyboard
        keyboard, used_families = render_model_keyboard(
            brand, models, "model", "family", back_cb="back_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"Quel modele {brand} ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Family selected
    if data.startswith("family:"):
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
            brand, models, indices, "model", back_cb="back_models",
        )
        await query.edit_message_text(
            f"{brand} {family} — variante :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Back to fuels
    if data == "back_fuels":
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _show_fuel_or_motors(query, session, brand, model)
        return

    # Back to motors
    if data == "back_motors":
        brand = session.get("brand", "")
        model = session.get("model", "")
        fuel = session.get("fuel")
        await _show_motors(query, session, brand, model, fuel)
        return

    # Back to part categories
    if data == "back_part_cats":
        await _show_parts_for_vehicle(query, session)
        return

    # Part category selected
    if data.startswith("part_cat:"):
        cat_idx = int(data.split(":", 1)[1])
        await _show_parts_in_category(query, session, cat_idx)
        return

    # VIN confirmed
    if data == "vin_yes":
        session["state"] = STATE_AWAITING_PART
        await _show_vehicle_confirmed(query, session)
        return

    # Brand selected
    if data.startswith("brand:"):
        brand = data.split(":", 1)[1]
        session["state"] = STATE_PICK_MODEL
        session["brand"] = brand
        from src.db.repository import get_distinct_models
        models = await get_distinct_models(brand)
        if not models:
            await query.edit_message_text(f"Aucun modele {brand} en base.")
            return
        session["models"] = models
        session.pop("family", None)
        from src.telegram.ui import render_model_keyboard
        keyboard, used_families = render_model_keyboard(
            brand, models, "model", "family", back_cb="back_brands",
        )
        session["use_families"] = used_families
        await query.edit_message_text(
            f"Quel modele {brand} ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Model selected — check fuel then motors
    if data.startswith("model:"):
        idx = int(data.split(":", 1)[1])
        brand = session.get("brand", "")
        models = session.get("models", [])
        model = models[idx] if idx < len(models) else ""
        session["model"] = model
        await _show_fuel_or_motors(query, session, brand, model)
        return

    # Fuel selected
    if data.startswith("fuel:"):
        fuel = data.split(":", 1)[1]
        session["fuel"] = fuel
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _show_motors(query, session, brand, model, fuel)
        return

    # Motorisation selected
    if data.startswith("motor:"):
        idx = int(data.split(":", 1)[1])
        motors = session.get("motors", [])
        if idx >= len(motors):
            await query.edit_message_text("Motorisation introuvable.")
            return
        m = motors[idx]
        brand = session.get("brand", "")
        model = session.get("model", "")
        await _select_motorisation(query, session, brand, model,
                                   m["fuel"], m["displacement"], m["power_hp"])
        return


async def _show_vehicle_confirmed(query, session: dict) -> None:
    """Show vehicle confirmed, then show available parts from DB."""
    await _show_parts_for_vehicle(query, session)


async def _show_parts_for_vehicle(query, session: dict) -> None:
    """Show part categories (or parts directly if single category)."""
    vehicle_ids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    if len(vehicle_ids) > 1:
        from src.db.repository import get_parts_for_vehicles
        parts = await get_parts_for_vehicles(vehicle_ids)
    else:
        from src.db.repository import get_parts_for_vehicle
        parts = await get_parts_for_vehicle(vehicle_ids[0]) if vehicle_ids else []
    session["parts"] = parts

    if not parts:
        await query.edit_message_text("\u26A0\uFE0F Aucune piece disponible pour ce vehicule.")
        return

    name = session.get("vehicle_name", "?")
    from src.telegram.ui import build_category_keyboard, categorize_parts
    cat_kb = build_category_keyboard(parts, "part_cat", back_cb="back_motors")
    if cat_kb:
        session["state"] = STATE_PICK_PART_CAT
        await query.edit_message_text(
            f"\U0001F697 *{_escape_md(name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F527 Selectionnez la categorie :",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(cat_kb),
        )
    else:
        # Single category — show parts directly
        await _show_parts_in_category(query, session, categorize_parts(parts)[0][0])


async def _show_parts_in_category(query, session: dict, cat_idx: int) -> None:
    """Show parts within a single category."""
    parts = session.get("parts", [])
    name = session.get("vehicle_name", "?")
    from src.telegram.ui import build_category_parts_keyboard, categorize_parts, PART_CATEGORIES
    cats = categorize_parts(parts)
    # Find category name
    cat_name = "Autres"
    for ci, cn, _ in cats:
        if ci == cat_idx:
            cat_name = cn
            break
    back_cb = "back_part_cats" if len(cats) > 1 else "back_motors"
    keyboard = build_category_parts_keyboard(parts, cat_idx, "part", back_cb)
    session["state"] = STATE_AWAITING_PART
    await query.edit_message_text(
        f"\U0001F697 *{_escape_md(name)}*\n"
        f"\U0001F527 *{_escape_md(cat_name)}* :",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _match_part_to_db(vehicle_id: int | list[int], part_text: str) -> list[str]:
    """Match user's part text to actual DB part names. Fuzzy first, then LLM.

    vehicle_id can be a single int or a list of ints.
    Returns list of matched part names. If the LLM understood the intent but
    the part isn't available, returns a special ["__not_available__:<interpreted>"] marker.
    """
    from src.db.repository import (
        search_parts_fuzzy, search_parts_fuzzy_multi,
        get_parts_for_vehicle, get_parts_for_vehicles,
    )

    # Step 1: fuzzy SQL match
    if isinstance(vehicle_id, list) and len(vehicle_id) > 1:
        matches = await search_parts_fuzzy_multi(vehicle_id, part_text)
    else:
        vid = vehicle_id[0] if isinstance(vehicle_id, list) else vehicle_id
        matches = await search_parts_fuzzy(vid, part_text)
    if matches:
        return matches

    # Step 2: LLM interpretation against available parts
    if isinstance(vehicle_id, list) and len(vehicle_id) > 1:
        all_parts = await get_parts_for_vehicles(vehicle_id)
    else:
        vid = vehicle_id[0] if isinstance(vehicle_id, list) else vehicle_id
        all_parts = await get_parts_for_vehicle(vid)
    if not all_parts:
        return []

    from src.interpreter.llm import call_llm, _parse_json_response
    parts_list = "\n".join(f"- {p}" for p in all_parts)
    prompt = (
        "The user is looking for an auto part. Match their request to the available parts list.\n"
        "The user may misspell, use slang, franco-arabic, or abbreviations.\n"
        "Return ONLY JSON (no extra text): {\"interpreted\": \"what user meant in proper French\", \"matched\": [\"exact part name from list\", ...]}\n"
        "Rules:\n"
        "- 'interpreted': always fill this with the correct French part name the user meant\n"
        "- 'matched': only names that EXACTLY appear in the available list AND are the SAME type of part.\n"
        "- CRITICAL: only match parts that are genuinely the same part the user asked for.\n"
        "  'Joint de culasse' does NOT match 'Filtre a huile'. 'Amortisseur' matches 'Amortisseur avant'.\n"
        "  Do NOT return unrelated parts. If the part is not in the list, return matched=[].\n"
        "- If ambiguous (e.g. 'frein' matches avant and arriere), return all matches.\n\n"
        f"Available parts:\n{parts_list}\n"
    )
    try:
        raw = await call_llm(
            [{"role": "system", "content": prompt}, {"role": "user", "content": part_text}],
            model="anthropic/claude-haiku-4.5",
        )
        data = _parse_json_response(raw)
        llm_matches = data.get("matched", [])
        interpreted = data.get("interpreted", part_text)
        # Validate: only keep parts that actually exist in the list
        valid = [p for p in llm_matches if p in all_parts]
        if valid:
            return valid
        # LLM understood intent but part not in DB
        if interpreted and interpreted != part_text:
            return [f"__not_available__:{interpreted}"]
        return []
    except Exception as e:
        log.warning("LLM part matching failed: %s", e)
        return []


async def _resolve_part(query, session: dict, part_text: str) -> None:
    """Resolve a part name: fuzzy match, LLM match, clarify if ambiguous, then confirm."""
    vids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    matched = await _match_part_to_db(vids if len(vids) > 1 else vids[0], part_text)

    # Handle __not_available__ marker
    if len(matched) == 1 and matched[0].startswith("__not_available__:"):
        interpreted = matched[0].split(":", 1)[1]
        matched = []
        part_text = interpreted

    if len(matched) == 1:
        session["confirmed_part"] = matched[0]
        await _show_search_confirmation(query, session)
        return

    if len(matched) > 1:
        session["parts"] = matched
        keyboard = []
        for i, part in enumerate(matched):
            keyboard.append([InlineKeyboardButton(part, callback_data=f"part:{i}")])
        keyboard.append([InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")])
        await query.edit_message_text(
            "\u2753 Precisez la piece :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Nothing matched — notify operator and show available parts
    vehicle_name = session.get("vehicle_name", "?")
    await notify_operator(
        f"\U0001F527 PIECE NON TROUVEE\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Vehicule: {vehicle_name}\n"
        f"Piece demandee: {part_text}\n"
        f"-> Ajoutez les references si disponible"
    )
    from src.db.repository import get_parts_for_vehicle
    all_parts = await get_parts_for_vehicle(session["vehicle_id"])
    session["parts"] = all_parts
    keyboard = []
    for i, part in enumerate(all_parts):
        keyboard.append([InlineKeyboardButton(part, callback_data=f"part:{i}")])
    keyboard.append([InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")])
    await query.edit_message_text(
        f"\u26A0\uFE0F '{part_text}' n'est pas encore disponible pour ce vehicule.\n"
        "Nous recherchons cette piece pour vous.\n\n"
        "\U0001F527 Autres pieces disponibles :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_search_confirmation(query, session: dict) -> None:
    """Show query summary and ask for confirmation before searching."""
    vehicle_name = session.get("vehicle_name", "?")
    part_name = session.get("confirmed_part", "?")
    keyboard = [
        [
            InlineKeyboardButton("\u2705 Lancer la recherche", callback_data="confirm_search"),
            InlineKeyboardButton("\U0001F527 Changer piece", callback_data="another_part"),
        ],
        [InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")],
    ]
    await query.edit_message_text(
        f"\U0001F697 *{_escape_md(vehicle_name)}*\n"
        f"\U0001F527 *{_escape_md(part_name)}*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Lancer la recherche ?",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def _result_keyboard() -> InlineKeyboardMarkup:
    """Standard keyboard after search results."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F527 Autre piece", callback_data="another_part"),
            InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search"),
        ],
    ])


async def handle_part_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle part selection, confirmation, and navigation."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = _get_session(user_id)
    data = query.data

    # Direct reference search confirmed
    if data == "ref_search_yes":
        reference = session.get("pending_reference")
        if not reference:
            await query.edit_message_text("Pas de reference en attente.")
            return
        await query.edit_message_text(
            f"\U0001F50D Recherche en cours...\n\n"
            f"Reference : {reference}"
        )
        from src.chain import search_reference
        result_text = await search_reference(reference)
        try:
            await query.edit_message_text(
                result_text, parse_mode="MarkdownV2", reply_markup=_result_keyboard(),
            )
        except Exception:
            await query.edit_message_text(
                result_text.replace("\\", ""), reply_markup=_result_keyboard(),
            )
        session.pop("pending_reference", None)
        return

    # Direct reference search declined
    if data == "ref_search_no":
        session.pop("pending_reference", None)
        keyboard = [
            [InlineKeyboardButton("\U0001F4F7 Photo carte grise", callback_data="id_photo")],
            [InlineKeyboardButton("\U0001F522 Entrer VIN", callback_data="id_vin")],
            [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
        ]
        await query.edit_message_text(
            "\U0001F697 Comment identifier votre vehicule ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Part selected by index → go to confirmation
    if data.startswith("part:"):
        idx = int(data.split(":", 1)[1])
        parts = session.get("parts", [])
        if idx < len(parts):
            session["confirmed_part"] = parts[idx]
            await _show_search_confirmation(query, session)
        else:
            await query.edit_message_text("Piece non trouvee.")
        return

    # User confirmed search
    if data == "confirm_search":
        part_name = session.get("confirmed_part")
        if not part_name:
            await _show_parts_for_vehicle(query, session)
            return
        await _search_part(query, user_id, part_name)
        return

    # Another part (same vehicle)
    if data == "another_part":
        session.pop("confirmed_part", None)
        await _show_parts_for_vehicle(query, session)
        return

    # New search (reset vehicle)
    if data == "new_search":
        sessions.pop(user_id, None)
        session = _get_session(user_id)
        keyboard = [
            [InlineKeyboardButton("\U0001F4F7 Photo carte grise", callback_data="id_photo")],
            [InlineKeyboardButton("\U0001F522 Entrer VIN", callback_data="id_vin")],
            [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
        ]
        await query.edit_message_text(
            "\U0001F504 Nouvelle recherche\n\n"
            "\U0001F697 Comment identifier votre vehicule ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Back to parts
    if data == "part_back":
        await _show_parts_for_vehicle(query, session)
        return


async def _search_part(query, user_id: int, part_name: str) -> None:
    """Search for a part via the full chain."""
    session = _get_session(user_id)
    vehicle_ids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    vehicle_name = session.get("vehicle_name", "?")

    await query.edit_message_text(
        f"\U0001F50D Recherche en cours...\n\n"
        f"\U0001F697 {vehicle_name}\n"
        f"\U0001F527 {part_name}"
    )

    from src.chain import search_part
    from src.db.repository import log_request

    search_id = vehicle_ids if len(vehicle_ids) > 1 else vehicle_ids[0]
    result_text = await search_part(search_id, vehicle_name, part_name)

    try:
        await query.edit_message_text(
            result_text,
            parse_mode="MarkdownV2",
            reply_markup=_result_keyboard(),
        )
    except Exception:
        await query.edit_message_text(
            result_text.replace("\\", ""),
            reply_markup=_result_keyboard(),
        )

    await log_request(user_id, vehicle_ids[0] if vehicle_ids else None, part_name, session.get("vin"), "high")


def _vehicle_short_label(vehicle) -> str:
    """Short label for engine selection: displacement + power + fuel + engine code."""
    parts = []
    if vehicle.displacement:
        parts.append(vehicle.displacement)
    if vehicle.power_hp:
        parts.append(f"{vehicle.power_hp}CV")
    if vehicle.fuel:
        parts.append(vehicle.fuel)
    if vehicle.engine_code:
        parts.append(vehicle.engine_code)
    return " ".join(parts) if parts else vehicle.pa24_full_name[:40]


async def _auto_store_vin_pattern(vin: str, vehicle_id: int, vehicle_name: str) -> None:
    """Auto-store VIN pattern and notify operator."""
    vin_pattern = vin[:13]
    try:
        from src.db.repository import add_vin_pattern
        await add_vin_pattern(vin_pattern, vehicle_id)
        log.info("Auto-stored VIN pattern %s -> %s", vin_pattern, vehicle_name)
    except Exception as e:
        log.error("Failed to store VIN pattern: %s", e)

    # Notify operator
    try:
        from src.chain import notify_operator
        await notify_operator(
            "-----------------------------\n"
            "NOUVEAU VIN\n"
            "-----------------------------\n"
            f"VIN: {vin}\n"
            f"Identifie par le client comme:\n"
            f"{vehicle_name}\n\n"
            f"Pattern {vin_pattern} enregistre automatiquement.\n"
            "-> Verifiez si correct via /vin\n"
            "-----------------------------"
        )
    except Exception as e:
        log.warning("Could not notify operator: %s", e)


# --- Text message handler ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text messages from client."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    session = _get_session(user_id)

    if not text:
        return

    # Handle pending confirmations via text (ok, oui, yes, non, etc.)
    lower = text.lower().strip()
    affirmative = lower in ("ok", "oui", "yes", "y", "o", "d'accord", "go", "lance", "ok go")
    negative = lower in ("non", "no", "n", "annuler", "cancel")

    if session.get("pending_reference") and (affirmative or negative):
        if affirmative:
            reference = session["pending_reference"]
            await update.message.reply_text(
                f"\U0001F50D Recherche en cours...\n\nReference : {reference}"
            )
            from src.chain import search_reference
            result_text = await search_reference(reference)
            try:
                await update.message.reply_text(
                    result_text, parse_mode="MarkdownV2", reply_markup=_result_keyboard(),
                )
            except Exception:
                await update.message.reply_text(
                    result_text.replace("\\", ""), reply_markup=_result_keyboard(),
                )
            session.pop("pending_reference", None)
        else:
            session.pop("pending_reference", None)
            await update.message.reply_text("\u274C OK, annule.")
        return

    if session.get("confirmed_part") and affirmative:
        part_name = session["confirmed_part"]
        vehicle_id = session.get("vehicle_id")
        vehicle_name = session.get("vehicle_name", "?")
        await update.message.reply_text(
            f"\U0001F50D Recherche en cours...\n\n"
            f"\U0001F697 {vehicle_name}\n"
            f"\U0001F527 {part_name}"
        )
        from src.chain import search_part
        from src.db.repository import log_request
        result_text = await search_part(vehicle_id, vehicle_name, part_name)
        try:
            await update.message.reply_text(
                result_text, parse_mode="MarkdownV2", reply_markup=_result_keyboard(),
            )
        except Exception:
            await update.message.reply_text(
                result_text.replace("\\", ""), reply_markup=_result_keyboard(),
            )
        await log_request(user_id, vehicle_id, part_name, session.get("vin"), "high")
        session.pop("confirmed_part", None)
        return

    # Awaiting VIN input
    if session["state"] == STATE_AWAITING_VIN:
        await _handle_vin_text(update, user_id, text)
        return

    # Vehicle confirmed, awaiting part name — interpret with LLM
    if session["state"] == STATE_AWAITING_PART and session["vehicle_id"]:
        await _handle_part_text(update, user_id, text)
        return

    # Check if text contains a VIN
    vin_match = VIN_PATTERN.search(text.upper())
    if vin_match:
        await _process_vin(update, user_id, vin_match.group(0))
        return

    # Check if text looks like a bare reference code (e.g. "K015578XS", "7O0026")
    bare_ref = text.strip()
    if (re.match(r"^[A-Za-z0-9][-A-Za-z0-9./]{3,25}$", bare_ref)
            and not bare_ref.isdigit()
            and re.search(r"\d", bare_ref)):
        session["pending_reference"] = bare_ref.upper()
        keyboard = [
            [
                InlineKeyboardButton("\u2705 Oui, rechercher", callback_data="ref_search_yes"),
                InlineKeyboardButton("\u274C Non", callback_data="ref_search_no"),
            ]
        ]
        await update.message.reply_text(
            f"\U0001F50D {bare_ref.upper()}\n\n"
            "C'est une reference piece ?\n"
            "Je peux la rechercher directement chez CDG.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Try to parse brand+model+part from free text
    matched = await _try_parse_vehicle_and_part(update, user_id, text)
    if matched:
        return

    # No context — show start
    keyboard = [
        [InlineKeyboardButton("\U0001F4F7 Photo carte grise", callback_data="id_photo")],
        [InlineKeyboardButton("\U0001F522 Entrer VIN", callback_data="id_vin")],
        [InlineKeyboardButton("\U0001F697 Choisir modele", callback_data="id_model")],
    ]
    await update.message.reply_text(
        "\U0001F697 Comment identifier votre vehicule ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _try_parse_vehicle_and_part(update: Update, user_id: int, text: str) -> bool:
    """Try to extract brand+model+part from free text. Returns True if handled."""
    from src.interpreter.llm import (
        call_llm, _parse_json_response,
        _is_plausible_reference, _infer_brand_from_model,
    )
    from src.db.repository import get_distinct_brands, get_distinct_models, get_vehicles_for_model

    brands = await get_distinct_brands()
    brand_list = ", ".join(brands)
    prompt = (
        "Extract vehicle brand, model, year, part name, and part reference from this message.\n"
        f"Known car brands in DB: {brand_list}.\n"
        "The user may write in French, Arabic, or Tunisian franco-arabic.\n"
        "If the user writes a model name without brand (polo, picanto, 208, clio, logan,\n"
        "yaris, golf, sandero, ...), INFER the car brand (Volkswagen, Kia, Peugeot, ...).\n"
        "A reference is a MANUFACTURER PART CODE mixing letters and digits, usually 6+\n"
        "chars (e.g. 'K015578XS', '7O0026', 'ADG02109'). Bare numbers like '6', '2020',\n"
        "'110' are NEVER references — they are a model generation, year, or power.\n"
        "A ref_brand is the manufacturer of the part (Gates, Bosch, etc.) - NOT the car brand.\n"
        "year is the production start year (4 digits like 2019), not a model generation.\n"
        "Return ONLY JSON: {\"brand\": \"...\", \"model\": \"...\", \"year\": ..., \"part\": \"...\", \"ref_brand\": \"...\", \"reference\": \"...\"}\n"
        "If any field is missing, set it to null. year should be an integer or null.\n"
        "Examples:\n"
        "- 'Kia picanto filtre a huile' -> {\"brand\": \"KIA\", \"model\": \"Picanto\", \"year\": null, \"part\": \"Filtre a huile\", \"ref_brand\": null, \"reference\": null}\n"
        "- 'Peugeot 208 2019 courroie de distribution' -> {\"brand\": \"PEUGEOT\", \"model\": \"208\", \"year\": 2019, \"part\": \"Courroie de distribution\", \"ref_brand\": null, \"reference\": null}\n"
        "- 'polo filtre hwa' -> {\"brand\": \"VOLKSWAGEN\", \"model\": \"Polo\", \"year\": null, \"part\": \"Filtre a air\", \"ref_brand\": null, \"reference\": null}\n"
        "- 'amortisseur arriere polo 6' -> {\"brand\": \"VOLKSWAGEN\", \"model\": \"Polo\", \"year\": null, \"part\": \"Amortisseur (arriere)\", \"ref_brand\": null, \"reference\": null}\n"
    )
    try:
        raw = await call_llm(
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            model="anthropic/claude-haiku-4.5",
        )
        data = _parse_json_response(raw)
    except Exception:
        return False

    # Drop bogus references (bare numbers like '6' from 'polo 6').
    if not _is_plausible_reference(data.get("reference")):
        data["reference"] = None
    # Fallback: brand missing but model is a known hint -> infer.
    if not data.get("brand"):
        data["brand"] = _infer_brand_from_model(data.get("model"))

    brand = data.get("brand")
    model = data.get("model")
    year = data.get("year")
    part = data.get("part")
    reference = data.get("reference")

    # If reference found, offer direct CDG search
    if reference:
        session = _get_session(user_id)
        session["pending_reference"] = reference
        session["pending_ref_brand"] = data.get("ref_brand")
        session["pending_part"] = part
        ref_label = f"{data.get('ref_brand', '')} {reference}".strip()
        keyboard = [
            [
                InlineKeyboardButton("\u2705 Oui, rechercher", callback_data="ref_search_yes"),
                InlineKeyboardButton("\u274C Non", callback_data="ref_search_no"),
            ]
        ]
        await update.message.reply_text(
            f"\U0001F50D {ref_label}\n\n"
            "C'est une reference piece ?\n"
            "Je peux la rechercher directement chez CDG.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    if not brand:
        return False

    # Check brand exists in DB (case-insensitive) — `brands` already fetched above.
    matched_brand = None
    for b in brands:
        if b.upper() == brand.upper():
            matched_brand = b
            break
    if not matched_brand:
        return False

    session = _get_session(user_id)
    session["brand"] = matched_brand
    session["pending_part"] = part

    if model:
        # Check model exists
        models = await get_distinct_models(matched_brand)
        matched_model = None
        for m in models:
            if m.upper() == model.upper():
                matched_model = m
                break
        if matched_model:
            session["model"] = matched_model
            session["models"] = models
            # Go to fuel/motor selection — send as fake query via message reply
            from src.db.repository import get_fuels_for_model, get_motorisations, get_vehicle_ids_for_motorisation
            fuels = await get_fuels_for_model(matched_brand, matched_model)
            if not fuels:
                await update.message.reply_text(f"Aucune motorisation pour {matched_brand} {matched_model}.")
                return True
            if len(fuels) == 1:
                fuel = fuels[0]
                session["fuel"] = fuel
                motors = await get_motorisations(matched_brand, matched_model, fuel)
                if len(motors) == 1:
                    m = motors[0]
                    vids = await get_vehicle_ids_for_motorisation(
                        matched_brand, matched_model, m["fuel"], m["displacement"], m["power_hp"])
                    session["vehicle_ids"] = vids
                    session["vehicle_id"] = vids[0]
                    fuel_display = m["fuel"].lower() if m["fuel"] else ""
                    session["vehicle_name"] = f"{matched_brand} {matched_model} {m['displacement']} {fuel_display} {m['power_hp']}CV"
                    session["state"] = STATE_AWAITING_PART
                    if part:
                        await _resolve_part_msg(update, session, part)
                    else:
                        from src.telegram.ui import build_parts_keyboard
                        from src.db.repository import get_parts_for_vehicles
                        parts = await get_parts_for_vehicles(vids)
                        session["parts"] = parts
                        if parts:
                            keyboard = build_parts_keyboard(parts, "part")
                            await update.message.reply_text(
                                f"{session['vehicle_name']}\n\nQue recherchez-vous ?",
                                reply_markup=InlineKeyboardMarkup(keyboard),
                            )
                        else:
                            await update.message.reply_text("Aucune piece disponible.")
                    return True
                # Multiple motors — show buttons
                session["state"] = STATE_PICK_MOTOR
                session["motors"] = motors
                keyboard = []
                for i, m in enumerate(motors):
                    label = _format_motor_button(m["displacement"], m["fuel"], m["power_hp"])
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"motor:{i}")])
                keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="back_models")])
                await update.message.reply_text(
                    f"Quelle motorisation {matched_brand} {matched_model} ?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return True
            # Multiple fuels — show fuel step
            session["state"] = STATE_PICK_FUEL
            keyboard = []
            row = []
            for f in fuels:
                row.append(InlineKeyboardButton(f, callback_data=f"fuel:{f}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data="back_models")])
            await update.message.reply_text(
                f"Votre {matched_model} est :",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return True

    # Brand matched but model not found — show models
    session["state"] = STATE_PICK_MODEL
    await _show_models_for_brand(update, user_id, matched_brand)
    return True


async def _resolve_part_msg(update: Update, session: dict, part_text: str) -> None:
    """Resolve a part name via message reply (not query edit)."""
    vids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    matched = await _match_part_to_db(vids if len(vids) > 1 else vids[0], part_text)

    # Handle __not_available__ marker
    if len(matched) == 1 and matched[0].startswith("__not_available__:"):
        interpreted = matched[0].split(":", 1)[1]
        matched = []
        part_text = interpreted

    if len(matched) == 1:
        session["confirmed_part"] = matched[0]
        await _show_search_confirmation_msg(update, session)
        return

    if len(matched) > 1:
        session["parts"] = matched
        keyboard = []
        for i, part in enumerate(matched):
            keyboard.append([InlineKeyboardButton(part, callback_data=f"part:{i}")])
        keyboard.append([InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")])
        await update.message.reply_text(
            "\u2753 Precisez la piece :", reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Nothing matched — notify operator and show available parts
    vehicle_name = session.get("vehicle_name", "?")
    await notify_operator(
        f"\U0001F527 PIECE NON TROUVEE\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Vehicule: {vehicle_name}\n"
        f"Piece demandee: {part_text}\n"
        f"-> Ajoutez les references si disponible"
    )
    from src.db.repository import get_parts_for_vehicle
    all_parts = await get_parts_for_vehicle(session["vehicle_id"])
    session["parts"] = all_parts
    keyboard = []
    for i, part in enumerate(all_parts):
        keyboard.append([InlineKeyboardButton(part, callback_data=f"part:{i}")])
    keyboard.append([InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")])
    await update.message.reply_text(
        f"\u26A0\uFE0F '{part_text}' n'est pas encore disponible pour ce vehicule.\n"
        "Nous recherchons cette piece pour vous.\n\n"
        "\U0001F527 Autres pieces disponibles :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_search_confirmation_msg(update: Update, session: dict) -> None:
    """Show confirmation via message reply."""
    vehicle_name = session.get("vehicle_name", "?")
    part_name = session.get("confirmed_part", "?")
    keyboard = [
        [
            InlineKeyboardButton("\u2705 Lancer la recherche", callback_data="confirm_search"),
            InlineKeyboardButton("\U0001F527 Changer piece", callback_data="another_part"),
        ],
        [InlineKeyboardButton("\U0001F504 Nouvelle recherche", callback_data="new_search")],
    ]
    await update.message.reply_text(
        f"\U0001F697 *{_escape_md(vehicle_name)}*\n"
        f"\U0001F527 *{_escape_md(part_name)}*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Lancer la recherche ?",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_parts_for_vehicle_msg(update: Update, session: dict) -> None:
    """Show part categories via update.message (not query.edit)."""
    vehicle_ids = session.get("vehicle_ids") or ([session["vehicle_id"]] if session.get("vehicle_id") else [])
    if len(vehicle_ids) > 1:
        from src.db.repository import get_parts_for_vehicles
        parts = await get_parts_for_vehicles(vehicle_ids)
    else:
        from src.db.repository import get_parts_for_vehicle
        parts = await get_parts_for_vehicle(vehicle_ids[0]) if vehicle_ids else []
    session["parts"] = parts

    if not parts:
        await update.message.reply_text("\u26A0\uFE0F Aucune piece disponible pour ce vehicule.")
        return

    name = session.get("vehicle_name", "?")
    from src.telegram.ui import build_category_keyboard, categorize_parts
    cat_kb = build_category_keyboard(parts, "part_cat", back_cb="back_motors")
    if cat_kb:
        session["state"] = STATE_PICK_PART_CAT
        await update.message.reply_text(
            f"\U0001F697 *{_escape_md(name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F527 Selectionnez la categorie :",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(cat_kb),
        )
    else:
        # Single category — show parts directly via flat keyboard
        cats = categorize_parts(parts)
        cat_idx = cats[0][0]
        from src.telegram.ui import build_category_parts_keyboard
        keyboard = build_category_parts_keyboard(parts, cat_idx, "part", "back_motors")
        session["state"] = STATE_AWAITING_PART
        await update.message.reply_text(
            f"\U0001F697 *{_escape_md(name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001F527 Selectionnez la piece :",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def _handle_part_text(update: Update, user_id: int, text: str) -> None:
    """Interpret free text part name via LLM, then resolve."""
    session = _get_session(user_id)

    # Use LLM to normalize franco-arabic part names
    part_name = await _interpret_part_name(text)
    if not part_name:
        part_name = text

    await _resolve_part_msg(update, session, part_name)


async def _interpret_part_name(text: str) -> str | None:
    """Use LLM to normalize a part name from franco-arabic to French."""
    from src.interpreter.llm import call_llm, _parse_json_response

    prompt = (
        "The user typed an auto part name in French or Tunisian franco-arabic.\n"
        "Normalize to standard French part name.\n"
        "Common vocabulary:\n"
        "- filtre zit = Filtre a huile\n"
        "- filtre hwa = Filtre a air\n"
        "- plakette frin / plakat = Plaquettes de frein avant\n"
        "- joint koulass = Joint de culasse\n"
        "- kourwa distribision = Kit de distribution\n"
        "- amortisor = Amortisseur avant\n"
        "- bouji = Bougie d'allumage\n"
        "- pompe lo = Pompe a eau\n"
        "- disque frin = Disque de frein avant\n"
        "- rotil = Rotule de direction\n"
        "- roulmon = Roulement de roue avant\n"
        "- ambriaj = Kit embrayage\n"
        "- demareur = Demarreur\n"
        "- alternatir = Alternateur\n"
        'Return ONLY JSON: {"part_name": "..."}'
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text},
    ]
    try:
        raw = await call_llm(messages, model="anthropic/claude-haiku-4.5")
        data = _parse_json_response(raw)
        return data.get("part_name")
    except Exception as e:
        log.warning("Part name interpretation failed: %s", e)
        return None


# --- Operator notification helper ---

async def notify_operator(text: str) -> None:
    """Send a notification to the operator bot via chain."""
    from src.chain import notify_operator as _chain_notify
    await _chain_notify(text)


# --- Bot builder ---

def build_client_app() -> Application:
    """Build and return the client bot Application."""
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_id_callback, pattern=r"^id_"))
    app.add_handler(CallbackQueryHandler(handle_selection_callback, pattern=r"^(vin_yes|brand:|model:|family:|fuel:|motor:|part_cat:|back_)"))
    app.add_handler(CallbackQueryHandler(handle_part_callback, pattern=r"^(part:|part_back|another_part|confirm_search|new_search|ref_search_)"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
