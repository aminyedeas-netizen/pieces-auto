"""Load and query VIN lookup tables from data/vin_tables/."""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "vin_tables"

_wmi_codes: dict | None = None
_year_codes: dict | None = None
_constructor_tables: dict[str, dict] = {}


def load_wmi_codes() -> dict:
    global _wmi_codes
    if _wmi_codes is None:
        _wmi_codes = json.loads((DATA_DIR / "wmi_codes.json").read_text())
    return _wmi_codes


def load_year_codes() -> dict:
    global _year_codes
    if _year_codes is None:
        _year_codes = json.loads((DATA_DIR / "year_codes.json").read_text())
    return _year_codes


def load_constructor_table(make: str) -> dict | None:
    """Load constructor-specific table by make name (case-insensitive)."""
    key = make.lower()
    if key in _constructor_tables:
        return _constructor_tables[key]

    path = DATA_DIR / f"{key}.json"
    if not path.exists():
        return None

    table = json.loads(path.read_text())
    _constructor_tables[key] = table
    return table


def find_constructor_table_by_wmi(wmi: str) -> dict | None:
    """Find the constructor table that owns this WMI code."""
    for path in DATA_DIR.glob("*.json"):
        if path.name in ("wmi_codes.json", "year_codes.json"):
            continue
        table = json.loads(path.read_text())
        if wmi in table.get("wmi_codes", []):
            key = path.stem
            _constructor_tables[key] = table
            return table
    return None
