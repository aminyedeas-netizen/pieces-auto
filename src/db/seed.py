"""Seed database from data/database.json (PiecesAuto24 scraped data)."""

import asyncio
import json
from pathlib import Path

import asyncpg

from src.db.models import Vehicle
from src.db.repository import DATABASE_URL

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "database.json"

_FUEL_MAP = {"Petrol": "Essence", "Diesel": "Diesel", "CNG": "CNG",
             "Electric": "Electrique", "Hybrid": "Hybride"}


def _vehicle_from_dict(v: dict) -> Vehicle:
    """Build a Vehicle from the structured vehicle dict in database.json."""
    disp = v.get("displacement")
    disp_str = str(disp) if disp else None
    fuel_raw = v.get("fuel", "")
    return Vehicle(
        brand=v.get("brand", "").upper(),
        model=v.get("model_generation", ""),
        displacement=disp_str,
        power_hp=v.get("cv"),
        fuel=_FUEL_MAP.get(fuel_raw, fuel_raw),
        year_start=v.get("year_start"),
        year_end=v.get("year_end"),
        engine_code=v.get("engine_code") or None,
        pa24_full_name=v.get("raw_vehicle", ""),
    )


def _extract_oe_refs(specs: dict) -> list[str]:
    """Extract OE reference codes from specs dict."""
    for key, value in specs.items():
        if "similaires" in key.lower() or "oe" in key.lower():
            if isinstance(value, str):
                return [ref.strip() for ref in value.split(",") if ref.strip()]
    return []


