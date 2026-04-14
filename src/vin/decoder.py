"""VIN decoder: hardcoded WMI/year tables, PSA engine code DB search, JSON fallback."""

from src.db.models import Confidence, VehicleInfo

# --- Hardcoded lookup tables ---

WMI_TABLE: dict[str, str] = {
    "VF3": "Peugeot", "VR3": "Peugeot",
    "VF7": "Citroen", "VR7": "Citroen",
    "VR1": "DS",
    "VF1": "Renault", "VF2": "Renault",
    "UU1": "Dacia", "VGA": "Dacia",
    "WVW": "Volkswagen", "WV2": "Volkswagen",
    "VSS": "Seat",
    "TMB": "Skoda",
    "KMH": "Hyundai", "MAL": "Hyundai",
    "KNA": "Kia", "KND": "Kia", "KNB": "Kia",
    "SB1": "Toyota", "JTD": "Toyota", "MR0": "Toyota",
    "WF0": "Ford",
    "ZFA": "Fiat", "ZFC": "Fiat",
    "TSM": "Suzuki", "JS2": "Suzuki",
    "JMB": "Mitsubishi", "JMY": "Mitsubishi",
    "SJN": "Nissan", "JN1": "Nissan",
    "JMZ": "Mazda",
    "MP1": "Isuzu",
    "LB3": "Geely", "L6T": "Geely",
    "LVT": "Chery", "LWD": "Chery",
    "LC0": "Haval", "LGX": "Haval",
    "LZW": "MG", "LSJ": "MG",
    "LA6": "Baic",
}

WMI_COUNTRY: dict[str, str] = {
    "VF3": "France", "VR3": "France", "VF7": "France", "VR7": "France",
    "VR1": "France", "VF1": "France", "VF2": "France",
    "UU1": "Roumanie", "VGA": "France",
    "WVW": "Allemagne", "WV2": "Allemagne",
    "VSS": "Espagne", "TMB": "Republique Tcheque",
    "KMH": "Coree du Sud", "MAL": "Coree du Sud",
    "KNA": "Coree du Sud", "KND": "Coree du Sud", "KNB": "Coree du Sud",
    "SB1": "Royaume-Uni", "JTD": "Japon", "MR0": "Japon",
    "WF0": "Allemagne",
    "ZFA": "Italie", "ZFC": "Italie",
    "TSM": "Japon", "JS2": "Japon",
    "JMB": "Japon", "JMY": "Japon",
    "SJN": "Japon", "JN1": "Japon",
    "JMZ": "Japon", "MP1": "Japon",
    "LB3": "Chine", "L6T": "Chine",
    "LVT": "Chine", "LWD": "Chine",
    "LC0": "Chine", "LGX": "Chine",
    "LZW": "Chine", "LSJ": "Chine",
    "LA6": "Chine",
}

PSA_BRANDS = {"Peugeot", "Citroen", "DS"}

YEAR_TABLE: dict[str, int] = {
    "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005,
    "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
    "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
    "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
    "S": 2025, "T": 2026,
}


def validate_vin(vin: str) -> str:
    """Validate and normalize VIN. Returns uppercase VIN or raises ValueError."""
    vin = vin.strip().upper()
    if len(vin) != 17:
        raise ValueError(f"VIN must be 17 characters, got {len(vin)}")
    invalid = set(vin) & set("IOQ")
    if invalid:
        raise ValueError(f"VIN contains invalid characters: {invalid}")
    return vin


async def decode_vin(vin: str) -> VehicleInfo:
    """Decode VIN using hardcoded tables + DB lookups.

    Priority:
    1. vin_patterns table (13 chars) — operator-validated, all brands
    2. PSA engine code search in vehicles table (positions 5-7)
    3. Local JSON tables (fallback)
    """
    vin = validate_vin(vin)
    explanation: list[str] = []

    # Step 1: WMI lookup (chars 0-2) -> brand + country
    wmi = vin[:3]
    brand = WMI_TABLE.get(wmi)
    if not brand:
        explanation.append(f"WMI {wmi} non reconnu")
        return VehicleInfo(vin=vin, confidence=Confidence.MISS, explanation=explanation)

    country = WMI_COUNTRY.get(wmi, "")
    explanation.append(f"{wmi} = {brand} ({country})")

    # Step 2: Year lookup (char 9, 0-indexed)
    year_char = vin[9]
    year = YEAR_TABLE.get(year_char)
    if year:
        explanation.append(f"Caractere 10 = {year_char} = annee {year}")

    # Step 3: Check vin_patterns table (13 chars) — highest priority
    vin_pattern_13 = vin[:13]
    pattern_vehicle = await _safe_lookup_vin_pattern(vin_pattern_13)
    if pattern_vehicle:
        explanation.append(f"Pattern {vin_pattern_13} trouve en base")
        return VehicleInfo(
            make=brand,
            model=pattern_vehicle.model,
            year=year,
            engine=_format_engine(pattern_vehicle),
            fuel=pattern_vehicle.fuel,
            vin=vin,
            vehicle_id=pattern_vehicle.id,
            pa24_full_name=pattern_vehicle.pa24_full_name,
            confidence=Confidence.HIGH,
            explanation=explanation,
        )

    # Step 4: PSA brands — engine code from VIN positions 5-7 (0-indexed: 5,6,7)
    if brand in PSA_BRANDS:
        engine_code = vin[5:8]
        result = await _decode_psa(vin, brand, year, engine_code, explanation)
        if result:
            return result
        # PSA engine code not in DB — try JSON fallback
        explanation.append(f"Code moteur {engine_code} non trouve en base")

    # Step 5: Non-PSA explanation
    if brand not in PSA_BRANDS:
        explanation.append(
            "Identification automatique non disponible pour cette marque"
        )
        explanation.append(f"Pattern {vin_pattern_13} non trouve en base")

    # Step 6: JSON table fallback
    result = _decode_from_json_tables(vin, brand, year, explanation)
    if result:
        return result

    # Step 7: Brand + year only
    return VehicleInfo(
        make=brand, year=year, vin=vin,
        confidence=Confidence.LOW, explanation=explanation,
    )


