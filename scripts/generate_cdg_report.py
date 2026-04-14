"""Generate a clean HTML+PDF report of CDG stock check results.

Usage:
    uv run python3 scripts/generate_cdg_report.py

Reads data/cdg_stock_results.json and outputs data/cdg_report.html + .pdf

Layout: grouped by part category (Plaquette de frein, Kit distribution, etc.).
Each found CDG ref shows OE/equivalent tag, price, status and the full list
of DB vehicles that use that ref. The catalog cycle searches refs against one
vehicle but a ref typically fits many — this report surfaces all of them.
"""

import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

RESULTS_FILE = Path(__file__).resolve().parent.parent / "data" / "cdg_stock_results.json"
OUTPUT_HTML = Path(__file__).resolve().parent.parent / "data" / "cdg_report.html"
OUTPUT_PDF = Path(__file__).resolve().parent.parent / "data" / "cdg_report.pdf"

DATABASE_URL = os.environ["DATABASE_URL"]


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _normalize(ref: str) -> str:
    return ref.replace(" ", "").replace("-", "").upper()


# Part category buckets — used to roll many specific part_name strings up into
# a small set of human-friendly category headers.
CATEGORIES: list[tuple[str, list[str]]] = [
    ("Distribution", ["distribution", "tendeur", "courroie"]),
    ("Embrayage", ["embrayage"]),
    ("Freinage", ["frein", "plaquette", "disque", "etrier", "machoire"]),
    ("Roulements", ["roulement"]),
    ("Pompe a eau / Refroidissement", ["pompe a eau", "pompe à eau", "thermostat", "radiateur", "durite"]),
    ("Suspension / Amortisseurs", ["amortisseur", "ressort", "biellette"]),
    ("Direction", ["direction", "cremaillere", "rotule"]),
    ("Demarrage / Charge", ["demarreur", "démarreur", "alternateur", "batterie"]),
    ("Joints", ["joint"]),
    ("Filtration", ["filtre"]),
    ("Allumage", ["bougie", "bobine"]),
    ("Echappement", ["echappement", "pot", "silencieux"]),
]


def categorize(part_name: str) -> str:
    lower = (part_name or "").lower()
    for label, keywords in CATEGORIES:
        for kw in keywords:
            if kw in lower:
                return label
    return "Autres"


async def fetch_vehicles_by_ref(refs: set[str]) -> dict[str, list[dict]]:
    """For each normalized reference, return the list of compatible vehicles in the DB.

    Vehicles are deduplicated by id and ordered brand, model, year_start.
    """
    if not refs:
        return {}
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            SELECT pr.reference, v.id AS vehicle_id, v.brand, v.model,
                   v.pa24_full_name, v.engine_code, v.year_start, v.year_end
            FROM part_references pr
            JOIN vehicles v ON v.id = pr.vehicle_id
            """,
        )
    finally:
        await conn.close()

    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        norm = _normalize(r["reference"])
        if norm not in refs:
            continue
        vid = r["vehicle_id"]
        if vid in out[norm]:
            continue
        out[norm][vid] = {
            "brand": r["brand"],
            "model": r["model"],
            "full_name": r["pa24_full_name"],
            "engine_code": r["engine_code"],
            "year_start": r["year_start"],
            "year_end": r["year_end"],
        }

    result: dict[str, list[dict]] = {}
    for norm, vmap in out.items():
        vehicles = sorted(
            vmap.values(),
            key=lambda v: (v["brand"] or "", v["model"] or "", v["year_start"] or 0),
        )
        result[norm] = vehicles
    return result


def _best_cdg_row(d: dict) -> dict | None:
    """Pick the most informative CDG row (prefer in-stock with price)."""
    rows = d.get("cdg_results", [])
    if not rows:
        return None
    in_stock = [r for r in rows if r.get("available")]
    if in_stock:
        return in_stock[0]
    return rows[0]


def _build_card(ref: str, d: dict, vehicles: list[dict]) -> str:
    """Render one found-ref card."""
    cdg_row = _best_cdg_row(d) or {}
    in_stock = cdg_row.get("available", False)
    status_class = "stock" if in_stock else "rupt"
    status_label = "En stock" if in_stock else "Rupture"
    price = cdg_row.get("price")
    price_html = (
        f'<span class="price">{price:.3f} TND</span>' if price else '<span class="price-na">prix N/A</span>'
    )
    is_oe = d.get("is_oe")
    tag_class = "tag-oe" if is_oe else "tag-eq"
    tag_label = "ORIGINE" if is_oe else _esc(d.get("ref_brand", "EQUIV"))

    cdg_desc = _esc(cdg_row.get("description", ""))
    cdg_ref = _esc(cdg_row.get("cdg_ref") or ref)

    veh_html = ""
    if vehicles:
        items = []
        for v in vehicles:
            year = ""
            if v["year_start"] and v["year_end"]:
                year = f" ({v['year_start']}-{v['year_end']})"
            elif v["year_start"]:
                year = f" ({v['year_start']}+)"
            engine = f" — moteur {_esc(v['engine_code'])}" if v.get("engine_code") else ""
            items.append(
                f'<li><strong>{_esc(v["brand"])} {_esc(v["model"])}</strong>{year}{engine}</li>'
            )
        veh_html = (
            f'<div class="veh-block"><div class="veh-title">Compatible avec {len(vehicles)} '
            f'vehicule{"s" if len(vehicles) > 1 else ""} :</div>'
            f'<ul class="veh-list">{"".join(items)}</ul></div>'
        )
    else:
        veh_html = '<div class="veh-block"><div class="veh-title">Aucun vehicule lie en base</div></div>'

    return f"""
