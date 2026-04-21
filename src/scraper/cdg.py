"""CDG wholesaler portal scraper using Playwright."""

import asyncio
import logging
import os
import re
import unicodedata

from playwright.async_api import async_playwright
from dotenv import load_dotenv

from src.db.models import CDGResult

load_dotenv()

log = logging.getLogger(__name__)

CDG_URL = os.environ.get("CDG_URL", "http://www.cdgros.com/Site_CDG25")


def _normalize_for_cdg(ref: str) -> str:
    """Strip separators (spaces, dashes, dots, slashes) for CDG search.

    Same characters in same order — only formatting removed.
    "560 118" -> "560118", "FAE-77134" -> "FAE77134"
    """
    return ref.replace(" ", "").replace("-", "").replace(".", "").replace("/", "").strip()


def _normalize_ref(ref: str) -> str:
    """Normalize a reference for comparison. Same as _normalize_for_cdg but uppercased."""
    return _normalize_for_cdg(ref).upper()


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


# Common filler words to strip when building fuzzy search variants
_FILLER = {"de", "du", "des", "le", "la", "les", "a", "au", "aux", "en", "et", "d"}


def _fuzzy_part_names(part_name: str) -> list[str]:
    """Generate search variants for a part name.

    Uses alias table first, then fuzzy fallbacks:
    1. All known aliases for the part (from PART_ALIASES)
    2. Original (stripped accents, uppercased)
    3. Without filler words ("Kit de distribution" -> "KIT DISTRIBUTION")
    4. First meaningful word only ("Amortisseur" from "Amortisseur avant")
    """
    from src.part_aliases import get_cdg_variants

    # Start with alias variants (includes the standard name)
    alias_variants = get_cdg_variants(part_name)

    clean = _strip_accents(part_name).upper().strip()
    variants = list(alias_variants)
    if clean not in variants:
        variants.append(clean)

    # Without fillers
    words = clean.split()
    meaningful = [w for w in words if w.lower() not in _FILLER and len(w) > 1]
    no_filler = " ".join(meaningful)
    if meaningful and no_filler not in variants:
        variants.append(no_filler)

    # First word only (if multi-word)
    if len(meaningful) > 1 and meaningful[0] not in variants:
        variants.append(meaningful[0])

    return variants


CDG_LOGIN = os.environ.get("CDG_LOGIN", "")
CDG_PASSWORD = os.environ.get("CDG_PASSWORD", "")


