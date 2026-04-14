"""Database queries for Pieces Auto TN."""

import asyncio
import os

import asyncpg
from dotenv import load_dotenv

from src.db.models import Confidence, Vehicle, VehicleInfo, StoredReference

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _get_pool() -> asyncpg.Pool:
    """Lazy-init a shared asyncpg connection pool. Safe under concurrent callers."""
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    statement_cache_size=0,
                )
    return _pool


async def warmup_pool() -> None:
    """Open the pool and run a trivial query so the first real request is fast."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")


async def _get_conn():
    """Acquire a connection from the pool. Release with `await _release(conn)`."""
    pool = await _get_pool()
    return await pool.acquire()


async def _release(conn) -> None:
    pool = await _get_pool()
    await pool.release(conn)


async def init_schema():
    """Create tables if they don't exist."""
    conn = await _get_conn()
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path) as f:
            sql = f.read()
        await conn.execute(sql)
    finally:
        await _release(conn)


async def lookup_vin_pattern(vin_pattern: str) -> Vehicle | None:
    """Look up a VIN pattern (13 chars) in vin_patterns table. Returns Vehicle if found."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT v.id, v.brand, v.model, v.chassis_code, v.displacement,
                   v.power_hp, v.fuel, v.year_start, v.year_end,
                   v.engine_code, v.pa24_full_name
            FROM vin_patterns vp
            JOIN vehicles v ON v.id = vp.vehicle_id
            WHERE vp.vin_pattern = $1
            """,
            vin_pattern,
        )
        if not row:
            return None
        return _row_to_vehicle(row)
    finally:
        await _release(conn)


async def search_vehicles_by_engine_code(brand: str, engine_code: str) -> list[Vehicle]:
    """Search vehicles table by brand + engine_code. For PSA VIN decoding."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
              AND LOWER(engine_code) = LOWER($2)
            ORDER BY model, year_start
            """,
            brand, engine_code,
        )
        return [_row_to_vehicle(r) for r in rows]
    finally:
        await _release(conn)


def _row_to_vehicle(row) -> Vehicle:
    """Convert a DB row to a Vehicle object."""
    return Vehicle(
        id=row["id"],
        brand=row["brand"],
        model=row["model"],
        chassis_code=row["chassis_code"],
        displacement=row["displacement"],
        power_hp=row["power_hp"],
        fuel=row["fuel"],
        year_start=row["year_start"],
        year_end=row["year_end"],
        engine_code=row["engine_code"],
        pa24_full_name=row["pa24_full_name"],
    )


async def get_all_vehicles() -> list[Vehicle]:
    """Get all vehicles."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            ORDER BY brand, model
            """
        )
        return [_row_to_vehicle(r) for r in rows]
    finally:
        await _release(conn)


async def get_vehicles_by_brand(brand: str) -> list[Vehicle]:
    """Get all vehicles for a brand."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
            ORDER BY model, year_start
            """,
            brand,
        )
        return [_row_to_vehicle(r) for r in rows]
    finally:
        await _release(conn)


async def get_vehicle_by_id(vehicle_id: int) -> Vehicle | None:
    """Get vehicle by ID."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            WHERE id = $1
            """,
            vehicle_id,
        )
        if not row:
            return None
        return _row_to_vehicle(row)
    finally:
        await _release(conn)


async def upsert_vehicle(vehicle: Vehicle) -> int:
    """Insert or update vehicle by pa24_full_name. Returns vehicle ID."""
    conn = await _get_conn()
    try:
        vehicle_id = await conn.fetchval(
            """
            INSERT INTO vehicles (brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (pa24_full_name) DO UPDATE SET
                brand = $1, model = $2, chassis_code = $3, displacement = $4,
                power_hp = $5, fuel = $6, year_start = $7, year_end = $8,
                engine_code = $9
            RETURNING id
            """,
            vehicle.brand,
            vehicle.model,
            vehicle.chassis_code,
            vehicle.displacement,
            vehicle.power_hp,
            vehicle.fuel,
            vehicle.year_start,
            vehicle.year_end,
            vehicle.engine_code,
            vehicle.pa24_full_name,
        )
        return vehicle_id
    finally:
        await _release(conn)


async def add_vin_pattern(vin_pattern: str, vehicle_id: int, confidence: str = "high") -> None:
    """Store a VIN pattern -> vehicle mapping."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO vin_patterns (vin_pattern, vehicle_id, confidence)
            VALUES ($1, $2, $3)
            ON CONFLICT (vin_pattern) DO UPDATE SET
                vehicle_id = $2, confidence = $3
            """,
            vin_pattern,
            vehicle_id,
            confidence,
        )
    finally:
        await _release(conn)


