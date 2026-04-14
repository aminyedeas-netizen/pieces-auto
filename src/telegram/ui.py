"""Telegram keyboard layout helpers for consistent, readable button UX.

Display contract
----------------
Every helper in this module is *display-only*: it transforms strings that come
from the database into something readable on a Telegram button. The original
DB values are never mutated, never overwritten, never re-stored.

How the round-trip works:

  DB row ─────► raw model/part/engine string
                   │
                   │  cached in the in-memory session (e.g. session["models"])
                   │  at its ORIGINAL DB form
                   ▼
              format_model_label(brand, raw)  ──► label shown on the button
                                                 (callback carries an INDEX
                                                  into the cached list, e.g.
                                                  callback_data="get_model:3")
                   ▼
            user taps button ──► handler reads the index, looks the
                                 ORIGINAL string back out of the session,
                                 and uses THAT in the next DB query.

Net effect: the DB never sees a formatted string. Add new formatters here and
keep the same convention — handlers must always resolve the user's tap back
to the unmodified DB value before querying.
"""

import re
import unicodedata

from telegram import InlineKeyboardButton


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_BODY_NOISE_RE = re.compile(
    r"\s*(?:/\s*)?3\s*/\s*5\s*portes?",
    flags=re.IGNORECASE,
)
_TRAILING_SLASH_RE = re.compile(r"\s+/\s+")
_MULTISPACE_RE = re.compile(r"\s{2,}")


