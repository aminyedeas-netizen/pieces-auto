"""Pivot tables: part_name (rows) x model (columns) = unique refs (cells).

One pivot per brand. Zeros shown as blank for readability.
Writes data/db_pivot.md and data/db_pivot.csv.
"""
import asyncio
import csv
import os
from collections import defaultdict
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def fetch():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            SELECT v.brand, v.model, pr.part_name,
                   COUNT(DISTINCT (pr.brand, pr.reference)) AS refs
            FROM vehicles v
            JOIN part_references pr ON pr.vehicle_id = v.id
            GROUP BY v.brand, v.model, pr.part_name
            ORDER BY v.brand, v.model, pr.part_name
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def build_pivot(rows):
    # brand -> {model_list, part_list, matrix[part][model]}
    brands = defaultdict(lambda: {"models": [], "parts": set(), "matrix": defaultdict(dict)})
    for r in rows:
        b = brands[r["brand"]]
        if r["model"] not in b["models"]:
            b["models"].append(r["model"])
        b["parts"].add(r["part_name"])
        b["matrix"][r["part_name"]][r["model"]] = r["refs"]
    for b in brands.values():
        b["parts"] = sorted(b["parts"])
    return brands


def short_model(m: str, maxlen: int = 25) -> str:
    return m if len(m) <= maxlen else m[: maxlen - 1] + "…"


def write_markdown(brands, path: Path):
    out = [
        "# Pieces Auto TN - Parts x Models Coverage",
        "",
        "Cell value = **unique references** stored for that part on that model "
        "(distinct `brand + reference` pairs). Blank = no coverage yet.",
        "",
        "Model names are shortened; full names in `data/db_inventory.md`.",
        "",
    ]
    for brand in sorted(brands):
        b = brands[brand]
        out.append(f"## {brand}")
        out.append("")
        header = "| Part \\ Model | " + " | ".join(short_model(m) for m in b["models"]) + " | **Total** |"
        sep = "|---|" + "|".join(["---:"] * len(b["models"])) + "|---:|"
        out.append(header)
        out.append(sep)
        # row totals = sum across models (same ref counted multiple times here — ok for quick read)
        col_totals = defaultdict(int)
        grand = 0
        for part in b["parts"]:
            cells = []
            row_total = 0
            for m in b["models"]:
                v = b["matrix"][part].get(m, 0)
                cells.append(str(v) if v else "")
                row_total += v
                col_totals[m] += v
            grand += row_total
            out.append(f"| {part} | " + " | ".join(cells) + f" | **{row_total}** |")
        tot_cells = [f"**{col_totals[m]}**" for m in b["models"]]
        out.append(f"| **Total** | " + " | ".join(tot_cells) + f" | **{grand}** |")
        out.append("")
    path.write_text("\n".join(out))


def write_csv(brands, path: Path):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        for brand in sorted(brands):
            b = brands[brand]
            w.writerow([f"[{brand}]"])
            w.writerow(["Part"] + b["models"])
            for part in b["parts"]:
                row = [part] + [b["matrix"][part].get(m, "") for m in b["models"]]
                w.writerow(row)
            w.writerow([])


async def main():
    rows = await fetch()
    brands = build_pivot(rows)
    out_dir = Path("data")
    write_markdown(brands, out_dir / "db_pivot.md")
    write_csv(brands, out_dir / "db_pivot.csv")
    # Brief stdout sample: Peugeot
    b = brands["PEUGEOT"]
    print("=== PEUGEOT pivot (sample) ===")
    models = b["models"]
    header = f"{'PART':<32}" + "".join(f"{short_model(m, 10):>12}" for m in models)
    print(header)
    for part in b["parts"][:12]:
        row = f"{part[:31]:<32}"
        for m in models:
            v = b["matrix"][part].get(m, 0)
            row += f"{(str(v) if v else '-'):>12}"
        print(row)
    print("...")
    print(f"\nFull pivot tables written to data/db_pivot.md and data/db_pivot.csv")
    print(f"Brands covered: {len(brands)}")
    print(f"Peugeot: {len(b['parts'])} parts x {len(b['models'])} models")


if __name__ == "__main__":
    asyncio.run(main())