async def lookup_references(vehicle_id: int, part_name: str) -> list[StoredReference]:
    """Find all references for a vehicle + part name."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, vehicle_id, part_name, brand, reference, is_oe,
                   price_eur, source
            FROM part_references
            WHERE vehicle_id = $1 AND LOWER(part_name) = LOWER($2)
            ORDER BY is_oe DESC, brand
            """,
            vehicle_id,
            part_name,
        )
        return [
            StoredReference(
                id=r["id"],
                vehicle_id=r["vehicle_id"],
                part_name=r["part_name"],
                brand=r["brand"],
                reference=r["reference"],
                is_oe=r["is_oe"],
                price_eur=r["price_eur"],
                source=r["source"],
            )
            for r in rows
        ]
    finally:
        await _release(conn)


async def lookup_references_grouped(vehicle_id: int, part_name: str) -> dict[str, list[StoredReference]]:
    """Find refs for vehicle+part, grouped by source type (oe, main_product, equivalent, cross_reference)."""
    refs = await lookup_references(vehicle_id, part_name)
    grouped: dict[str, list[StoredReference]] = {
        "oe": [], "main_product": [], "equivalent": [], "cross_reference": [],
    }
    for r in refs:
        key = r.source if r.source in grouped else "equivalent"
        grouped[key].append(r)
    return grouped


async def insert_reference(
    vehicle_id: int,
    part_name: str,
    brand: str,
    reference: str,
    is_oe: bool,
    price_eur: float | None = None,
    source: str = "piecesauto24",
) -> int:
    """Insert a part reference. Returns reference ID."""
    conn = await _get_conn()
    try:
        ref_id = await conn.fetchval(
            """
            INSERT INTO part_references (vehicle_id, part_name, brand,
                   reference, is_oe, price_eur, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            vehicle_id,
            part_name,
            brand,
            reference,
            is_oe,
            price_eur,
            source,
        )
        if ref_id:
            return ref_id
        row = await conn.fetchrow(
            """
            SELECT id FROM part_references
            WHERE vehicle_id = $1 AND part_name = $2 AND
                  brand = $3 AND reference = $4
            """,
            vehicle_id,
            part_name,
            brand,
            reference,
        )
        return row["id"]
    finally:
        await _release(conn)


async def get_all_references_for_vehicle(vehicle_id: int) -> list[StoredReference]:
    """Get all references for a vehicle (all parts)."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, vehicle_id, part_name, brand, reference, is_oe,
                   price_eur, source
            FROM part_references
            WHERE vehicle_id = $1
            ORDER BY part_name, is_oe DESC, brand
            """,
            vehicle_id,
        )
        return [
            StoredReference(
                id=r["id"],
                vehicle_id=r["vehicle_id"],
                part_name=r["part_name"],
                brand=r["brand"],
                reference=r["reference"],
                is_oe=r["is_oe"],
                price_eur=r["price_eur"],
                source=r["source"],
            )
            for r in rows
        ]
    finally:
        await _release(conn)


async def insert_compatibility(reference_id: int, compatible_vehicle_name: str) -> None:
    """Insert a compatible vehicle for a reference."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO part_vehicle_compatibility (reference_id, compatible_vehicle_name)
            VALUES ($1, $2)
            """,
            reference_id,
            compatible_vehicle_name,
        )
    finally:
        await _release(conn)


async def insert_screenshot(
    vehicle_id: int,
    part_name: str | None,
    filename: str,
    screenshot_type: str | None = None,
) -> int:
    """Insert screenshot record. Returns screenshot ID."""
    conn = await _get_conn()
    try:
        screenshot_id = await conn.fetchval(
            """
            INSERT INTO screenshots (vehicle_id, part_name, filename, screenshot_type)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            vehicle_id,
            part_name,
            filename,
            screenshot_type,
        )
        return screenshot_id
    finally:
        await _release(conn)


