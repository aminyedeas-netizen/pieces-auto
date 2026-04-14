"""Seed database from data/database.json (PiecesAuto24 scraped data)."""

import json
import re
from pathlib import Path

import asyncpg

from src.db.models import Vehicle
from src.db.repository import DATABASE_URL

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "database.json"


def _parse_vehicle_name(name: str) -> Vehicle:
    """Parse a PiecesAuto24 vehicle name string into a Vehicle."""
    parts = name.split()
    brand = parts[0] if parts else ""

    displacement = None
    power_hp = None
    fuel = None
    engine_code = None
    year_start = None
    year_end = None
    model_parts = []

    i = 1
    while i < len(parts):
        p = parts[i]
        if re.match(r"^\d+\.\d+$", p):
            displacement = p
            i += 1
            break
        model_parts.append(p)
        i += 1

    remaining = parts[i:]
    remaining_str = " ".join(remaining)

    hp_match = re.search(r"(\d+)\s*CV", remaining_str)
    if hp_match:
        power_hp = int(hp_match.group(1))

    for fuel_kw in ("Diesel", "Essence"):
        if fuel_kw in remaining_str:
            fuel = fuel_kw
            break

    year_match = re.search(r"(\d{4})\s*-\s*(\d{4}|\.\.\.)", remaining_str)
    if year_match:
        year_start = int(year_match.group(1))
        if year_match.group(2) != "...":
            year_end = int(year_match.group(2))

    skip = {"CV", "Essence", "Diesel", "-", "..."}
    tech_kw = {"PureTech", "BlueHDi", "HDi", "dCi", "TDI", "TSI", "MPI",
               "CRDi", "T-GDi", "VTVT", "MSi", "GTI", "TCi", "VTi"}
    candidates = []
    for token in remaining:
        if token in skip or re.match(r"^\d{4}$", token) or re.match(r"^\d+$", token):
            continue
        if re.match(r"^\(.*\)$", token) or token in tech_kw:
            continue
        if re.match(r"^[A-Za-z0-9]", token):
            candidates.append(token)

    if candidates:
        engine_code = " ".join(candidates)

    model = " ".join(model_parts) if model_parts else ""

    return Vehicle(
        brand=brand.upper(),
        model=model,
        displacement=displacement,
        power_hp=power_hp,
        fuel=fuel,
        year_start=year_start,
        year_end=year_end,
        engine_code=engine_code,
        pa24_full_name=name,
    )


def _extract_oe_refs(specs: dict) -> list[str]:
    """Extract OE reference codes from specs dict."""
    for key, value in specs.items():
        if "similaires" in key.lower() or "oe" in key.lower():
            if isinstance(value, str):
                return [ref.strip() for ref in value.split(",") if ref.strip()]
    return []


async def _upsert_vehicle(conn: asyncpg.Connection, vehicle: Vehicle) -> int:
    """Upsert vehicle using existing connection."""
    return await conn.fetchval(
        """
        INSERT INTO vehicles (brand, model, chassis_code, displacement,
               power_hp, fuel, year_start, year_end, engine_code, pa24_full_name)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (pa24_full_name) DO UPDATE SET
            brand = $1, model = $2, chassis_code = $3, displacement = $4,
            power_hp = $5, fuel = $6, year_start = $7, year_end = $8, engine_code = $9
        RETURNING id
        """,
        vehicle.brand, vehicle.model, vehicle.chassis_code, vehicle.displacement,
        vehicle.power_hp, vehicle.fuel, vehicle.year_start, vehicle.year_end,
        vehicle.engine_code, vehicle.pa24_full_name,
    )


async def _insert_ref(
    conn: asyncpg.Connection, vehicle_id: int, part_name: str,
    brand: str, reference: str, is_oe: bool,
    price_eur: float | None, source: str,
) -> None:
    """Insert reference using existing connection."""
    await conn.execute(
        """
        INSERT INTO part_references (vehicle_id, part_name, brand, reference, is_oe, price_eur, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT DO NOTHING
        """,
        vehicle_id, part_name, brand, reference, is_oe, price_eur, source,
    )


async def seed_vehicles():
    """Load data from database.json: upsert vehicles and insert all references."""
    if not DATA_PATH.exists():
        print("data/database.json not found")
        return

    data = json.loads(DATA_PATH.read_text())
    if not data:
        print("database.json is empty, nothing to seed")
        return

    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        # Phase 0: collect all valid pa24_full_names, delete stale data
        all_names = list({entry["vehicle"] for entry in data if entry.get("vehicle")})
        if all_names:
            stale_filter = "SELECT id FROM vehicles WHERE pa24_full_name != ALL($1::text[])"
            # Delete from all FK-dependent tables first
            await conn.execute(
                "DELETE FROM part_vehicle_compatibility WHERE reference_id IN "
                f"(SELECT id FROM part_references WHERE vehicle_id IN ({stale_filter}))",
                all_names,
            )
            await conn.execute(
                f"DELETE FROM part_references WHERE vehicle_id IN ({stale_filter})",
                all_names,
            )
            await conn.execute(
                f"DELETE FROM screenshots WHERE vehicle_id IN ({stale_filter})",
                all_names,
            )
            await conn.execute(
                f"DELETE FROM vin_patterns WHERE vehicle_id IN ({stale_filter})",
                all_names,
            )
            await conn.execute(
                "DELETE FROM vehicles WHERE pa24_full_name != ALL($1::text[])",
                all_names,
            )

        # Phase 1: upsert vehicles
        seen_vehicles: dict[str, int] = {}
        for entry in data:
            vehicle_name = entry.get("vehicle", "")
            if not vehicle_name or vehicle_name in seen_vehicles:
                continue
            vehicle = _parse_vehicle_name(vehicle_name)
            vehicle_id = await _upsert_vehicle(conn, vehicle)
            seen_vehicles[vehicle_name] = vehicle_id

        print(f"Upserted {len(seen_vehicles)} vehicles")

        # Phase 2: batch-collect all references
        ref_rows: list[tuple] = []
        for entry in data:
            vehicle_name = entry.get("vehicle", "")
            if not vehicle_name or vehicle_name not in seen_vehicles:
                continue
            vehicle_id = seen_vehicles[vehicle_name]
            part_name = entry.get("part_searched", "")
            if not part_name:
                continue

            product = entry.get("product_scraped")
            if product and product.get("brand") and product.get("reference"):
                ref_rows.append((
                    vehicle_id, part_name, product["brand"],
                    product["reference"], False, product.get("price_eur"), "main_product",
                ))

            for ref_code in _extract_oe_refs(entry.get("specs", {})):
                ref_rows.append((vehicle_id, part_name, "OE", ref_code, True, None, "oe"))

            for eq in entry.get("equivalents", []) or []:
                if eq.get("brand") and eq.get("reference"):
                    ref_rows.append((
                        vehicle_id, part_name, eq["brand"], eq["reference"],
                        False, eq.get("price_eur"), "equivalent",
                    ))

            for xr in entry.get("cross_references", []) or []:
                if xr.get("brand") and xr.get("reference"):
                    ref_rows.append((
                        vehicle_id, part_name, xr["brand"], xr["reference"],
                        False, xr.get("price_eur"), "cross_reference",
                    ))

        # Phase 3: batch insert refs with executemany
        if ref_rows:
            await conn.executemany(
                """
                INSERT INTO part_references (vehicle_id, part_name, brand, reference, is_oe, price_eur, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT DO NOTHING
                """,
                ref_rows,
            )

        print(f"Seeded {len(seen_vehicles)} vehicles, {len(ref_rows)} references")
    finally:
        await conn.close()