def format_model_label(brand: str, model: str, max_len: int = 24) -> str:
    """Render a model name as a clean Telegram button label.

    - Strips redundant leading brand prefix (case/diacritics-insensitive).
    - Removes verbose body-style noise like "/ 3/5 portes".
    - Normalizes inconsistent casing (PA24 mixes "Citroën" / "CITROËN").
    - Uppercases short lowercase trailing chassis tokens ("Picanto ba" -> "BA").
    - Mid-truncates if still too long so chassis code in parens is preserved.
    """
    label = model.strip()
    brand_norm = _strip_diacritics(brand).lower()
    label_norm = _strip_diacritics(label).lower()
    if label_norm.startswith(brand_norm + " "):
        label = label.split(" ", 1)[1] if " " in label else label
    label = _BODY_NOISE_RE.sub("", label)
    label = _TRAILING_SLASH_RE.sub(" ", label)
    label = _MULTISPACE_RE.sub(" ", label).strip(" /-")
    parts = label.split()
    if parts and len(parts[-1]) <= 3 and parts[-1].islower() and parts[-1].isalpha():
        parts[-1] = parts[-1].upper()
        label = " ".join(parts)
    if len(label) > max_len:
        keep = max_len - 1
        head = label[: keep // 2]
        tail = label[-(keep - len(head)) :]
        label = f"{head}…{tail}"
    return label


def format_year_label(year_start: int | None, year_end: int | None) -> str:
    if year_start is None:
        return "?"
    if year_end is None or year_end == year_start:
        return str(year_start)
    return f"{year_start}-{year_end}"


def format_engine_label(vehicle, max_len: int = 28) -> str:
    """Compact engine description for a button: '1.6 90CV Diesel 9HX'.

    Pulls only the discriminating fields (displacement, power, fuel,
    engine_code) and strips empty bits. The full PA24 name stays in
    session["vehicle_name"] for downstream display.
    """
    bits: list[str] = []
    if getattr(vehicle, "displacement", None):
        bits.append(vehicle.displacement)
    if getattr(vehicle, "power_hp", None):
        bits.append(f"{vehicle.power_hp}CV")
    if getattr(vehicle, "fuel", None):
        bits.append(vehicle.fuel)
    if getattr(vehicle, "engine_code", None):
        bits.append(vehicle.engine_code)
    label = " ".join(bits) if bits else "Moteur"
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    return label


def grid_buttons(
    items: list[tuple[str, str]],
    cols: int = 3,
) -> list[list[InlineKeyboardButton]]:
    """Lay out (label, callback_data) tuples in a fixed-column grid."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, cb in items:
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


PART_CATEGORIES: list[tuple[str, list[str]]] = [
    (
        "Freinage",
        [
            "Plaquette de frein (avant)",
            "Plaquette de frein (arrière)",
            "Disque de frein (avant)",
            "Disque de frein (arrière)",
            "Étrier de frein",
            "Mâchoire de frein",
            "Kit de frein",
            "Câble de frein",
            "Liquide de frein",
            "Maître-cylindre de frein",
        ],
    ),
    (
        "Filtration",
        [
            "Filtre à huile",
            "Filtre à air",
            "Filtre à carburant",
            "Filtre d'habitacle",
        ],
    ),
    (
        "Distribution / Refroidissement",
        [
            "Kit de distribution",
            "Kit chaîne de distribution",
            "Tendeur de courroie de distribution",
            "Kit de courroie d'accessoire",
            "Pompe à eau",
            "Thermostat",
            "Radiateur",
            "Durite",
        ],
    ),
    (
        "Suspension / Direction",
        [
            "Amortisseur (avant)",
            "Amortisseur (arrière)",
            "Rotule de direction",
            "Rotule de suspension",
            "Biellette de barre stabilisatrice",
            "Roulement de roue (avant)",
            "Roulement de roue (arrière)",
            "Triangle de suspension",
            "Silent bloc",
            "Cardan",
            "Soufflet de cardan",
        ],
    ),
    (
        "Moteur / Électrique",
        [
            "Alternateur",
            "Démarreur",
            "Bougie",
            "Bougie de préchauffage",
            "Bobine d'allumage",
            "Kit d'embrayage",
            "Volant moteur",
            "Injecteur",
            "Turbocompresseur",
            "Sonde lambda",
            "Capteur",
            "EGR",
        ],
    ),
]


def _categorize(part: str) -> int:
    """Return index of the category a part belongs to, or len(PART_CATEGORIES) for 'Autres'."""
    for i, (_, names) in enumerate(PART_CATEGORIES):
        for pattern in names:
            if part.lower() == pattern.lower():
                return i
    # fallback: substring match on category keywords
    low = part.lower()
    keyword_map = {
        0: ["frein", "étrier", "mâchoire", "maître-cylindre"],
        1: ["filtre"],
        2: ["distribution", "courroie", "pompe", "thermostat", "radiateur", "durite"],
        3: [
            "amortisseur", "rotule", "biellette", "roulement", "triangle",
            "silent", "cardan", "soufflet", "direction", "suspension",
        ],
        4: [
            "alternateur", "démarreur", "bougie", "bobine", "embrayage",
            "volant moteur", "injecteur", "turbo", "sonde", "capteur", "egr",
        ],
    }
    for cat_idx, kws in keyword_map.items():
        if any(k in low for k in kws):
            return cat_idx
    return len(PART_CATEGORIES)


def _divider(title: str) -> list[InlineKeyboardButton]:
    """Non-clickable section header row."""
    return [InlineKeyboardButton(f"── {title} ──", callback_data="noop")]


def build_parts_keyboard(
    parts: list[str],
    callback_prefix: str,
    tail_rows: list[list[InlineKeyboardButton]] | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Lay out a parts list with category dividers and 2-col grid inside each section.

    Keeps the original index of each part so callbacks stay `{prefix}:{i}` where
    i is the position in the input list (handlers rely on this).
    """
    # group indices by category, preserving input order inside each group
    groups: dict[int, list[int]] = {}
    for i, p in enumerate(parts):
        groups.setdefault(_categorize(p), []).append(i)

    keyboard: list[list[InlineKeyboardButton]] = []
    category_order = list(range(len(PART_CATEGORIES))) + [len(PART_CATEGORIES)]
    for cat_idx in category_order:
        if cat_idx not in groups:
            continue
        title = PART_CATEGORIES[cat_idx][0] if cat_idx < len(PART_CATEGORIES) else "Autres"
        keyboard.append(_divider(title))
        indices = groups[cat_idx]
        # 2-col grid; short labels (<=22 chars) get paired
        row: list[InlineKeyboardButton] = []
        for i in indices:
            label = parts[i] if len(parts[i]) <= 38 else parts[i][:37] + "…"
            btn = InlineKeyboardButton(label, callback_data=f"{callback_prefix}:{i}")
            # if current part or its partner is long, flush row and use full width
            if len(label) > 28:
                if row:
                    keyboard.append(row)
                    row = []
                keyboard.append([btn])
                continue
            row.append(btn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    if tail_rows:
        keyboard.extend(tail_rows)
    return keyboard


def handle_noop_callback_data(data: str) -> bool:
    """True if a callback should be silently ignored (category headers)."""
    return data == "noop"