async def seed_vehicles():
    """Load data from database.json: upsert vehicles and insert all references.

    Uses COPY + staging tables for speed on large datasets.
    """
    if not DATA_PATH.exists():
        print("data/database.json not found")
        return

    data = json.loads(DATA_PATH.read_text())
    if not data:
        print("database.json is empty, nothing to seed")
        return

    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        await conn.execute("SET statement_timeout = '0'")
        # Phase 0: delete stale vehicles via temp table
        all_names = list({
            entry["vehicle"]["raw_vehicle"]
            for entry in data
            if isinstance(entry.get("vehicle"), dict) and entry["vehicle"].get("raw_vehicle")
        })
        print(f"Preparing {len(all_names)} vehicles...")

        await conn.execute("CREATE TEMP TABLE _keep(name TEXT PRIMARY KEY)")
        await conn.copy_records_to_table("_keep", records=[(n,) for n in all_names], columns=["name"])
        stale = "SELECT id FROM vehicles v WHERE NOT EXISTS (SELECT 1 FROM _keep k WHERE k.name = v.pa24_full_name)"
        await conn.execute(f"DELETE FROM part_vehicle_compatibility WHERE reference_id IN (SELECT id FROM part_references WHERE vehicle_id IN ({stale}))")
        await conn.execute(f"DELETE FROM part_references WHERE vehicle_id IN ({stale})")
        await conn.execute(f"DELETE FROM screenshots WHERE vehicle_id IN ({stale})")
        await conn.execute(f"DELETE FROM vin_patterns WHERE vehicle_id IN ({stale})")
        await conn.execute("DELETE FROM vehicles v WHERE NOT EXISTS (SELECT 1 FROM _keep k WHERE k.name = v.pa24_full_name)")
        await conn.execute("DROP TABLE _keep")
        print("Stale data cleaned")

        # Phase 1: batch upsert vehicles via COPY
        vehicle_rows = []
        seen_names = set()
        for entry in data:
            v_dict = entry.get("vehicle")
            if not isinstance(v_dict, dict):
                continue
            name = v_dict.get("raw_vehicle", "")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            v = _vehicle_from_dict(v_dict)
            vehicle_rows.append((
                v.brand, v.model, v.chassis_code, v.displacement,
                v.power_hp, v.fuel, v.year_start, v.year_end, v.engine_code, v.pa24_full_name,
            ))

        cols = ["brand", "model", "chassis_code", "displacement",
                "power_hp", "fuel", "year_start", "year_end", "engine_code", "pa24_full_name"]
        await conn.execute(f"CREATE TEMP TABLE _vstg ({', '.join(f'{c} TEXT' if c not in ('power_hp','year_start','year_end') else f'{c} INT' for c in cols)})")
        await conn.copy_records_to_table("_vstg", records=vehicle_rows, columns=cols)
        await conn.execute("""
            INSERT INTO vehicles (brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end, engine_code, pa24_full_name)
            SELECT brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end, engine_code, pa24_full_name
            FROM _vstg
            ON CONFLICT (pa24_full_name) DO UPDATE SET
                brand=EXCLUDED.brand, model=EXCLUDED.model, chassis_code=EXCLUDED.chassis_code,
                displacement=EXCLUDED.displacement, power_hp=EXCLUDED.power_hp, fuel=EXCLUDED.fuel,
                year_start=EXCLUDED.year_start, year_end=EXCLUDED.year_end, engine_code=EXCLUDED.engine_code
        """)
        await conn.execute("DROP TABLE _vstg")

        # Build name->id map
        rows = await conn.fetch("SELECT id, pa24_full_name FROM vehicles")
        seen_vehicles = {r["pa24_full_name"]: r["id"] for r in rows}
        print(f"Upserted {len(vehicle_rows)} vehicles")

        # Phase 2: collect refs, skipping vehicles already fully seeded
        # First pass: count expected refs per vehicle from database.json
        expected_counts: dict[int, int] = {}
        for entry in data:
            v_dict = entry.get("vehicle")
            if not isinstance(v_dict, dict):
                continue
            vehicle_name = v_dict.get("raw_vehicle", "")
            if not vehicle_name or vehicle_name not in seen_vehicles:
                continue
            vehicle_id = seen_vehicles[vehicle_name]
            part_name = entry.get("part") or entry.get("part_searched", "")
            if not part_name:
                continue
            n = 0
            product = entry.get("product") or entry.get("product_scraped")
            if product and product.get("brand") and product.get("reference"):
                n += 1
            n += len(_extract_oe_refs(entry.get("specs", {})))
            for eq in entry.get("equivalents", []) or []:
                if eq.get("brand") and eq.get("reference"):
                    n += 1
            for xr in entry.get("cross_references", []) or []:
                if xr.get("brand") and xr.get("reference"):
                    n += 1
            expected_counts[vehicle_id] = expected_counts.get(vehicle_id, 0) + n

        # Get actual ref counts from DB
        db_counts_rows = await conn.fetch(
            "SELECT vehicle_id, COUNT(*) AS cnt FROM part_references GROUP BY vehicle_id"
        )
        db_counts = {r["vehicle_id"]: r["cnt"] for r in db_counts_rows}

        changed_vehicles = {
            vid for vid, expected in expected_counts.items()
            if db_counts.get(vid, 0) != expected
        }
        if not changed_vehicles:
            print(f"Seeded {len(vehicle_rows)} vehicles, 0 new references (all up to date)")
            return

        print(f"{len(changed_vehicles)} vehicles have new references, collecting...")

        ref_rows: list[tuple] = []
        for entry in data:
            v_dict = entry.get("vehicle")
            if not isinstance(v_dict, dict):
                continue
            vehicle_name = v_dict.get("raw_vehicle", "")
            if not vehicle_name or vehicle_name not in seen_vehicles:
                continue
            vehicle_id = seen_vehicles[vehicle_name]
            if vehicle_id not in changed_vehicles:
                continue
            part_name = entry.get("part") or entry.get("part_searched", "")
            if not part_name:
                continue

            product = entry.get("product") or entry.get("product_scraped")
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

        print(f"Seeded {len(vehicle_rows)} vehicles")
    finally:
        await conn.close()

    # Phase 3: insert refs in chunks with fresh connections (Supabase drops long ones)
    CHUNK = 10_000
    print(f"Inserting {len(ref_rows)} references in chunks of {CHUNK}...")
    cols = ["vehicle_id", "part_name", "brand", "reference", "is_oe", "price_eur", "source"]
    for i in range(0, len(ref_rows), CHUNK):
        chunk = ref_rows[i:i + CHUNK]
        for attempt in range(3):
            try:
                c = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
                try:
                    await c.execute("SET statement_timeout = '0'")
                    await c.execute("DROP TABLE IF EXISTS _rstg")
                    await c.execute("""
                        CREATE TEMP TABLE _rstg (
                            vehicle_id INT, part_name TEXT, brand TEXT, reference TEXT,
                            is_oe BOOLEAN, price_eur FLOAT, source TEXT
                        )
                    """)
                    await c.copy_records_to_table("_rstg", records=chunk, columns=cols)
                    await c.execute("""
                        INSERT INTO part_references (vehicle_id, part_name, brand, reference, is_oe, price_eur, source)
                        SELECT vehicle_id, part_name, brand, reference, is_oe, price_eur, source
                        FROM _rstg ON CONFLICT DO NOTHING
                    """)
                finally:
                    await c.close()
                break
            except (asyncpg.exceptions.ConnectionDoesNotExistError,
                    asyncpg.exceptions.QueryCanceledError) as e:
                if attempt < 2:
                    print(f"  chunk {i} attempt {attempt+1} failed ({e}), retrying...")
                    await asyncio.sleep(2)
                else:
                    raise
        print(f"  {min(i + CHUNK, len(ref_rows))}/{len(ref_rows)}")

    print(f"Seeded {len(vehicle_rows)} vehicles, {len(ref_rows)} references")