<div class="card">
  <div class="card-head">
    <span class="status {status_class}">{status_label}</span>
    <span class="tag {tag_class}">{tag_label}</span>
    <span class="ref-code">{cdg_ref}</span>
    {price_html}
  </div>
  <div class="card-body">
    <div class="part-name">{_esc(d.get("part_name", ""))}</div>
    <div class="cdg-desc">{cdg_desc}</div>
    {veh_html}
  </div>
</div>
"""


def build_html(searched: dict, vehicles_by_ref: dict[str, list[dict]]) -> str:
    found_items = [(ref, d) for ref, d in searched.items() if d.get("cdg_found")]
    in_stock_items = [
        (ref, d) for ref, d in found_items
        if any(r.get("available") for r in d.get("cdg_results", []))
    ]
    rupture_items = [
        (ref, d) for ref, d in found_items
        if not any(r.get("available") for r in d.get("cdg_results", []))
    ]
    total = len(searched)
    not_found_total = total - len(found_items)

    # Coverage: how many distinct vehicles have at least one ref found on CDG
    distinct_vehicles_covered = set()
    for ref, _ in found_items:
        for v in vehicles_by_ref.get(_normalize(ref), []):
            distinct_vehicles_covered.add(v["full_name"])

    # Group found items by category
    by_cat: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for ref, d in found_items:
        by_cat[categorize(d.get("part_name", ""))].append((ref, d))

    # Sort categories by amount, then within sort by in-stock first then OE first
    def _item_sort(t):
        ref, d = t
        in_stock = any(r.get("available") for r in d.get("cdg_results", []))
        return (not in_stock, not d.get("is_oe"), d.get("part_name", ""))

    cat_order = sorted(by_cat.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    style = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 24px; color: #1f2937;
         background: #f3f4f6; }
  h1 { color: #0f172a; font-size: 24px; border-bottom: 3px solid #2563eb;
       padding-bottom: 10px; margin-top: 0; }
  h2.cat { color: #fff; background: #0f172a; padding: 12px 18px;
           border-radius: 8px; font-size: 17px; margin-top: 36px; }
  h2.cat .count { font-weight: normal; opacity: 0.7; font-size: 13px; }

  .summary { background: #fff; border-radius: 10px; padding: 20px 24px;
             margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .summary p { margin: 6px 0; font-size: 14px; line-height: 1.6; }
  .stat { font-weight: 700; color: #2563eb; }

  .card { background: #fff; border-radius: 10px; margin: 14px 0;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06);
          border-left: 4px solid #d1d5db; overflow: hidden;
          page-break-inside: avoid; }
  .card-head { padding: 12px 18px; background: #f9fafb;
               border-bottom: 1px solid #e5e7eb; display: flex;
               align-items: center; gap: 12px; flex-wrap: wrap; }
  .card-body { padding: 14px 18px; }

  .status { font-size: 11px; font-weight: 700; padding: 3px 10px;
            border-radius: 12px; text-transform: uppercase;
            letter-spacing: 0.5px; }
  .stock { background: #dcfce7; color: #166534; }
  .rupt  { background: #fee2e2; color: #991b1b; }

  .tag { font-size: 10px; font-weight: 700; padding: 3px 8px;
         border-radius: 4px; text-transform: uppercase;
         letter-spacing: 0.5px; }
  .tag-oe { background: #1e3a8a; color: #fff; }
  .tag-eq { background: #475569; color: #fff; }

  .ref-code { font-family: 'SF Mono', Consolas, monospace; font-weight: 700;
              color: #0f172a; font-size: 14px; }
  .price { margin-left: auto; font-weight: 700; color: #0f172a; font-size: 15px; }
  .price-na { margin-left: auto; color: #9ca3af; font-size: 13px; }

  .part-name { font-weight: 600; color: #0f172a; margin-bottom: 4px; }
  .cdg-desc { font-size: 12px; color: #6b7280; margin-bottom: 12px; }

  .veh-block { background: #f9fafb; padding: 10px 14px; border-radius: 6px;
               border-left: 3px solid #2563eb; }
  .veh-title { font-size: 12px; font-weight: 600; color: #374151;
               margin-bottom: 6px; text-transform: uppercase;
               letter-spacing: 0.3px; }
  .veh-list { margin: 0; padding-left: 18px; columns: 2;
              column-gap: 24px; font-size: 12px; line-height: 1.7;
              color: #374151; }
  .veh-list li { break-inside: avoid; }

  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e7eb;
            color: #9ca3af; font-size: 11px; text-align: center; }

  @media print {
    body { background: #fff; padding: 0; }
    .card { border: 1px solid #e5e7eb; }
  }
</style>
"""
    head = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>CDG Grossiste - Catalogue pieces compatibles</title>
{style}</head><body>
<h1>CDG Grossiste - Catalogue pieces compatibles</h1>