async def _decode_psa(
    vin: str, brand: str, year: int | None,
    engine_code: str, explanation: list[str],
) -> VehicleInfo | None:
    """PSA-specific decode: search engine_code in vehicles table."""
    explanation.append(
        f"Positions 5-7 = {engine_code}\n"
        f"Chez {'/'.join(PSA_BRANDS)}, les positions 5-7 du VIN "
        f"contiennent le code moteur a 3 lettres."
    )

    vehicles = await _safe_search_engine_code(brand, engine_code)

    if not vehicles:
        return None

    # If multiple vehicles share the same engine code, try to disambiguate
    # using model code from JSON tables
    vehicle = vehicles[0]
    if len(vehicles) > 1:
        model_from_json = _get_model_from_json(vin, brand)
        if model_from_json:
            for v in vehicles:
                if model_from_json.lower() in v.model.lower():
                    vehicle = v
                    break

    engine_desc = _format_engine(vehicle)
    explanation.append(f"{engine_code} = {engine_desc}")

    return VehicleInfo(
        make=brand,
        model=vehicle.model,
        year=year,
        engine=engine_desc,
        fuel=vehicle.fuel,
        vin=vin,
        vehicle_id=vehicle.id,
        pa24_full_name=vehicle.pa24_full_name,
        confidence=Confidence.HIGH,
        explanation=explanation,
    )


def _decode_from_json_tables(
    vin: str, brand: str, year: int | None, explanation: list[str],
) -> VehicleInfo | None:
    """Fallback: decode using local JSON tables in data/vin_tables/."""
    from src.vin.tables import find_constructor_table_by_wmi

    wmi = vin[:3]
    table = find_constructor_table_by_wmi(wmi)
    if not table:
        return None

    # Model lookup
    model_pos = table.get("model_positions", [])
    model_code = "".join(vin[p] for p in model_pos) if model_pos else None
    model = table.get("vin_models", {}).get(model_code) if model_code else None

    if not model:
        return None

    # Engine lookup (PSA 3-char codes in JSON)
    engine_pos = table.get("engine_positions", [])
    engine_code = "".join(vin[p] for p in engine_pos) if engine_pos else None
    engine_entry = table.get("engines", {}).get(engine_code) if engine_code else None

    if engine_entry:
        engine_conf = engine_entry.get("confidence", "medium")
        confidence = Confidence.HIGH if engine_conf == "high" else Confidence.MEDIUM
        explanation.append(f"Decode JSON: {model} - {engine_entry['desc']}")
        return VehicleInfo(
            make=brand, model=model, year=year,
            engine=engine_entry["desc"],
            fuel=engine_entry.get("fuel"),
            vin=vin, confidence=confidence, explanation=explanation,
        )

    explanation.append(f"Decode JSON: {model} (motorisation inconnue)")
    return VehicleInfo(
        make=brand, model=model, year=year, vin=vin,
        confidence=Confidence.MEDIUM, explanation=explanation,
    )


def _get_model_from_json(vin: str, brand: str) -> str | None:
    """Try to get model name from JSON table for disambiguation."""
    from src.vin.tables import find_constructor_table_by_wmi

    table = find_constructor_table_by_wmi(vin[:3])
    if not table:
        return None
    model_pos = table.get("model_positions", [])
    model_code = "".join(vin[p] for p in model_pos) if model_pos else None
    return table.get("vin_models", {}).get(model_code) if model_code else None


async def _safe_lookup_vin_pattern(vin_pattern: str):
    """Lookup VIN pattern, returning None if DB unavailable."""
    try:
        from src.db.repository import lookup_vin_pattern
        return await lookup_vin_pattern(vin_pattern)
    except Exception:
        return None


async def _safe_search_engine_code(brand: str, engine_code: str) -> list:
    """Search engine code, returning empty list if DB unavailable."""
    try:
        from src.db.repository import search_vehicles_by_engine_code
        return await search_vehicles_by_engine_code(brand, engine_code)
    except Exception:
        return []


def _format_engine(vehicle) -> str:
    """Format engine description from a Vehicle record."""
    parts = []
    if vehicle.displacement:
        parts.append(vehicle.displacement)
    if vehicle.power_hp:
        parts.append(f"{vehicle.power_hp}CV")
    if vehicle.fuel:
        parts.append(vehicle.fuel)
    if vehicle.engine_code:
        parts.append(vehicle.engine_code)
    return " ".join(parts) if parts else ""
