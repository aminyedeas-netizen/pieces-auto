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


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_BODY_NOISE_RE = re.compile(
    r"\s*(?:/\s*)?3\s*/\s*5\s*portes?",
    flags=re.IGNORECASE,
)
_TRAILING_SLASH_RE = re.compile(r"\s+/\s+")
_MULTISPACE_RE = re.compile(r"\s{2,}")

# Verbose body-style words compressed to short forms. Applied as whole-word
# substitutions so "Sportback" becomes "Sportb." but "Sportbacker" (not a
# real token, but safe anyway) would not.
_BODY_ABBREVIATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bSportback\b", re.IGNORECASE), "Sportb."),
    (re.compile(r"\bCabriolet\b", re.IGNORECASE), "Cabr."),
    (re.compile(r"\bBerline\b", re.IGNORECASE), "Berl."),
    (re.compile(r"\bCoup[eé]\b", re.IGNORECASE), "Coup."),
    (re.compile(r"\bRoadster\b", re.IGNORECASE), "Road."),
    (re.compile(r"\bAllroad\b", re.IGNORECASE), "Allr."),
    (re.compile(r"\bCitycarver\b", re.IGNORECASE), "Citycrv."),
    (re.compile(r"\ballstreet\b", re.IGNORECASE), "allstr."),
]


def model_family(model: str) -> str:
    """Return the model's family root (first token), e.g. 'A3 Sportback (8VA)' -> 'A3'.

    Used to group many variants of the same family under one picker entry so
    users tap 'A3' once, then pick the body / chassis variant.
    """
    parts = model.strip().split()
    return parts[0] if parts else model


def format_model_label(brand: str, model: str, max_len: int = 30) -> str:
    """Render a model name as a clean Telegram button label.

    - Strips redundant leading brand prefix (case/diacritics-insensitive).
    - Removes verbose body-style noise like "/ 3/5 portes".
    - Abbreviates long body-style words (Sportback -> Sportb., etc.).
    - Normalizes inconsistent casing (PA24 mixes "Citroën" / "CITROËN").
    - Uppercases short lowercase trailing chassis tokens ("Picanto ba" -> "BA").
    - End-truncates cleanly if still too long.
    """
    label = model.strip()
    brand_norm = _strip_diacritics(brand).lower()
    label_norm = _strip_diacritics(label).lower()
    if label_norm.startswith(brand_norm + " "):
        label = label.split(" ", 1)[1] if " " in label else label
    label = _BODY_NOISE_RE.sub("", label)
    for pat, repl in _BODY_ABBREVIATIONS:
        label = pat.sub(repl, label)
    label = _TRAILING_SLASH_RE.sub(" ", label)
    label = _MULTISPACE_RE.sub(" ", label).strip(" /-")
    parts = label.split()
    if parts and len(parts[-1]) <= 3 and parts[-1].islower() and parts[-1].isalpha():
        parts[-1] = parts[-1].upper()
        label = " ".join(parts)
    if len(label) > max_len:
        label = label[: max_len - 1].rstrip() + "…"
    return label


def adaptive_grid(
    items: list[tuple[str, str]],
    threshold: int = 22,
) -> list[list[InlineKeyboardButton]]:
    """Lay out (label, callback_data) tuples in 1 or 2 columns depending on length.

    Two columns when every label is short (<= threshold chars), one column
    otherwise. Avoids the cramped look you get when mixing long labels into a
    fixed 2-column grid.
    """
    one_col = any(len(label) > threshold for label, _ in items)
    cols = 1 if one_col else 2
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


def group_families(models: list[str]) -> dict[str, list[int]]:
    """Map family root -> list of original indices into `models`, preserving order."""
    out: dict[str, list[int]] = {}
    for i, m in enumerate(models):
        out.setdefault(model_family(m), []).append(i)
    return out


def should_group_by_family(models: list[str]) -> bool:
    """True when the model list is big enough that a family picker helps."""
    if len(models) <= 6:
        return False
    groups = group_families(models)
    if len(groups) < 2:
        return False
    return any(len(v) >= 2 for v in groups.values())


def render_model_keyboard(
    brand: str,
    models: list[str],
    item_prefix: str,
    family_prefix: str,
    back_cb: str | None = None,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> tuple[list[list[InlineKeyboardButton]], bool]:
    """Render a model picker. Returns (keyboard, used_families).

    If many models share families, show one button per family; otherwise flat.
    Callbacks use `{family_prefix}:<family_name>` for family buttons and
    `{item_prefix}:<i>` for individual models, where i is the index into
    the original `models` list.
    """
    use_families = should_group_by_family(models)
    if use_families:
        groups = group_families(models)
        items: list[tuple[str, str]] = []
        for fam in sorted(groups.keys()):
            count = len(groups[fam])
            label = f"{fam} ({count})" if count > 1 else fam
            items.append((label, f"{family_prefix}:{fam}"))
        rows = adaptive_grid(items)
    else:
        items = [(format_model_label(brand, m), f"{item_prefix}:{i}") for i, m in enumerate(models)]
        rows = adaptive_grid(items)
    if back_cb:
        rows.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    if extra_rows:
        rows.extend(extra_rows)
    return rows, use_families


def render_variants_keyboard(
    brand: str,
    models: list[str],
    indices: list[int],
    item_prefix: str,
    back_cb: str,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Render variants of one family. Callbacks are `{item_prefix}:<i>` (original index)."""
    items = [(format_model_label(brand, models[i]), f"{item_prefix}:{i}") for i in indices]
    rows = adaptive_grid(items)
    rows.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    if extra_rows:
        rows.extend(extra_rows)
    return rows


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


def categorize_parts(parts: list[str]) -> list[tuple[int, str, list[int]]]:
    """Group parts into categories. Returns (cat_idx, cat_name, part_indices) for non-empty cats."""
    groups: dict[int, list[int]] = {}
    for i, p in enumerate(parts):
        groups.setdefault(_categorize(p), []).append(i)

    result = []
    category_order = list(range(len(PART_CATEGORIES))) + [len(PART_CATEGORIES)]
    for cat_idx in category_order:
        if cat_idx not in groups:
            continue
        title = PART_CATEGORIES[cat_idx][0] if cat_idx < len(PART_CATEGORIES) else "Autres"
        result.append((cat_idx, title, groups[cat_idx]))
    return result


def build_category_keyboard(
    parts: list[str],
    cat_prefix: str,
    back_cb: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Show category buttons with part count, e.g. 'Freinage (4)'."""
    cats = categorize_parts(parts)
    if len(cats) <= 1:
        # Single category — skip straight to parts (caller should handle)
        return []
    keyboard = []
    for cat_idx, title, indices in cats:
        label = f"{title} ({len(indices)})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{cat_prefix}:{cat_idx}")])
    if back_cb:
        keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    return keyboard


def build_category_parts_keyboard(
    parts: list[str],
    cat_idx: int,
    part_prefix: str,
    back_cb: str,
) -> list[list[InlineKeyboardButton]]:
    """Show parts within a single category."""
    cats = categorize_parts(parts)
    indices = []
    for ci, _, idxs in cats:
        if ci == cat_idx:
            indices = idxs
            break
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in indices:
        label = parts[i] if len(parts[i]) <= 38 else parts[i][:37] + "..."
        btn = InlineKeyboardButton(label, callback_data=f"{part_prefix}:{i}")
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
    keyboard.append([InlineKeyboardButton("\u2B05 Retour", callback_data=back_cb)])
    return keyboard


def handle_noop_callback_data(data: str) -> bool:
    """True if a callback should be silently ignored (category headers)."""
    return data == "noop"
