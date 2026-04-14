"""Check CDG stock for OE + equivalent references from the database.

Usage:
    uv run python3 scripts/cdg_stock_check.py [--limit N] [--brand BRAND] [--vehicle PATTERN] [--resume]

Outputs:
    data/cdg_stock_results.json  -- full structured results (append-safe)
    stdout                       -- live progress + summary

The script searches OE refs first, then equivalents for the same vehicle+part combos.
Use --resume to skip refs already in the results file.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from dotenv import load_dotenv

load_dotenv()

from src.db.repository import DATABASE_URL
from src.scraper.cdg import CDGScraper

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

RESULTS_FILE = Path(__file__).resolve().parent.parent / "data" / "cdg_stock_results.json"
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "cdg_screenshots"


def load_existing_results() -> dict:
    """Load previous results file if it exists."""
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {"searched": {}, "summary": {}}


def save_results(results: dict):
    """Save results to JSON file."""
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))


async def fetch_refs(
    brand_filter: str | None = None,
    vehicle_filter: str | None = None,
    limit: int = 200,
    exclude_refs: set[str] | None = None,
) -> list[dict]:
    """Fetch OE + equivalent refs from DB, prioritizing CDG-likely parts."""
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)

    # Build WHERE clauses
    conditions = ["1=1"]
    params = []
    idx = 1

    if brand_filter:
        conditions.append(f"v.brand ILIKE ${idx}")
        params.append(f"%{brand_filter}%")
        idx += 1

    if vehicle_filter:
        conditions.append(f"v.pa24_full_name ILIKE ${idx}")
        params.append(f"%{vehicle_filter}%")
        idx += 1

    where = " AND ".join(conditions)

    rows = await conn.fetch(
        f"""
        SELECT DISTINCT pr.reference, pr.brand as ref_brand, pr.part_name,
               pr.source, pr.is_oe, v.brand as vehicle_brand, v.model,
               v.pa24_full_name
        FROM part_references pr
        JOIN vehicles v ON v.id = pr.vehicle_id
        WHERE {where}
        ORDER BY v.brand, v.model, pr.is_oe DESC, pr.reference
        """,
        *params,
    )
    await conn.close()

    # Deduplicate by reference, skip already-searched
    seen = {}
    for r in rows:
        ref = r["reference"]
        if exclude_refs and ref in exclude_refs:
            continue
        if ref not in seen:
            seen[ref] = {
                "reference": ref,
                "ref_brand": r["ref_brand"],
                "part_name": r["part_name"],
                "source": r["source"],
                "is_oe": r["is_oe"],
                "vehicle_brand": r["vehicle_brand"],
                "vehicle": r["pa24_full_name"],
            }

    # Priority 1: part category (CDG-likely parts first, filters/bougies last)
    part_priority = [
        # Tier 0: kit distribution — CDG confirmed stock
        ["kit de distribution", "courroie de distribution", "tendeur de courroie de distribution"],
        # Tier 1: kit embrayage
        ["kit d'embrayage", "embrayage"],
        # Tier 2: freinage
        ["plaquette de frein", "disque de frein", "frein"],
        # Tier 3: roulements, pompe eau, amortisseurs
        ["roulement"],
        ["pompe a eau", "pompe à eau"],
        ["amortisseur"],
        # Tier 4: direction, demarreurs, alternateurs
        ["direction", "cremaillere", "rotule"],
        ["demarreur", "démarreur"],
        ["alternateur"],
        # Tier 5: thermostat, joint, courroie accessoire
        ["thermostat"],
        ["joint"],
        ["kit de courroie d'accessoire", "courroie d'accessoire", "courroie accessoire"],
        # Tier 6: filters and bougies last
        ["filtre"],
        ["bougie"],
    ]

    def get_part_tier(part_name: str) -> int:
        lower = part_name.lower()
        for tier, keywords in enumerate(part_priority):
            for kw in keywords:
                if kw in lower:
                    return tier
        return len(part_priority)  # unknown parts after filters

    # Priority 2: common Tunisian vehicles
    vehicle_keywords = [
        "208", "PureTech", "301", "Partner",
        "Logan", "Sandero", "Duster",
        "Clio", "Symbol", "Megane",
        "Picanto", "Rio", "Sportage",
        "i10", "i20", "Tucson", "Accent",
        "Polo", "Golf", "Caddy",
        "Yaris", "Corolla",
        "Fiorino", "Doblo",
    ]

    def get_vehicle_priority(vehicle: str) -> int:
        lower = vehicle.lower()
        for i, kw in enumerate(vehicle_keywords):
            if kw.lower() in lower:
                return i
        return len(vehicle_keywords)

    def sort_key(item):
        return (get_part_tier(item["part_name"]), get_vehicle_priority(item["vehicle"]), item["reference"])

    sorted_refs = sorted(seen.values(), key=sort_key)
    return sorted_refs[:limit]


async def run_search(refs: list[dict], resume: bool = False):
    """Search CDG for all refs, with resume support."""
    results = load_existing_results() if resume else {"searched": {}, "summary": {}}
    already_done = set(results["searched"].keys()) if resume else set()

    to_search = [r for r in refs if r["reference"] not in already_done]
    print(f"Total refs: {len(refs)} | Already done: {len(already_done)} | To search: {len(to_search)}")
    if not to_search:
        print("Nothing to search.")
        _print_summary(results)
        return

    scraper = CDGScraper()
    for attempt in range(3):
        try:
            await scraper.start()
            break
        except Exception as e:
            print(f"Login attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                print("Could not connect to CDG after 3 attempts.")
                return
            try:
                await scraper.close()
            except Exception:
                pass
            scraper = CDGScraper()
    print("Logged into CDG")
    print()

    found_count = 0
    in_stock_count = 0

    for idx, item in enumerate(to_search):
        ref = item["reference"]
        try:
            raw_results = await scraper.search(ref)

            # Filter: only keep CDG results with exact reference match
            ref_clean = ref.replace(" ", "").replace("-", "").upper()
            cdg_results = []
            for r in raw_results:
                cdg_clean = r.reference.replace(" ", "").replace("-", "").upper()
                if cdg_clean == ref_clean:
                    cdg_results.append(r)

            entry = {
                "ref_brand": item["ref_brand"],
                "part_name": item["part_name"],
                "source": item["source"],
                "is_oe": item["is_oe"],
                "vehicle": item["vehicle"],
                "vehicle_brand": item["vehicle_brand"],
                "cdg_found": len(cdg_results) > 0,
                "cdg_raw_count": len(raw_results),
                "cdg_results": [],
            }

            if cdg_results:
                found_count += 1
                avail = [r for r in cdg_results if r.available]
                rupt = [r for r in cdg_results if not r.available]
                if avail:
                    in_stock_count += 1

                for r in cdg_results:
                    entry["cdg_results"].append({
                        "cdg_ref": r.reference,
                        "description": r.description,
                        "price": r.price,
                        "available": r.available,
                    })

                status = f"FOUND: {len(avail)} stock, {len(rupt)} rupture"

                # Save screenshot for manual verification
                SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                safe_brand = item["vehicle_brand"].replace(" ", "_")
                safe_part = item["part_name"].replace(" ", "_").replace("/", "-")[:30]
                safe_ref = ref.replace(" ", "_").replace("/", "-")
                filename = f"{safe_brand}_{safe_part}_{safe_ref}.png"
                await scraper.screenshot(str(SCREENSHOTS_DIR / filename))
            else:
                status = "not found"

            results["searched"][ref] = entry

            # Print progress
            progress = f"[{idx + 1}/{len(to_search)}]"
            oe_tag = "OE" if item["is_oe"] else item["ref_brand"]
            print(f"{progress} {ref} ({oe_tag}, {item['part_name'][:30]}) -> {status}")

            # Auto-save every 25 searches
            if (idx + 1) % 25 == 0:
                _update_summary(results)
                save_results(results)
                print(f"  -- saved ({found_count} found, {in_stock_count} in stock so far) --")

        except Exception as e:
            print(f"[{idx + 1}] ERROR {ref}: {e}")
            results["searched"][ref] = {
                "ref_brand": item["ref_brand"],
                "part_name": item["part_name"],
                "source": item["source"],
                "is_oe": item["is_oe"],
                "vehicle": item["vehicle"],
                "vehicle_brand": item["vehicle_brand"],
                "cdg_found": False,
                "error": str(e),
                "cdg_results": [],
            }
            # Reconnect
            try:
                await scraper.close()
            except Exception:
                pass
            scraper = CDGScraper()
            await scraper.start()

    await scraper.close()

    _update_summary(results)
    save_results(results)
    print()
    _print_summary(results)

    # Auto-generate HTML+PDF report
    try:
        from scripts.generate_cdg_report import main as generate_report
        print()
        generate_report()
    except Exception as e:
        print(f"Report generation failed: {e}")


def _update_summary(results: dict):
    """Recompute summary stats from searched data."""
    searched = results["searched"]
    total = len(searched)
    found = sum(1 for v in searched.values() if v.get("cdg_found"))
    in_stock = sum(
        1 for v in searched.values()
        if any(r.get("available") for r in v.get("cdg_results", []))
    )
    rupture_only = found - in_stock
    oe_found = sum(1 for v in searched.values() if v.get("cdg_found") and v.get("is_oe"))
    equiv_found = sum(1 for v in searched.values() if v.get("cdg_found") and not v.get("is_oe"))

    results["summary"] = {
        "total_searched": total,
        "found_on_cdg": found,
        "in_stock": in_stock,
        "rupture_only": rupture_only,
        "not_found": total - found,
        "oe_found": oe_found,
        "equiv_found": equiv_found,
    }


def _print_summary(results: dict):
    """Print human-readable summary."""
    s = results.get("summary", {})
    print("=" * 60)
    print("CDG STOCK CHECK SUMMARY")
    print("=" * 60)
    print(f"Total searched:    {s.get('total_searched', 0)}")
    print(f"Found on CDG:      {s.get('found_on_cdg', 0)}")
    print(f"  In stock:        {s.get('in_stock', 0)}")
    print(f"  Rupture only:    {s.get('rupture_only', 0)}")
    print(f"  OE refs found:   {s.get('oe_found', 0)}")
    print(f"  Equiv found:     {s.get('equiv_found', 0)}")
    print(f"Not found on CDG:  {s.get('not_found', 0)}")
    print()

    # Show in-stock items grouped by vehicle
    searched = results.get("searched", {})
    in_stock_items = [
        (ref, data) for ref, data in searched.items()
        if any(r.get("available") for r in data.get("cdg_results", []))
    ]

    if in_stock_items:
        print("IN STOCK AT CDG:")
        print("-" * 60)
        by_vehicle = {}
        for ref, data in in_stock_items:
            v = data.get("vehicle", "?")
            by_vehicle.setdefault(v, []).append((ref, data))

        for vehicle, items in sorted(by_vehicle.items()):
            print(f"  {vehicle}")
            for ref, data in items:
                tag = "OE" if data.get("is_oe") else data.get("ref_brand", "?")
                print(f"    [{tag}] {ref} ({data['part_name']})")
                for r in data["cdg_results"]:
                    if r["available"]:
                        price = f"{r['price']:.3f} TND" if r.get("price") else "N/A"
                        print(f"      -> {r['cdg_ref']} {r['description'][:40]} | {price}")
            print()


def main():
    parser = argparse.ArgumentParser(description="Check CDG stock for DB references")
    parser.add_argument("--limit", type=int, default=200, help="Max refs to search (default 200)")
    parser.add_argument("--brand", type=str, help="Filter by vehicle brand (e.g. PEUGEOT)")
    parser.add_argument("--vehicle", type=str, help="Filter by vehicle name pattern (e.g. '208 PureTech')")
    parser.add_argument("--resume", action="store_true", help="Skip refs already in results file")
    parser.add_argument("--summary", action="store_true", help="Just print summary of existing results")
    args = parser.parse_args()

    if args.summary:
        results = load_existing_results()
        _print_summary(results)
        return

    async def _run():
        # When resuming, pass already-searched refs to fetch_refs so it picks new ones
        exclude = set()
        if args.resume:
            existing = load_existing_results()
            exclude = set(existing.get("searched", {}).keys())
            if exclude:
                print(f"Resuming: {len(exclude)} refs already searched, fetching new ones")

        refs = await fetch_refs(
            brand_filter=args.brand,
            vehicle_filter=args.vehicle,
            limit=args.limit,
            exclude_refs=exclude if exclude else None,
        )
        print(f"Fetched {len(refs)} new refs from DB (limit={args.limit})")
        oe = sum(1 for r in refs if r["is_oe"])
        equiv = len(refs) - oe
        print(f"  OE: {oe} | Equivalents/cross-refs: {equiv}")
        print()
        await run_search(refs, resume=args.resume)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
