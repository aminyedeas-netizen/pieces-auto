"""Generate inventory report: brand, model, years, engines, parts, unique refs.

Outputs:
- stdout: aligned text table
- data/db_inventory.md: markdown table (shareable)
- data/db_inventory.csv: CSV
"""
import asyncio
import csv
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def fetch_rows() -> list[dict]:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            SELECT
                v.brand,
                v.model,
                MIN(v.year_start) AS year_from,
                MAX(COALESCE(v.year_end, v.year_start)) AS year_to,
                COUNT(DISTINCT COALESCE(v.engine_code, v.displacement, v.pa24_full_name)) AS engines,
                COUNT(DISTINCT pr.part_name) AS parts,
                COUNT(DISTINCT (pr.brand, pr.reference)) AS refs
            FROM vehicles v
            LEFT JOIN part_references pr ON pr.vehicle_id = v.id
            GROUP BY v.brand, v.model
            ORDER BY v.brand, v.model
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def year_str(yf, yt):
    if yf is None:
        return "-"
    if yt is None or yt == yf:
        return str(yf)
    return f"{yf}-{yt}"


def print_table(rows: list[dict]):
    headers = ["BRAND", "MODEL", "YEARS", "ENGINES", "PARTS", "REFS"]
    widths = [12, 48, 11, 8, 7, 6]
    line = "".join(h.ljust(w) for h, w in zip(headers, widths))
    print("=" * sum(widths))
    print(line)
    print("=" * sum(widths))
    cur_brand = None
    brand_tot = {"engines": 0, "parts": 0, "refs": 0, "models": 0}

    def flush_brand():
        if cur_brand is None:
            return
        print(
            f"{'':<12}{'-- ' + cur_brand + ' total (' + str(brand_tot['models']) + ' models)':<48}"
            f"{'':<11}{brand_tot['engines']:<8}{brand_tot['parts']:<7}{brand_tot['refs']:<6}"
        )
        print("-" * sum(widths))

    for r in rows:
        if r["brand"] != cur_brand:
            flush_brand()
            cur_brand = r["brand"]
            brand_tot = {"engines": 0, "parts": 0, "refs": 0, "models": 0}
        m = r["model"][:47]
        print(
            f"{r['brand']:<12}{m:<48}{year_str(r['year_from'], r['year_to']):<11}"
            f"{r['engines']:<8}{r['parts']:<7}{r['refs']:<6}"
        )
        brand_tot["engines"] += r["engines"]
        brand_tot["parts"] += r["parts"]
        brand_tot["refs"] += r["refs"]
        brand_tot["models"] += 1
    flush_brand()


def write_markdown(rows: list[dict], path: Path):
    tot_engines = sum(r["engines"] for r in rows)
    tot_parts = sum(r["parts"] for r in rows)
    tot_refs = sum(r["refs"] for r in rows)
    brands = sorted({r["brand"] for r in rows})

    lines = [
        "# Pieces Auto TN - Database Inventory",
        "",
        f"**{len(brands)} brands · {len(rows)} models · ~{tot_refs:,} unique references**",
        "",
        "## How to read this table",
        "",
        "- **Years**: production span covered (from earliest `year_start` to latest `year_end`).",
        "- **Engines**: distinct engine/displacement variants we indexed for that model "
        "(a single model can have petrol/diesel/electric and several displacements).",
        "- **Parts**: distinct part categories checked (Amortisseur avant, Filtre à huile, etc.).",
        "- **Unique refs**: distinct `(brand, reference)` SKUs stored. "
        "Same SKU shared across compatible variants is counted once.",
        "",
        "## Summary by brand",
        "",
        "| Brand | Models | Engines | Parts checked | Unique refs |",
        "|---|---:|---:|---:|---:|",
    ]
    for b in brands:
        sub = [r for r in rows if r["brand"] == b]
        lines.append(
            f"| {b} | {len(sub)} | {sum(r['engines'] for r in sub)} | "
            f"{sum(r['parts'] for r in sub)} | {sum(r['refs'] for r in sub):,} |"
        )
    lines.append(f"| **TOTAL** | **{len(rows)}** | **{tot_engines}** | **{tot_parts}** | **{tot_refs:,}** |")
    lines.append("")
    lines.append("## Detail by model")
    lines.append("")
    lines.append("| Brand | Model | Years | Engines | Parts | Unique refs |")
    lines.append("|---|---|---|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['brand']} | {r['model']} | {year_str(r['year_from'], r['year_to'])} | "
            f"{r['engines']} | {r['parts']} | {r['refs']:,} |"
        )
    path.write_text("\n".join(lines))


def write_csv(rows: list[dict], path: Path):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["brand", "model", "years", "engines", "parts_checked", "unique_refs"])
        for r in rows:
            w.writerow(
                [
                    r["brand"],
                    r["model"],
                    year_str(r["year_from"], r["year_to"]),
                    r["engines"],
                    r["parts"],
                    r["refs"],
                ]
            )


async def main():
    rows = await fetch_rows()
    print_table(rows)
    out_dir = Path("data")
    write_markdown(rows, out_dir / "db_inventory.md")
    write_csv(rows, out_dir / "db_inventory.csv")
    print(f"\nWrote data/db_inventory.md and data/db_inventory.csv")


if __name__ == "__main__":
    asyncio.run(main())