class CDGScraper:
    """Scrapes the CDG wholesaler portal for part availability and pricing."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Launch browser and login to CDG."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        await self._login()

    async def _login(self):
        """Login to CDG portal."""
        log.info("Navigating to %s", CDG_URL)
        await self._page.goto(CDG_URL, wait_until="networkidle", timeout=60000)

        await self._page.locator("#A8").click()
        await self._page.keyboard.type(CDG_LOGIN)
        await self._page.keyboard.press("Tab")
        await self._page.keyboard.type(CDG_PASSWORD)
        await self._page.keyboard.press("Enter")

        await self._page.wait_for_timeout(5000)
        title = await self._page.title()
        log.info("After login - Title: %s", title)
        if "Login" in title:
            raise RuntimeError("Login failed — still on login page")

    async def _ensure_session(self):
        """Re-login if session has expired."""
        title = await self._page.title()
        if "Login" in title:
            log.warning("CDG session expired, re-logging in")
            await self._login()

    async def search(self, reference: str) -> list[CDGResult]:
        """Search for a single reference. Serialized via lock.

        Tries normalized form first (no spaces/dashes/dots), then original
        if different and first attempt returned nothing.
        """
        normalized = _normalize_for_cdg(reference)
        results = await self._search_once(normalized)
        if not results and normalized != reference:
            results = await self._search_once(reference)
        return results

    async def _search_once(self, reference: str) -> list[CDGResult]:
        """Single CDG search attempt for a reference string."""
        async with self._lock:
            await self._ensure_session()

            search_field = self._page.locator("#A20")
            await search_field.click()
            await search_field.fill("")
            await self._page.keyboard.type(reference)
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_timeout(4000)

            title = await self._page.title()
            if "Login" in title:
                log.warning("CDG session expired during search, re-logging in")
                await self._login()
                search_field = self._page.locator("#A20")
                await search_field.click()
                await search_field.fill("")
                await self._page.keyboard.type(reference)
                await self._page.keyboard.press("Enter")
                await self._page.wait_for_timeout(4000)

            has_equiv = await self._expand_equivalents()
            results = await self._parse_results()

            if has_equiv:
                await self._go_to_catalog()

            return results

    async def _expand_equivalents(self) -> bool:
        """Click the equivalents count button to show all equivalent refs."""
        try:
            btn_info = await self._page.evaluate(r"""() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const text = b.textContent.trim();
                    if (/^\d{1,3}$/.test(text) && parseInt(text) > 0 && b.id) {
                        return {id: b.id};
                    }
                }
                return null;
            }""")
            if btn_info:
                await self._page.locator(f"#{btn_info['id']}").click()
                await self._page.wait_for_timeout(4000)
                return True
        except Exception as e:
            log.debug("No equiv button or click failed: %s", e)
        return False

    async def _go_to_catalog(self):
        """Navigate back to catalog page (needed after expanding equivalents)."""
        try:
            cat_link = self._page.locator("text=Catalogue").first
            if await cat_link.count() > 0:
                await cat_link.click()
                await self._page.wait_for_timeout(3000)
        except Exception as e:
            log.debug("Could not navigate to catalog: %s", e)

    async def screenshot(self, path: str):
        """Take a screenshot of the current page."""
        async with self._lock:
            await self._page.screenshot(path=path, full_page=True)

    async def _parse_results(self) -> list[CDGResult]:
        """Parse results from page inner text.

        Page text structure per result row:
            Prix HT
            Quantite           <- only present if available
            Reference
            REFCODE
            DESCRIPTION
            NUMBER             <- equivalent count link (ignore)
        """
        body = await self._page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]

        # Extract prices from inputs near "Prix HT" labels in each row
        prices = await self._page.evaluate("""() => {
            const vals = [];
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                if (el.children.length === 0 && el.textContent.trim() === 'Prix HT') {
                    const parent = el.closest('div[style*="position"]') || el.parentElement?.parentElement;
                    if (!parent) continue;
                    const row = parent.parentElement;
                    if (!row) continue;
                    const inputs = row.querySelectorAll('input[type="text"]');
                    for (const inp of inputs) {
                        const v = inp.value.trim().replace(/\\s/g, '');
                        if (/^\\d+[,.]\\d{2,3}$/.test(v)) {
                            vals.push(parseFloat(v.replace(',', '.')));
                            break;
                        }
                    }
                }
            }
            return vals;
        }""")

        results = []
        price_idx = 0
        i = 0
        while i < len(lines):
            if lines[i] in ("Référence", "Reference") and i + 2 < len(lines):
                ref = lines[i + 1]
                desc = lines[i + 2]

                if ref in ("Prix HT", "Quantité", ""):
                    i += 1
                    continue

                available = i > 0 and lines[i - 1] == "Quantité"

                if available:
                    price = prices[price_idx] if price_idx < len(prices) else None
                    price_idx += 1
                else:
                    price = None

                results.append(CDGResult(
                    reference=ref,
                    brand="",
                    description=desc,
                    price=price,
                    available=available,
                ))
                i += 3
            else:
                i += 1

        return results

    async def search_all(self, references: list[str]) -> dict[str, list[CDGResult]]:
        """Search all references, return {ref: [CDGResult]} for each."""
        results = {}
        for ref in references:
            results[ref] = await self.search(ref)
        return results

    async def search_designation(self, designation: str) -> list[CDGResult]:
        """Search CDG by part name (designation field #A33).

        Returns all results found — caller cross-references against known OE refs.
        """
        async with self._lock:
            await self._ensure_session()

            search_field = self._page.locator("#A33")
            await search_field.click()
            await search_field.fill("")
            await self._page.keyboard.type(designation)
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_timeout(4000)

            title = await self._page.title()
            if "Login" in title:
                log.warning("CDG session expired during designation search, re-logging in")
                await self._login()
                search_field = self._page.locator("#A33")
                await search_field.click()
                await search_field.fill("")
                await self._page.keyboard.type(designation)
                await self._page.keyboard.press("Enter")
                await self._page.wait_for_timeout(4000)

            results = await self._parse_results()
            log.info("CDG designation '%s': %d results", designation, len(results))
            return results

    async def search_designation_fallback(
        self, part_name: str, oe_refs: list[str],
    ) -> list[CDGResult]:
        """Search CDG by part name, then filter results that match our OE refs.

        Tries fuzzy variants of the part name. For each CDG result, checks if
        the description contains any of our OE refs (normalized).
        """
        if not oe_refs:
            return []

        # Build normalized OE ref set for matching
        oe_norm = {_normalize_ref(r) for r in oe_refs}

        variants = _fuzzy_part_names(part_name)
        log.info("CDG designation fallback for '%s', variants: %s, %d OE refs",
                 part_name, variants, len(oe_refs))

        for variant in variants:
            all_results = await self.search_designation(variant)
            if not all_results:
                continue

            # Check each result: does its description contain one of our OE refs?
            matched = []
            for r in all_results:
                embedded = _extract_embedded_refs(r.description)
                for emb in embedded:
                    if _normalize_ref(emb) in oe_norm:
                        log.info("CDG designation match: %s desc has OE '%s'",
                                 r.reference, emb)
                        matched.append(r)
                        break

            if matched:
                return matched

        return []

    async def close(self):
        """Close browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


def _extract_embedded_refs(description: str) -> list[str]:
    """Extract reference codes embedded in CDG descriptions.

    CDG descriptions like "SONDE LAMBDA A4 PASS 032906265" contain OE refs.
    Match codes that are 6+ chars with at least some digits.
    """
    refs = []
    for token in description.split():
        clean = token.strip(".,;()")
        if len(clean) < 5:
            continue
        has_digit = any(c.isdigit() for c in clean)
        if has_digit and clean.replace("-", "").replace(".", "").isalnum():
            refs.append(clean)
    return refs