async def log_request(
    telegram_user_id: int,
    vehicle_id: int | None,
    part_name: str | None,
    vin: str | None,
    vin_confidence: str | None,
    cdg_results_count: int = 0,
) -> None:
    """Log a client request."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO requests_log (telegram_user_id, vehicle_id, part_name,
                   vin, vin_confidence, cdg_results_count)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            telegram_user_id,
            vehicle_id,
            part_name,
            vin,
            vin_confidence,
            cdg_results_count,
        )
    finally:
        await _release(conn)


async def get_stats() -> dict:
    """Return DB stats: vehicles, references, vin_patterns, requests today."""
    conn = await _get_conn()
    try:
        vehicles = await conn.fetchval("SELECT COUNT(*) FROM vehicles")
        references = await conn.fetchval("SELECT COUNT(*) FROM part_references")
        vin_patterns = await conn.fetchval("SELECT COUNT(*) FROM vin_patterns")
        requests_today = await conn.fetchval(
            "SELECT COUNT(*) FROM requests_log WHERE created_at >= CURRENT_DATE"
        )
        return {
            "vehicles": vehicles,
            "references": references,
            "vin_patterns": vin_patterns,
            "requests_today": requests_today,
        }
    finally:
        await _release(conn)


async def get_distinct_brands() -> list[str]:
    """Get all distinct brands from vehicles table, sorted."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT brand FROM vehicles
            ORDER BY brand
            """
        )
        return [r["brand"] for r in rows]
    finally:
        await _release(conn)


import re as _re

_ENGINE_SUFFIX_RE = _re.compile(
    r"\s+(?:"
    r"\d{1,3}\s*CV\b"
    r"|\d{4}\s*[-\u2014]"
    r"|BlueHDi|BLUEHDI|PureTech|PURETECH|TCe|HDi|HDI|Blue\s*dCi|dCi"
    r"|e-[\w\u00C0-\u017F]+"
    r"|\((?:[A-Z0-9, ]+)\)\s+\d"
    r")"
)


def _canonical_model(model: str) -> str:
    """Strip engine-spec suffix (e.g. ' BlueHDi 110 CV Diesel 2020 - ...')."""
    m = _ENGINE_SUFFIX_RE.search(model)
    return model[: m.start()].rstrip(" -\u2014") if m else model


async def get_distinct_models(brand: str) -> list[str]:
    """Distinct models for a brand, with engine-suffixed variants collapsed.

    Engine specs (BlueHDi, PureTech, "131 CV", year ranges) inside model names
    are stripped to a canonical base. Multiple originals collapsing to the same
    canonical are merged. The returned canonical is what callbacks pass to
    get_vehicles_for_model / get_distinct_years_for_model, which prefix-match.
    """
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT model FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
            ORDER BY model
            """,
            brand,
        )
        canonicals: dict[str, str] = {}  # lower(canonical) -> displayed canonical
        for r in rows:
            c = _canonical_model(r["model"])
            key = c.lower()
            # prefer the shortest representative for a stable label
            if key not in canonicals or len(c) < len(canonicals[key]):
                canonicals[key] = c
        # second pass: prefix-collapse (e.g. "C4 Phase 3" absorbs "C4 Phase 3 X")
        all_models = sorted(canonicals.values(), key=lambda m: (len(m), m.lower()))
        keep: list[str] = []
        for m in all_models:
            ml = m.lower()
            if not any(ml.startswith(k.lower() + " ") for k in keep):
                keep.append(m)
        return sorted(keep, key=str.lower)
    finally:
        await _release(conn)


async def get_vehicles_for_model(brand: str, model: str) -> list[Vehicle]:
    """Get all vehicle variants for a brand+model (different engines).

    Matches the model exactly OR any model that starts with `model + " "`,
    so engine-suffixed variants stored in the model column are included.
    """
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
              AND (LOWER(model) = LOWER($2) OR LOWER(model) LIKE LOWER($2) || ' %')
            ORDER BY year_start, engine_code
            """,
            brand,
            model,
        )
        return [_row_to_vehicle(r) for r in rows]
    finally:
        await _release(conn)


async def get_distinct_years_for_model(brand: str, model: str) -> list[int]:
    """Get distinct year_start values for a brand+model (prefix-match), sorted."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT year_start FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
              AND (LOWER(model) = LOWER($2) OR LOWER(model) LIKE LOWER($2) || ' %')
              AND year_start IS NOT NULL
            ORDER BY year_start
            """,
            brand,
            model,
        )
        return [r["year_start"] for r in rows]
    finally:
        await _release(conn)


async def get_vehicles_for_model_year(brand: str, model: str, year: int) -> list[Vehicle]:
    """Get vehicle variants for brand+model+year (model prefix-matches)."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement,
                   power_hp, fuel, year_start, year_end,
                   engine_code, pa24_full_name
            FROM vehicles
            WHERE LOWER(brand) = LOWER($1)
              AND (LOWER(model) = LOWER($2) OR LOWER(model) LIKE LOWER($2) || ' %')
              AND year_start = $3
            ORDER BY engine_code
            """,
            brand,
            model,
            year,
        )
        return [_row_to_vehicle(r) for r in rows]
    finally:
        await _release(conn)


async def get_parts_for_vehicle(vehicle_id: int) -> list[str]:
    """Get distinct part names that have references for a vehicle."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT part_name FROM part_references
            WHERE vehicle_id = $1
            ORDER BY part_name
            """,
            vehicle_id,
        )
        return [r["part_name"] for r in rows]
    finally:
        await _release(conn)


async def search_parts_fuzzy(vehicle_id: int, query: str) -> list[str]:
    """Find part names for a vehicle that contain the query string."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT part_name FROM part_references
            WHERE vehicle_id = $1 AND LOWER(part_name) LIKE '%' || LOWER($2) || '%'
            ORDER BY part_name
            """,
            vehicle_id, query,
        )
        return [r["part_name"] for r in rows]
    finally:
        await _release(conn)
