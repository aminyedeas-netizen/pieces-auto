"""PiecesAuto24 scraper: search PA24, extract product data from HTML, save to DB.

Adapted from scripts/add_product.py for headless bot use. No screenshots or LLM
vision — everything is parsed from HTML with BeautifulSoup.
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

from src.db.repository import upsert_vehicle, insert_reference, insert_compatibility
from src.db.models import Vehicle

log = logging.getLogger(__name__)

# Canonical brand casing (from add_product.py)
BRAND_CASE = {
    "PEUGEOT": "Peugeot", "CITROEN": "Citroen", "RENAULT": "Renault",
    "DACIA": "Dacia", "VOLKSWAGEN": "Volkswagen", "KIA": "Kia",
    "HYUNDAI": "Hyundai", "TOYOTA": "Toyota", "FIAT": "Fiat",
    "FORD": "Ford", "SEAT": "Seat", "NISSAN": "Nissan",
    "OPEL": "Opel", "SKODA": "Skoda", "AUDI": "Audi",
    "BMW": "BMW", "MERCEDES-BENZ": "Mercedes-Benz",
}

FUEL_MARKERS = {
    "Essence/\u00e9lectrique": "Hybrid", "\u00c9lectrique": "Electric",
    "Essence": "Petrol", "Diesel": "Diesel", "GNC": "CNG",
}

MULTI_WORD_BRANDS = {
    "BLUE PRINT", "FEBI BILSTEIN", "KAVO PARTS", "RIDEX PLUS",
    "HERTH+BUSS JAKOPARTS", "DACO Germany", "MASTER SPORT",
    "QUINTON HAZELL", "MEAT DORIA", "MEAT & DORIA",
    "WIX FILTERS", "MAGNETI MARELLI", "HELLA PAGID",
}
_MULTI_FIRST = {b.split()[0] for b in MULTI_WORD_BRANDS}


def _strip_accents(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _human_delay():
    import random
    return random.uniform(1.5, 3)


# ---------------------------------------------------------------------------
# Browser connection (CDP to running Chrome, bypasses Cloudflare)
# ---------------------------------------------------------------------------

CDP_URL = "http://localhost:9222"

# Serialize all CDP access — Chrome can't handle concurrent Playwright connections reliably
_cdp_lock = asyncio.Lock()


async def _connect():
    """Connect to Chrome via CDP, reusing the existing tab.

    Chrome must be running with --remote-debugging-port=9222.
    Reuses pages[0] which already passed Cloudflare. Callers are serialized
    via _cdp_lock so concurrent access is impossible.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    return pw, page