<div class="summary">
  <p>Recherche effectuee sur <span class="stat">{total}</span> references chez CDG Grossiste (cdgros.com).</p>
  <p>Resultat : <span class="stat">{len(found_items)}</span> references distribuees par CDG, dont
     <span class="stat">{len(in_stock_items)}</span> en stock et
     <span class="stat">{len(rupture_items)}</span> en rupture.
     <span class="stat">{not_found_total}</span> references non distribuees.</p>
  <p>Couverture vehicules (au moins une piece trouvee) : <span class="stat">{len(distinct_vehicles_covered)}</span>.</p>
  <p>Le catalogue est organise par categorie de piece. Pour chaque reference trouvee chez CDG,
     la liste des vehicules de notre base compatibles avec cette piece est affichee dessous.</p>
</div>
"""

    body_parts = []
    for cat, items in cat_order:
        items_sorted = sorted(items, key=_item_sort)
        body_parts.append(
            f'<h2 class="cat">{_esc(cat)} <span class="count">- {len(items_sorted)} reference{"s" if len(items_sorted) > 1 else ""}</span></h2>'
        )
        for ref, d in items_sorted:
            body_parts.append(_build_card(ref, d, vehicles_by_ref.get(_normalize(ref), [])))

    footer = f"""
<div class="footer">
Rapport genere le {datetime.now().strftime('%d/%m/%Y a %H:%M')} - {total} references recherchees sur CDG Grossiste (cdgros.com)
</div>
</body></html>
"""
    return head + "\n".join(body_parts) + footer


async def _amain():
    if not RESULTS_FILE.exists():
        print("No results file found. Run cdg_stock_check.py first.")
        return

    data = json.loads(RESULTS_FILE.read_text())
    searched = data.get("searched", {})
    if not searched:
        print("No results to report.")
        return

    found_refs = {_normalize(ref) for ref, d in searched.items() if d.get("cdg_found")}
    vehicles_by_ref = await fetch_vehicles_by_ref(found_refs)

    html = build_html(searched, vehicles_by_ref)
    OUTPUT_HTML.write_text(html)
    print(f"HTML saved to {OUTPUT_HTML}")

    # Print short summary
    total = len(searched)
    found_items = [d for d in searched.values() if d.get("cdg_found")]
    in_stock = sum(1 for d in found_items if any(r.get("available") for r in d.get("cdg_results", [])))
    print(f"\n  Total searched: {total}")
    print(f"  Found on CDG:   {len(found_items)}")
    print(f"    En stock:     {in_stock}")
    print(f"    Rupture:      {len(found_items) - in_stock}")


def _generate_pdf():
    """PDF via Playwright sync API. Must run OUTSIDE any asyncio loop."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"file://{OUTPUT_HTML}")
            page.pdf(
                path=str(OUTPUT_PDF), format="A4", print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()
        print(f"PDF  saved to {OUTPUT_PDF}")
    except Exception as e:
        print(f"PDF generation failed: {e}")


def main():
    asyncio.run(_amain())
    _generate_pdf()


if __name__ == "__main__":
    main()
