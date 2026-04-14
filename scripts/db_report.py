"""Descriptive DB report - lists brands, vehicles, engines, parts by name.

Writes data/db_report.md. Re-run after each re-seed:
    uv run python3 scripts/db_report.py
"""
import asyncio
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def fetch():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        vehicles = await conn.fetch(
            """
            SELECT id, brand, model, chassis_code, displacement, power_hp, fuel,
                   year_start, year_end, engine_code, pa24_full_name
            FROM vehicles
            ORDER BY brand, model, year_start NULLS LAST, displacement
            """
        )
        parts = await conn.fetch(
            """
            SELECT v.id AS vehicle_id, pr.part_name,
                   COUNT(DISTINCT (pr.brand, pr.reference)) AS refs
            FROM vehicles v
            JOIN part_references pr ON pr.vehicle_id = v.id
            GROUP BY v.id, pr.part_name
            """
        )
        vin_counts = await conn.fetch(
            """
            SELECT vehicle_id, COUNT(*) AS n
            FROM vin_patterns GROUP BY vehicle_id
            """
        )
        totals = await conn.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM vehicles)                           AS vehicles,
              (SELECT COUNT(DISTINCT brand) FROM vehicles)              AS brands,
              (SELECT COUNT(DISTINCT model) FROM vehicles)              AS models,
              (SELECT COUNT(*) FROM part_references)                    AS pr_rows,
              (SELECT COUNT(DISTINCT (brand, reference)) FROM part_references) AS uniq_refs,
              (SELECT COUNT(DISTINCT part_name) FROM part_references)   AS part_categories,
              (SELECT COUNT(*) FROM vin_patterns)                       AS vin_patterns
            """
        )
        return {
            "vehicles": [dict(r) for r in vehicles],
            "parts": [dict(r) for r in parts],
            "vin_counts": {r["vehicle_id"]: r["n"] for r in vin_counts},
            "totals": dict(totals),
        }
    finally:
        await conn.close()


def year_str(ys, ye):
    if ys is None:
        return "année non renseignée"
    if ye is None or ye == ys:
        return f"{ys}"
    return f"{ys}-{ye}"


def engine_label(v: dict) -> str:
    bits = []
    if v["displacement"]:
        bits.append(v["displacement"])
    if v["power_hp"]:
        bits.append(f"{v['power_hp']} CV")
    if v["fuel"]:
        bits.append(v["fuel"])
    if v["engine_code"]:
        bits.append(f"code {v['engine_code']}")
    return " · ".join(bits) if bits else "moteur non renseigné"


def render(data) -> str:
    vehicles = data["vehicles"]
    parts_by_v = defaultdict(list)
    for p in data["parts"]:
        parts_by_v[p["vehicle_id"]].append((p["part_name"], p["refs"]))
    for v_id in parts_by_v:
        parts_by_v[v_id].sort(key=lambda x: (-x[1], x[0]))

    by_brand = defaultdict(lambda: defaultdict(list))
    for v in vehicles:
        by_brand[v["brand"]][v["model"]].append(v)

    t = data["totals"]
    out = [
        "# Rapport base de données - Pieces Auto TN",
        "",
        f"_Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        "## Vue d'ensemble",
        "",
        f"La base contient **{t['brands']} marques**, **{t['models']} modèles** et "
        f"**{t['vehicles']} variantes** (année + motorisation).",
        "",
        f"Pour ces véhicules, nous avons référencé **{t['uniq_refs']:,} références uniques** "
        f"de pièces détachées, réparties sur **{t['part_categories']} catégories de pièces** "
        f"(amortisseurs, filtres, freins, distribution, etc.). "
        f"Une même référence peut être compatible avec plusieurs véhicules ; "
        f"au total on compte **{t['pr_rows']:,} associations pièce ↔ véhicule**.",
        "",
        f"Le décodage VIN s'appuie sur **{t['vin_patterns']} patterns** enregistrés "
        f"(les 13 premiers caractères d'un VIN → véhicule).",
        "",
        "## Marques couvertes",
        "",
        "| Marque | Modèles | Variantes | Références uniques |",
        "|---|---:|---:|---:|",
    ]
    brand_totals = []
    for brand in sorted(by_brand):
        models = by_brand[brand]
        n_variants = sum(len(vs) for vs in models.values())
        uniq = set()
        for vs in models.values():
            for v in vs:
                for pn, _ in parts_by_v.get(v["id"], []):
                    pass
        # compute unique refs for brand via separate query-style aggregate from data
        brand_vids = {v["id"] for vs in models.values() for v in vs}
        # rebuild from parts data
        brand_refs = 0
        # we only have (part_name, refs) per vehicle, which overcounts; query again inline
        brand_totals.append((brand, len(models), n_variants, brand_vids))
    # second pass: brand unique refs via data['parts'] summed per vehicle then reported as approx-none.
    # For accuracy we fetch again via the raw connection pool inside render? Not possible; use
    # an approximate row-sum plus a note instead.
    out.pop()  # remove sep placeholder? actually keep header
    # Replace with correct values via a helper pre-computed in totals_by_brand.
    return out, brand_totals


async def main():
    data = await fetch()
    # Second pass for accurate per-brand unique refs
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        brand_uniq = {
            r["brand"]: r["u"]
            for r in await conn.fetch(
                """
                SELECT v.brand, COUNT(DISTINCT (pr.brand, pr.reference)) AS u
                FROM vehicles v JOIN part_references pr ON pr.vehicle_id = v.id
                GROUP BY v.brand
                """
            )
        }
    finally:
        await conn.close()

    vehicles = data["vehicles"]
    parts_by_v = defaultdict(list)
    for p in data["parts"]:
        parts_by_v[p["vehicle_id"]].append((p["part_name"], p["refs"]))
    for v_id in parts_by_v:
        parts_by_v[v_id].sort(key=lambda x: (-x[1], x[0]))

    by_brand = defaultdict(lambda: defaultdict(list))
    for v in vehicles:
        by_brand[v["brand"]][v["model"]].append(v)

    t = data["totals"]
    out = [
        "# Rapport base de données - Pieces Auto TN",
        "",
        f"_Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        "## Vue d'ensemble",
        "",
        f"La base contient **{t['brands']} marques**, **{t['models']} modèles** et "
        f"**{t['vehicles']} variantes** (année + motorisation).",
        "",
        f"Pour ces véhicules, nous avons référencé **{t['uniq_refs']:,} références uniques** "
        f"réparties sur **{t['part_categories']} catégories de pièces** "
        f"(amortisseurs, filtres, freins, distribution, etc.). "
        f"Une même référence peut être compatible avec plusieurs véhicules ; "
        f"au total on compte **{t['pr_rows']:,} associations pièce ↔ véhicule**.",
        "",
        f"Le décodage VIN s'appuie sur **{t['vin_patterns']} patterns** enregistrés.",
        "",
        "## Marques couvertes",
        "",
        "| Marque | Modèles | Variantes | Références uniques |",
        "|---|---:|---:|---:|",
    ]
    for brand in sorted(by_brand):
        models = by_brand[brand]
        n_var = sum(len(vs) for vs in models.values())
        out.append(f"| {brand} | {len(models)} | {n_var} | {brand_uniq.get(brand, 0):,} |")
    out.append("")

    out.append("## Détail par marque")
    out.append("")
    for brand in sorted(by_brand):
        models = by_brand[brand]
        n_var = sum(len(vs) for vs in models.values())
        out.append(f"### {brand}")
        out.append("")
        out.append(
            f"_{len(models)} modèle(s), {n_var} variante(s), "
            f"{brand_uniq.get(brand, 0):,} références uniques._"
        )
        out.append("")
        for model in sorted(models):
            variants = models[model]
            out.append(f"#### {model}")
            out.append("")
            # gather years
            years = [v["year_start"] for v in variants if v["year_start"]]
            years_end = [v["year_end"] for v in variants if v["year_end"]]
            if years:
                ymin = min(years)
                ymax = max(years_end) if years_end else max(years)
                out.append(f"- Période : **{ymin}-{ymax}**" if ymin != ymax else f"- Année : **{ymin}**")
            else:
                out.append("- Période : _non renseignée_")
            # engines list
            out.append(f"- Variantes indexées ({len(variants)}) :")
            for v in variants:
                parts_count = len(parts_by_v.get(v["id"], []))
                uniq_refs_v = sum(refs for _, refs in parts_by_v.get(v["id"], []))
                vin_n = data["vin_counts"].get(v["id"], 0)
                vin_txt = f" · {vin_n} VIN pattern(s)" if vin_n else ""
                out.append(
                    f"  - **{year_str(v['year_start'], v['year_end'])}** — "
                    f"{engine_label(v)} · {parts_count} catégories / "
                    f"{uniq_refs_v} réf.{vin_txt}"
                )
            # top 5 parts for this model (aggregated across variants)
            agg = defaultdict(int)
            for v in variants:
                for pn, refs in parts_by_v.get(v["id"], []):
                    agg[pn] += refs
            if agg:
                top = sorted(agg.items(), key=lambda x: -x[1])[:5]
                out.append(
                    "- Top catégories (somme des réf. sur toutes les variantes) : "
                    + ", ".join(f"{pn} ({n})" for pn, n in top)
                )
            out.append("")
    Path("data/db_report.md").write_text("\n".join(out))
    print(f"Rapport écrit : data/db_report.md ({sum(1 for _ in out)} lignes)")


if __name__ == "__main__":
    asyncio.run(main())