async def search_pa24(query: str) -> str | None:
    """Search PA24 for a reference or query. Returns product page URL or None.

    Uses the search field on the homepage (URL-based search doesn't work
    reliably with CDP — stale results). Also extracts product data while on
    the page to avoid a second navigation. Data is cached in _extracted_cache.
    """
    clean = query.strip()

    async with _cdp_lock:
        pw, page = await _connect()
        try:
            # Navigate to homepage and type in the search field
            await page.goto("https://www.piecesauto24.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            title = await page.title()
            if "cloudflare" in title.lower() or "attention" in title.lower():
                log.warning("Cloudflare challenge on PA24")
                return None

            search_input = page.locator("input[name='keyword']").first
            if not await search_input.count():
                log.error("PA24 search field not found")
                return None

            await search_input.click()
            await search_input.fill(clean)

            # Press Enter triggers navigation — wait for it properly
            await page.keyboard.press("Enter")

            # Wait for URL to change to search results page
            for _ in range(20):
                await page.wait_for_timeout(500)
                try:
                    url = page.url
                    if "rechercher" in url or "keyword" in url:
                        break
                except Exception:
                    pass
            else:
                log.warning("PA24 search: URL did not change to search results")

            # Let the page fully render
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)

            # Retry evaluate in case context is still settling
            results = None
            for attempt in range(3):
                try:
                    results = await page.evaluate("""() => {
                        const items = document.querySelectorAll('a.listing-item__name');
                        return Array.from(items).slice(0, 10).map(a => ({
                            text: a.textContent.trim(),
                            href: a.href
                        }));
                    }""")
                    break
                except Exception as e:
                    if "context" in str(e).lower() and attempt < 2:
                        log.debug("PA24 evaluate retry %d: %s", attempt + 1, e)
                        await page.wait_for_timeout(2000)
                    else:
                        raise

            if not results:
                log.info("PA24 search for '%s': no results", clean)
                return None

            ref_clean = clean.replace(" ", "").upper()
            matched_url = None

            for r in results[:5]:
                await page.goto(r["href"], wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                info = await page.evaluate("""() => {
                    const refEl = document.querySelector('.product-block__article');
                    const ref = refEl ? refEl.textContent.trim().replace(/^N°\\s*de\\s*référence\\s*:\\s*/, '') : '';
                    return {ref};
                }""")

                ref_on_page = info["ref"].replace(" ", "").upper()
                if ref_clean in ref_on_page or ref_on_page in ref_clean:
                    matched_url = page.url
                    break

            if not matched_url:
                log.info("PA24 no exact match for %s, using first result", query)
                await page.goto(results[0]["href"], wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                matched_url = page.url

            # Extract product data now while we're on the page
            log.info("PA24 match: %s -> %s, extracting data...", query, matched_url)
            data = await _extract_from_current_page(page)
            if data:
                _extracted_cache[matched_url] = (time.time(), data)
                log.info("PA24 data cached for %s", matched_url)

            return matched_url
        except Exception as e:
            log.error("PA24 search error: %s", e)
            return None
        finally:
            await pw.stop()


# Cache for extracted product data — populated by search_pa24, consumed by extract_product_page
_extracted_cache: dict[str, tuple[float, dict]] = {}  # {url: (timestamp, data)}
_EXTRACT_CACHE_TTL = 300  # 5 minutes


async def _extract_compatible_vehicles(page) -> list[dict]:
    """Click each brand accordion in #compatibility to load models via AJAX."""
    brand_links = page.locator("#compatibility [data-toggle-maker]")
    count = await brand_links.count()
    if not count:
        return []

    result = []
    for i in range(count):
        link = brand_links.nth(i)
        brand = (await link.text_content()).strip()
        if not brand:
            continue
        try:
            await link.click(timeout=3000)
            await page.wait_for_timeout(2000)
        except Exception:
            continue

        # After clicking, models appear as .product-info-block__item-list__title
        parent = page.locator(f"#compatibility .product-info-block__item").nth(i)
        model_els = parent.locator(".product-info-block__item-list__title")
        model_count = await model_els.count()
        models = []
        for j in range(model_count):
            text = (await model_els.nth(j).text_content()).strip()
            if text:
                models.append(text)
        if models:
            result.append({"brand": brand, "models": models})

    return result


async def _extract_from_current_page(page) -> dict | None:
    """Extract product data from a PA24 page that is already loaded.

    Shared extraction logic used by both search_pa24 and extract_product_page.
    """
    try:
        await page.wait_for_timeout(2000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        sections = {}

        el = page.locator(".product-block").first
        if await el.count():
            sections["fiche"] = await el.inner_html(timeout=5000)

        await _scroll_to(page, ".product-description")
        el = page.locator(".product-description").first
        if await el.count():
            sections["specs"] = await el.inner_html(timeout=5000)

        await _scroll_to(page, "#alternative-products")
        while True:
            btn = page.locator("#alternative-products .slick-next:not(.slick-disabled)")
            if not await btn.count():
                break
            try:
                await btn.click(timeout=5000)
                await asyncio.sleep(_human_delay())
            except Exception:
                break
        el = page.locator("#alternative-products").first
        if await el.count():
            sections["equivalents"] = await el.inner_html(timeout=5000)

        await _scroll_to(page, ".product-similar-spec")
        el = page.locator(".product-similar-spec").first
        if await el.count():
            sections["cross_refs"] = await el.inner_html(timeout=5000)

        # OE refs — in #oem section, each <li> has <a> with "BRAND ref_code"
        await _scroll_to(page, "#oem")
        oe_data = await page.evaluate("""() => {
            const section = document.querySelector('#oem');
            if (!section) return [];
            const refs = [];
            for (const li of section.querySelectorAll('li')) {
                const a = li.querySelector('a');
                if (!a) continue;
                const text = a.textContent.trim();
                // Format: "RENAULT 77 00 777 654" or "BMW / MINI 31 31 6 781 903"
                // Handle "BRAND1 / BRAND2 ref" pattern
                const slashMatch = text.match(/^([A-Z][A-Z\\s]*?)\\s*\\/\\s*([A-Z][A-Z]+)\\s+(.+)$/);
                if (slashMatch) {
                    refs.push({brand: slashMatch[1].trim() + ' / ' + slashMatch[2].trim(), ref: slashMatch[3]});
                    continue;
                }
                const parts = text.split(/\\s+/);
                if (parts.length >= 2) {
                    const brand = parts[0];
                    const ref = parts.slice(1).join(' ');
                    refs.push({brand, ref});
                }
            }
            return refs;
        }""")
        # Convert to [{brand, refs: [ref]}] format for _parse_oe_refs
        oe_grouped = {}
        for item in oe_data:
            oe_grouped.setdefault(item["brand"], []).append(item["ref"])
        oe_data_grouped = [{"brand": b, "refs": r} for b, r in oe_grouped.items()]

        # Compatible vehicles — brand accordions load models lazily via AJAX
        await _scroll_to(page, "#compatibility")
        compatible_vehicles = await _extract_compatible_vehicles(page)

        product = _parse_fiche(sections.get("fiche", ""))
        specs = _parse_specs(sections.get("specs", ""))
        equivalents = _parse_equivalents(sections.get("equivalents", ""))
        cross_refs = _parse_cross_references(sections.get("cross_refs", ""))
        oe_refs = _parse_oe_refs(oe_data_grouped)

        log.info("PA24 extracted: ref=%s, %d equivs, %d cross, %d oe, %d compat brands",
                 product.get("reference", "?"), len(equivalents), len(cross_refs),
                 len(oe_refs), len(compatible_vehicles))

        if not product.get("reference"):
            return None

        return {
            "product": product,
            "specs": specs,
            "equivalents": equivalents,
            "cross_refs": cross_refs,
            "oe_refs": oe_refs,
            "compatible_vehicles": compatible_vehicles,
        }
    except Exception as e:
        log.error("PA24 extraction from current page failed: %s", e)
        return None


async def extract_product_page(url: str) -> dict | None:
    """Extract product data from a PA24 URL.

    Checks the cache first (populated by search_pa24). Only navigates
    to the URL if cache miss.
    """
    # Check cache — search_pa24 already extracted this data
    cached = _extracted_cache.pop(url, None)
    if cached and time.time() - cached[0] < _EXTRACT_CACHE_TTL:
        log.info("PA24 extraction cache hit for %s", url)
        return cached[1]

    # Cache miss — must navigate (may hit Cloudflare)
    async with _cdp_lock:
        pw, page = await _connect()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            for attempt in range(3):
                try:
                    title = await page.title()
                    break
                except Exception as e:
                    if attempt < 2:
                        await page.wait_for_timeout(2000)
                    else:
                        raise
            if "cloudflare" in title.lower():
                log.warning("Cloudflare challenge on PA24")
                return None
            return await _extract_from_current_page(page)
        except Exception as e:
            log.error("PA24 extraction failed: %s", e)
            return None
        finally:
            await pw.stop()


async def _scroll_to(page, selector):
    el = page.locator(selector).first
    if await el.count():
        try:
            await el.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.5)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTML parsing (BeautifulSoup)
# ---------------------------------------------------------------------------

def _parse_fiche(html: str) -> dict:
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")

    brand = ""
    brand_link = soup.select_one("a.product-gallery__brand") or soup.select_one(".product-gallery__brand a")
    if brand_link and brand_link.get("href"):
        m = re.search(r"/m-([^/]+?)(?:\?|$)", brand_link["href"])
        if m:
            brand = m.group(1).replace("-", " ").upper()

    reference, ean = "", ""
    for span in soup.select(".product-block__article"):
        text = span.get_text(strip=True)
        if "r\u00e9f" in text.lower():
            reference = re.sub(r"^N\u00b0\s*de\s*r\u00e9f\u00e9rence\s*:\s*", "", text).strip()
        elif text.startswith("EAN:"):
            ean = text.replace("EAN:", "").strip()

    name = ""
    title_el = soup.select_one(".product-block__title")
    if title_el:
        subtitle = title_el.select_one(".product-block__subtitle")
        if subtitle:
            subtitle.extract()
        title_text = title_el.get_text(strip=True)
        if reference and reference in title_text:
            name = title_text.split(reference, 1)[-1].strip()
        else:
            parts = title_text.split(None, 2)
            name = parts[2] if len(parts) > 2 else title_text

    price = None
    price_el = soup.select_one(".product-block__price-new-wrap")
    if price_el:
        m = re.search(r"([\d\s]+[,.][\d]+)", price_el.get_text().replace("\xa0", " "))
        if m:
            price = float(m.group(1).replace(" ", "").replace(",", "."))

    return {"brand": brand, "reference": reference, "name": name, "price_eur": price, "ean": ean}


def _parse_specs(html: str) -> dict:
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    specs = {}
    for item in soup.select(".product-description__item"):
        t = item.select_one(".product-description__item-title")
        v = item.select_one(".product-description__item-value")
        if t and v:
            key = t.get_text(strip=True).rstrip(":")
            val = v.get_text(strip=True)
            if key and val:
                specs[key] = val
    return specs


def _parse_equivalents(html: str) -> list[dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    equivalents = []
    for card in soup.select(".product-card-grid"):
        name_el = card.select_one(".product-card-grid__product-name-span")
        ref_el = card.select_one(".product-card-grid__product-number > span")
        price_el = card.select_one(".product-card-grid__product-price")
        if not name_el:
            continue
        words = name_el.get_text(strip=True).split()
        brand = words[0] if words else ""
        if brand in _MULTI_FIRST and len(words) >= 2:
            two = f"{words[0]} {words[1]}"
            for mwb in MULTI_WORD_BRANDS:
                if mwb.upper().startswith(two.upper()):
                    brand = mwb
                    break
        reference = ""
        if ref_el:
            reference = ref_el.get_text(strip=True).replace("N\u00b0 de r\u00e9f\u00e9rence:", "").strip()
        entry = {"brand": brand, "reference": reference}
        if price_el:
            m = re.search(r"([\d\s]+[,.][\d]+)", price_el.get_text().replace("\xa0", " "))
            if m:
                entry["price_eur"] = float(m.group(1).replace(" ", "").replace(",", "."))
        equivalents.append(entry)
    return equivalents


def _parse_cross_references(html: str) -> list[dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    refs = []
    for row in soup.select(".product-similar-spec__row-item"):
        links = row.select(".product-similar-spec__row-link-item")
        if len(links) >= 2:
            refs.append({"brand": links[0].get_text(strip=True),
                         "reference": links[1].get_text(strip=True)})
    return refs


def _parse_oe_refs(oe_data: list[dict]) -> list[dict]:
    refs = []
    for g in oe_data:
        for ref in g.get("refs", []):
            refs.append({"brand": g["brand"], "reference": ref})
    return refs


def _parse_compatible_vehicles(html: str) -> list[dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    vehicles = []
    for brand_item in soup.select("[data-toggle-maker]"):
        brand_name = brand_item.get_text(strip=True)
        models = []
        ul = brand_item.find_next_sibling("ul")
        if ul:
            for li in ul.select("li"):
                t = li.select_one(".product-info-block__item-list__title")
                if t:
                    models.append(t.get_text(strip=True))
        vehicles.append({"brand": brand_name, "models": models})
    return vehicles


def _parse_compat_from_text(raw_text: str) -> list[dict]:
    """Fallback: parse compatible vehicles from raw section text.

    PA24 compatibility section text looks like:
        AUDI
        A4 Avant (8E5, B6) 1.9 TDI (116 CV) Diesel 2001 - 2004
        A4 Avant (8EC, B7) 2.0 TDI (140 CV) Diesel 2004 - 2008
        BMW
        Série 3 Berline (E46) ...
    """
    if not raw_text:
        return []
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    vehicles = []
    current_brand = None
    current_models = []

    for line in lines:
        # Brand line: all-caps or known brand, no digits (except "3" in "Série 3")
        # Heuristic: short line (<30 chars), mostly uppercase
        is_brand = (
            len(line) < 30
            and not any(c.isdigit() for c in line)
            and line == line.upper()
        )
        if is_brand:
            if current_brand and current_models:
                vehicles.append({"brand": current_brand, "models": current_models})
            current_brand = line
            current_models = []
        elif current_brand:
            current_models.append(line)

    if current_brand and current_models:
        vehicles.append({"brand": current_brand, "models": current_models})

    return vehicles


# ---------------------------------------------------------------------------
# Save to DB
# ---------------------------------------------------------------------------

def _parse_vehicle_name(name: str) -> Vehicle:
    """Parse a PA24 vehicle name string into a Vehicle object."""
    # Strip "(Année de construction ...)" suffix from PA24 compatibility strings
    clean = re.sub(r'\s*\(Année de construction[^)]*\)\s*$', '', name).strip()
    # Also strip "(Année de construction ..." without closing paren (truncated)
    clean = re.sub(r'\s*\(Année de construction.*$', '', clean).strip()
    parts = clean.split()
    brand = parts[0].upper() if parts else ""
    model = " ".join(parts[1:]) if len(parts) > 1 else ""
    return Vehicle(brand=brand, model=model, pa24_full_name=clean)


async def _save_to_db(data: dict, vehicle_name: str, part_name: str) -> str:
    """Save extracted PA24 data to the database. Returns detailed summary."""
    vehicle = _parse_vehicle_name(vehicle_name)
    vehicle_id = await upsert_vehicle(vehicle)

    ref_ids: list[int] = []

    # OE references
    oe_saved = []
    for r in data.get("oe_refs", []):
        if r.get("brand") and r.get("reference"):
            rid = await insert_reference(vehicle_id, part_name, r["brand"], r["reference"], True, source="oe")
            ref_ids.append(rid)
            oe_saved.append(r)

    # Main product
    product = data.get("product", {})
    if product.get("brand") and product.get("reference"):
        rid = await insert_reference(
            vehicle_id, part_name, product["brand"], product["reference"],
            False, product.get("price_eur"), source="main_product",
        )
        ref_ids.append(rid)

    # Equivalents
    eq_saved = []
    for eq in data.get("equivalents", []):
        if eq.get("brand") and eq.get("reference"):
            rid = await insert_reference(
                vehicle_id, part_name, eq["brand"], eq["reference"],
                False, eq.get("price_eur"), source="equivalent",
            )
            ref_ids.append(rid)
            eq_saved.append(eq)

    # Cross references
    xr_saved = []
    for xr in data.get("cross_refs", []):
        if xr.get("brand") and xr.get("reference"):
            rid = await insert_reference(
                vehicle_id, part_name, xr["brand"], xr["reference"],
                False, xr.get("price_eur"), source="cross_reference",
            )
            ref_ids.append(rid)
            xr_saved.append(xr)

    # Compatible vehicles
    compat = data.get("compatible_vehicles", [])
    for cv_group in compat:
        brand = cv_group.get("brand", "")
        for model_str in cv_group.get("models", []):
            compat_name = f"{brand} {model_str}".strip()
            for rid in ref_ids:
                await insert_compatibility(rid, compat_name)

    # Build detailed summary
    lines = [
        f"Scraping termine: {len(ref_ids)} references ajoutees",
        f"Vehicule: {vehicle_name}",
        f"Piece: {part_name}",
    ]

    # Main product
    if product.get("brand") and product.get("reference"):
        price_str = f" ({product['price_eur']:.2f} EUR)" if product.get("price_eur") else ""
        lines.append(f"\nProduit principal: {product['brand']} {product['reference']}{price_str}")

    # OE refs
    if oe_saved:
        lines.append(f"\nReferences OE ({len(oe_saved)}):")
        for r in oe_saved[:10]:
            lines.append(f"  {r['brand']} -- {r['reference']}")
        if len(oe_saved) > 10:
            lines.append(f"  ... +{len(oe_saved) - 10} autres")

    # Equivalents
    if eq_saved:
        lines.append(f"\nEquivalents ({len(eq_saved)}):")
        for eq in eq_saved[:10]:
            price_str = f" ({eq['price_eur']:.2f} EUR)" if eq.get("price_eur") else ""
            lines.append(f"  {eq['brand']} {eq['reference']}{price_str}")
        if len(eq_saved) > 10:
            lines.append(f"  ... +{len(eq_saved) - 10} autres")

    # Cross references
    if xr_saved:
        lines.append(f"\nCross-references ({len(xr_saved)}):")
        for xr in xr_saved[:10]:
            lines.append(f"  {xr['brand']} {xr['reference']}")
        if len(xr_saved) > 10:
            lines.append(f"  ... +{len(xr_saved) - 10} autres")

    # Compatible vehicles
    total_models = sum(len(cv.get("models", [])) for cv in compat)
    if compat:
        lines.append(f"\nVehicules compatibles ({len(compat)} marques, {total_models} modeles):")
        for cv in compat[:8]:
            brand = cv.get("brand", "?")
            model_count = len(cv.get("models", []))
            lines.append(f"  {brand} ({model_count} modeles)")
        if len(compat) > 8:
            lines.append(f"  ... +{len(compat) - 8} autres marques")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# database.json sync
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "database.json"


def _build_db_entry(vehicle_name: str, part_name: str, data: dict, source_url: str) -> dict:
    """Build one database.json entry matching the format seed.py expects."""
    product = data.get("product", {})

    # Build OE refs as comma-separated string in specs (seed.py reads from there)
    specs = dict(data.get("specs", {}))
    oe_refs = data.get("oe_refs", [])
    if oe_refs:
        oe_str = ", ".join(r["reference"] for r in oe_refs if r.get("reference"))
        if oe_str:
            specs["Similaires a des numeros OE"] = oe_str

    # Merge OE refs into cross_references too (they're separate brands)
    cross_refs = list(data.get("cross_refs", []))
    for r in oe_refs:
        if r.get("brand") and r.get("reference"):
            cross_refs.append({"brand": r["brand"], "reference": r["reference"]})

    return {
        "vehicle": _parse_vehicle_to_dict(vehicle_name),
        "part": part_name,
        "product": {
            "brand": product.get("brand", "").strip(),
            "reference": product.get("reference", "").strip(),
            "name": product.get("name", "").strip(),
        },
        "specs": specs,
        "equivalents": data.get("equivalents", []),
        "cross_references": cross_refs,
        "compatible_vehicles": data.get("compatible_vehicles", []),
        "source": "chatbot_scrape",
        "source_url": source_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _parse_vehicle_to_dict(vehicle_str: str) -> dict:
    """Parse a vehicle string into the structured dict format for database.json."""
    # Strip "(Année de construction ...)" suffix
    clean = re.sub(r'\s*\(Année de construction[^)]*\)\s*$', '', vehicle_str).strip()
    clean = re.sub(r'\s*\(Année de construction.*$', '', clean).strip()
    result = {
        "brand": "", "model_generation": "", "displacement": None,
        "cv": None, "fuel": "", "year_start": None, "year_end": None,
        "engine_code": "", "raw_vehicle": clean,
    }
    if not clean:
        return result

    parts = clean.split()
    raw_brand = parts[0]
    result["brand"] = BRAND_CASE.get(raw_brand.upper(), raw_brand)

    cv_match = re.search(r'(\d+)\s*CV\b', clean)
    if cv_match:
        result["cv"] = int(cv_match.group(1))

    for marker, fuel in FUEL_MARKERS.items():
        if marker in clean:
            result["fuel"] = fuel
            break

    year_match = re.search(r'(\d{4})\s*-\s*(\d{4}|\.\.\.)', clean)
    if year_match:
        result["year_start"] = int(year_match.group(1))
        result["year_end"] = int(year_match.group(2)) if year_match.group(2) != "..." else None

    # Model = everything between brand and first spec
    after_brand = clean[len(raw_brand):].strip()
    spec_start = len(after_brand)
    search_zone = clean[len(raw_brand):]
    if cv_match:
        search_zone = clean[len(raw_brand):cv_match.start()]
    disp_match = re.search(r'(\d+[.,]\d+)\s', search_zone)
    if disp_match:
        result["displacement"] = float(disp_match.group(1).replace(",", "."))
        pos = clean.find(disp_match.group(0), len(raw_brand))
        rel_pos = pos - len(raw_brand) - 1
        if 0 < rel_pos < spec_start:
            spec_start = rel_pos
    if cv_match:
        pos = clean.find(cv_match.group(0), len(raw_brand))
        rel_pos = pos - len(raw_brand) - 1
        if 0 < rel_pos < spec_start:
            spec_start = rel_pos
    result["model_generation"] = after_brand[:spec_start].strip()

    return result


def _append_to_database_json(entries: list[dict]) -> int:
    """Append entries to database.json, skipping duplicates. Returns count added."""
    existing = json.loads(DB_PATH.read_text(encoding="utf-8")) if DB_PATH.exists() else []
    existing_set = {
        (e.get("vehicle", {}).get("raw_vehicle", ""), e.get("part", ""))
        for e in existing
    }

    added = 0
    for entry in entries:
        key = (entry["vehicle"]["raw_vehicle"], entry["part"])
        if key not in existing_set:
            existing.append(entry)
            existing_set.add(key)
            added += 1

    if added:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DB_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, DB_PATH)
        log.info("database.json: +%d entries (%d total)", added, len(existing))

    return added


# ---------------------------------------------------------------------------
# Public API (called from ai_functions.py)
# ---------------------------------------------------------------------------

# Recent scrape results — prevents the LLM from re-scraping the same URL twice
_recent_scrapes: dict[str, tuple[float, str]] = {}  # {url: (timestamp, result)}
_SCRAPE_CACHE_TTL = 300  # 5 minutes


async def scrape_pa24_page(url: str) -> str:
    """Full pipeline: navigate to PA24 URL, extract HTML, parse, save to DB + database.json.

    Vehicle and part info are extracted from the PA24 page itself.
    One DB entry is created per compatible vehicle found on the page.
    Returns cached result if same URL was scraped in the last 5 minutes.
    """
    # Check cache — prevents double-scrape when LLM calls this twice
    now = time.time()
    cached = _recent_scrapes.get(url)
    if cached and now - cached[0] < _SCRAPE_CACHE_TTL:
        log.info("PA24 scrape cache hit for %s", url)
        return cached[1]

    log.info("Scraping PA24: %s", url)

    data = await extract_product_page(url)
    if not data:
        return "Echec de l'extraction PA24. La page est peut-etre protegee par Cloudflare ou le produit n'existe pas."

    product = data["product"]
    part_name = product.get("name", "").strip() or "piece"
    compat = data.get("compatible_vehicles", [])

    if compat:
        all_results = []
        db_entries = []
        for cv_group in compat:
            brand_name = cv_group.get("brand", "")
            for model_str in cv_group.get("models", []):
                vehicle_name = f"{brand_name} {model_str}".strip()
                if not vehicle_name:
                    continue
                result = await _save_to_db(data, vehicle_name, part_name)
                all_results.append(result)
                db_entries.append(_build_db_entry(vehicle_name, part_name, data, url))

        added = _append_to_database_json(db_entries)
        summary = (
            f"Scraping termine: {product.get('brand', '?')} {product.get('reference', '?')}\n"
            f"Piece: {part_name}\n"
            f"{len(db_entries)} vehicules traites"
        )
        if added:
            summary += f"\n+{added} entrees ajoutees a database.json"
        if all_results:
            summary += f"\n\n{all_results[-1]}"
    else:
        vehicle_name = f"{product.get('brand', '?')} {product.get('reference', '?')}"
        summary = await _save_to_db(data, vehicle_name, part_name)
        entry = _build_db_entry(vehicle_name, part_name, data, url)
        added = _append_to_database_json([entry])
        if added:
            summary += f"\n\n(+{added} entree ajoutee a database.json)"

    _recent_scrapes[url] = (time.time(), summary)
    return summary
