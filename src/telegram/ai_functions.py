"""Execute AI tool calls by mapping function names to DB/scraper operations."""

import json
import logging
import os

from src.db import repository as repo
from src.db.models import StoredReference
from src.part_aliases import resolve_part_name

import unicodedata

log = logging.getLogger(__name__)


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _clean_model_name(model: str) -> str:
    """Strip chassis codes, year ranges, and technical suffixes from model names.

    'Clio II 3/5 portes (BB, CB)' -> 'Clio II 3/5 portes'
    'Captur (J5_, H5_)' -> 'Captur'
    '208 I 3/5 portes (CA_, CC_)' -> '208 I 3/5 portes'
    """
    import re
    # Remove parenthesized chassis codes (letters, digits, underscores, commas, slashes, dots)
    clean = re.sub(r'\s*\([A-Za-z0-9_,./\s]+\)\s*', ' ', model).strip()
    # Remove trailing year ranges like "2012 - 2019"
    clean = re.sub(r'\s+\d{4}\s*-\s*(\d{4}|\.\.\.)\s*$', '', clean).strip()
    return clean


def _dedup_parts(parts: list[str]) -> list[str]:
    """Deduplicate part names that only differ by accents."""
    seen: dict[str, str] = {}  # normalized -> original
    for p in parts:
        key = _strip_accents(p).lower()
        if key not in seen:
            seen[key] = p
    return list(seen.values())

CDG_URL = os.environ.get("CDG_URL", "http://www.cdgros.com/Site_CDG25")


def _format_vehicle(v) -> str:
    """One-line vehicle summary."""
    parts = [v.brand, v.model]
    if v.displacement:
        parts.append(v.displacement)
    if v.fuel:
        parts.append(v.fuel.lower())
    if v.power_hp:
        parts.append(f"{v.power_hp}CV")
    if v.engine_code:
        parts.append(v.engine_code)
    return " ".join(parts)


def _format_refs(refs: list[StoredReference]) -> str:
    """Format a list of references into readable text."""
    if not refs:
        return "Aucune reference trouvee."

    grouped: dict[str, list[StoredReference]] = {
        "oe": [], "main_product": [], "equivalent": [], "cross_reference": [],
    }
    for r in refs:
        key = r.source if r.source in grouped else "equivalent"
        grouped[key].append(r)

    lines = []
    if grouped["oe"]:
        lines.append("OE:")
        for r in grouped["oe"]:
            price = f" ({r.price_eur:.2f} EUR)" if r.price_eur else ""
            lines.append(f"  {r.brand} -- {r.reference}{price}")

    if grouped["main_product"]:
        lines.append("Produit principal:")
        for r in grouped["main_product"]:
            price = f" ({r.price_eur:.2f} EUR)" if r.price_eur else ""
            lines.append(f"  {r.brand} -- {r.reference}{price}")

    if grouped["equivalent"]:
        lines.append("Equivalents:")
        for r in grouped["equivalent"]:
            price = f" ({r.price_eur:.2f} EUR)" if r.price_eur else ""
            lines.append(f"  {r.brand} -- {r.reference}{price}")

    if grouped["cross_reference"]:
        lines.append("Cross-references:")
        for r in grouped["cross_reference"]:
            price = f" ({r.price_eur:.2f} EUR)" if r.price_eur else ""
            lines.append(f"  {r.brand} -- {r.reference}{price}")

    lines.append(f"Total: {len(refs)} references.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Function implementations
# ---------------------------------------------------------------------------


async def list_brands(**_kwargs) -> str:
    brands = await repo.get_distinct_brands()
    if not brands:
        return "Aucune marque en base."
    choices = json.dumps(brands, ensure_ascii=False)
    return f"{len(brands)} marques en base:\nCHOICES:{choices}"


async def list_models(brand: str, **_kwargs) -> str:
    models = await repo.get_distinct_models(brand)
    if not models:
        return f"Aucun modele pour {brand}."
    clean = [_clean_model_name(m) for m in models]
    # Dedup after cleaning
    seen = set()
    unique = []
    for m in clean:
        key = m.lower()
        if key not in seen:
            seen.add(key)
            unique.append(m)
    choices = json.dumps(unique, ensure_ascii=False)
    return f"{brand} -- {len(unique)} modeles:\nCHOICES:{choices}"


async def list_engines(brand: str, model: str, fuel: str | None = None, **_kwargs) -> str:
    motors = await repo.get_motorisations(brand, model, fuel)
    if not motors:
        return f"Aucune motorisation pour {brand} {model}."
    engine_labels = []
    for m in motors:
        fuel_str = m["fuel"].lower() if m["fuel"] else ""
        label = f"{m['displacement']} {fuel_str} {m['power_hp']}CV".strip()
        if label not in engine_labels:
            engine_labels.append(label)
    choices = json.dumps(engine_labels, ensure_ascii=False)
    return f"{brand} {model} -- {len(engine_labels)} motorisations:\nCHOICES:{choices}"


async def search_parts(
    brand: str, model: str, part_name: str,
    fuel: str | None = None, power_hp: int | None = None, **_kwargs,
) -> str:
    original_name = part_name
    part_name = resolve_part_name(part_name)
    vehicles = await repo.search_vehicles_flexible(brand, model, fuel, power_hp)

    # Progressively relax constraints if no match
    if not vehicles and (fuel or power_hp):
        vehicles = await repo.search_vehicles_flexible(brand, model)

    if not vehicles:
        all_vehicles = await repo.get_vehicles_for_model(brand, model)
        if not all_vehicles:
            return f"Aucun vehicule {brand} {model} en base."
        lines = [f"Pas de {brand} {model}"]
        if power_hp:
            lines[0] += f" {power_hp}CV"
        if fuel:
            lines[0] += f" {fuel}"
        lines[0] += " en base."
        lines.append("Motorisations disponibles:")
        seen = set()
        for v in all_vehicles:
            key = (v.displacement, v.fuel, v.power_hp)
            if key not in seen:
                seen.add(key)
                lines.append(f"  {_format_vehicle(v)}")
        return "\n".join(lines)

    vehicle_ids = [v.id for v in vehicles]
    refs = await repo.lookup_references_multi(vehicle_ids, part_name)

    # If alias resolution changed the name and got no results, try the original
    if not refs and original_name.lower() != part_name.lower():
        refs = await repo.lookup_references_multi(vehicle_ids, original_name)
        if refs:
            part_name = original_name

    if not refs:
        # Try fuzzy part name matching
        parts = _dedup_parts(await repo.search_parts_fuzzy_multi(vehicle_ids, part_name))
        if parts:
            choices = json.dumps(parts[:10], ensure_ascii=False)
            return (
                f"{brand} {model} -- '{part_name}' non trouve.\n"
                f"Pieces similaires:\nCHOICES:{choices}"
            )
        all_parts = _dedup_parts(await repo.get_parts_for_vehicles(vehicle_ids))
        if all_parts:
            choices = json.dumps(all_parts[:15], ensure_ascii=False)
            return (
                f"{brand} {model} -- '{part_name}' non disponible en base.\n"
                f"Pieces en base ({len(all_parts)}):\nCHOICES:{choices}"
            )
        return f"Aucune reference pour {brand} {model} -- {part_name}."

    header = f"{brand} {model} -- {part_name}\n"
    return header + _format_refs(refs)


async def search_by_reference(reference: str, **_kwargs) -> str:
    rows = await repo.search_reference_in_db(reference)
    if not rows:
        return f"Reference {reference.upper()} non trouvee en base."

    r = rows[0]
    lines = [
        f"Reference: {r['brand']} {r['reference']}",
        f"Piece: {r['part_name']}",
        f"Source: {r['source']}",
    ]
    if r["price_eur"]:
        lines.append(f"Prix: {r['price_eur']:.2f} EUR")

    # List vehicles that have this ref
    vehicle_names = set()
    for row in rows:
        vehicle_names.add(f"{row['v_brand']} {row['v_model']} {row['displacement'] or ''} "
                         f"{(row['fuel'] or '').lower()} {row['power_hp'] or ''}CV".strip())

    lines.append(f"\nVehicules en base ({len(vehicle_names)}):")
    for vn in sorted(vehicle_names)[:10]:
        lines.append(f"  {vn}")

    compat = await repo.get_compatible_vehicles_for_ref(reference)
    if compat:
        lines.append(f"\nVehicules compatibles ({len(compat)}):")
        for c in compat[:10]:
            lines.append(f"  {c}")
        if len(compat) > 10:
            lines.append(f"  ... et {len(compat) - 10} autres")

    return "\n".join(lines)


async def get_coverage(
    brand: str, model: str,
    fuel: str | None = None, power_hp: int | None = None, **_kwargs,
) -> str:
    vehicles = await repo.search_vehicles_flexible(brand, model, fuel, power_hp)
    if not vehicles:
        return f"Aucun vehicule {brand} {model} en base."

    vehicle_ids = [v.id for v in vehicles]
    coverage = await repo.get_coverage_for_vehicle(vehicle_ids)

    if not coverage:
        return f"{brand} {model} -- Aucune piece en base."

    part_names = _dedup_parts([c["part_name"] for c in coverage])
    choices = json.dumps(part_names, ensure_ascii=False)
    return f"{brand} {model} -- {len(part_names)} pieces en base:\nCHOICES:{choices}"


async def get_compatible_vehicles(reference: str, **_kwargs) -> str:
    compat = await repo.get_compatible_vehicles_for_ref(reference)
    rows = await repo.search_reference_in_db(reference)

    if not compat and not rows:
        return f"Reference {reference.upper()} non trouvee en base."

    lines = [f"Vehicules compatibles avec {reference.upper()}:"]

    if rows:
        vehicle_names = set()
        for r in rows:
            vehicle_names.add(f"{r['v_brand']} {r['v_model']} {r['displacement'] or ''} "
                             f"{(r['fuel'] or '').lower()} {r['power_hp'] or ''}CV".strip())
        lines.append(f"\nEn base ({len(vehicle_names)}):")
        for vn in sorted(vehicle_names):
            lines.append(f"  {vn}")

    if compat:
        lines.append(f"\nCompatibilite declaree ({len(compat)}):")
        for c in compat[:20]:
            lines.append(f"  {c}")
        if len(compat) > 20:
            lines.append(f"  ... et {len(compat) - 20} autres")

    return "\n".join(lines)


async def compare_vehicles(vehicle1: str, vehicle2: str, part_name: str, **_kwargs) -> str:
    """Check if two vehicles share references for a part."""
    # Search vehicles by description text
    from src.db.repository import get_all_vehicles
    all_v = await get_all_vehicles()

    def find_vehicle(desc: str):
        desc_lower = desc.lower()
        for v in all_v:
            if desc_lower in v.pa24_full_name.lower() or desc_lower in _format_vehicle(v).lower():
                return v
        return None

    v1 = find_vehicle(vehicle1)
    v2 = find_vehicle(vehicle2)

    if not v1:
        return f"Vehicule '{vehicle1}' non trouve en base."
    if not v2:
        return f"Vehicule '{vehicle2}' non trouve en base."

    refs1 = await repo.lookup_references(v1.id, part_name)
    refs2 = await repo.lookup_references(v2.id, part_name)

    if not refs1 and not refs2:
        return f"Aucune reference pour '{part_name}' sur aucun des deux vehicules."

    codes1 = {r.reference.upper() for r in refs1}
    codes2 = {r.reference.upper() for r in refs2}
    common = codes1 & codes2

    lines = [f"Comparaison -- {part_name}:"]
    lines.append(f"  {_format_vehicle(v1)}: {len(refs1)} refs")
    lines.append(f"  {_format_vehicle(v2)}: {len(refs2)} refs")
    lines.append(f"  References communes: {len(common)}")

    if common:
        lines.append("  Refs partagees: " + ", ".join(sorted(common)[:10]))

    only1 = codes1 - codes2
    only2 = codes2 - codes1
    if only1:
        lines.append(f"  Uniquement {_format_vehicle(v1)}: {', '.join(sorted(only1)[:5])}")
    if only2:
        lines.append(f"  Uniquement {_format_vehicle(v2)}: {', '.join(sorted(only2)[:5])}")

    return "\n".join(lines)


async def identify_vehicle(query: str, **_kwargs) -> str:
    """Identify vehicle from VIN or text description."""
    query = query.strip()

    # Check if it looks like a VIN (17 alphanumeric chars)
    if len(query) == 17 and query.isalnum():
        from src.vin.decoder import decode_vin
        info = await decode_vin(query.upper())
        lines = [f"VIN: {query.upper()}"]
        if info.make:
            lines.append(f"Marque: {info.make}")
        if info.model:
            lines.append(f"Modele: {info.model}")
        if info.year:
            lines.append(f"Annee: {info.year}")
        if info.engine:
            lines.append(f"Moteur: {info.engine}")
        if info.vehicle_id:
            lines.append(f"Vehicle ID en base: {info.vehicle_id}")
        if info.pa24_full_name:
            lines.append(f"PA24: {info.pa24_full_name}")
        lines.append(f"Confiance: {info.confidence.value}")
        if info.explanation:
            lines.append("Details: " + " | ".join(info.explanation))
        return "\n".join(lines)

    # Text description: search in vehicles
    all_v = await repo.get_all_vehicles()
    query_lower = query.lower()
    matches = []
    for v in all_v:
        desc = _format_vehicle(v).lower()
        if all(word in desc for word in query_lower.split()):
            matches.append(v)

    if not matches:
        return f"Aucun vehicule correspondant a '{query}'."

    if len(matches) <= 5:
        lines = [f"Vehicules correspondant a '{query}':"]
        for v in matches:
            lines.append(f"  [ID {v.id}] {_format_vehicle(v)}")
        return "\n".join(lines)

    return f"{len(matches)} vehicules correspondant a '{query}'. Precisez le modele ou la motorisation."


async def search_cdg(
    reference: str | None = None,
    vehicle_id: int | None = None,
    part_name: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    **_kwargs,
) -> str:
    """Search CDG by reference, by part name, or both with fallbacks."""
    from src.chain import get_scraper

    if part_name:
        part_name = resolve_part_name(part_name)

    # Resolve vehicle_ids from brand+model
    _vehicle_ids = []
    if not vehicle_id and brand and model:
        vehicles = await repo.search_vehicles_flexible(brand, model)
        _vehicle_ids = [v.id for v in vehicles]
        if _vehicle_ids:
            vehicle_id = _vehicle_ids[0]

    try:
        scraper = await get_scraper()
    except Exception as e:
        log.error("CDG scraper error: %s", e)
        return f"Erreur CDG: {e}"

    # Direct reference search
    if reference:
        try:
            results = await scraper.search(reference.upper())
        except Exception as e:
            log.error("CDG search error: %s", e)
            return f"Erreur CDG: {e}"

        if results:
            return _format_cdg(f"CDG -- {reference.upper()}:", results)

        # Fallback 1: try other refs for same vehicle+part
        if part_name and (vehicle_id or _vehicle_ids):
            lookup_ids = _vehicle_ids if _vehicle_ids else [vehicle_id]
            all_refs_fb1 = await repo.lookup_references_multi(lookup_ids, part_name)
            other_refs = [r for r in all_refs_fb1 if r.reference.upper() != reference.upper()]
            for ref in other_refs:
                try:
                    results = await scraper.search(ref.reference)
                except Exception:
                    continue
                if results:
                    return _format_cdg(
                        f"{reference.upper()} non trouvee chez CDG.\n"
                        f"Resultat via {ref.brand} {ref.reference}:",
                        results,
                    )

    # Fallback 2 / direct designation search: by part name + OE cross-reference
    if part_name and (vehicle_id or _vehicle_ids):
        # Use multi-vehicle lookup to find OE refs across all matching vehicles
        lookup_ids = _vehicle_ids if _vehicle_ids else [vehicle_id]
        all_refs = await repo.lookup_references_multi(lookup_ids, part_name)
        oe_refs = list({r.reference for r in all_refs if r.is_oe})

        if oe_refs:
            try:
                desig_hits = await scraper.search_designation_fallback(part_name, oe_refs)
                if desig_hits:
                    header = f"Resultat CDG via recherche designation '{part_name}':"
                    if reference:
                        header = f"{reference.upper()} non trouvee chez CDG.\n{header}"
                    return _format_cdg(header, desig_hits)
            except Exception as e:
                log.error("CDG designation fallback error: %s", e)

        # Fallback 3: try searching each OE ref directly
        for oe_ref in oe_refs[:5]:
            try:
                results = await scraper.search(oe_ref)
            except Exception:
                continue
            if results:
                header = f"Resultat CDG via reference OE {oe_ref}:"
                if reference:
                    header = f"{reference.upper()} non trouvee chez CDG.\n{header}"
                return _format_cdg(header, results)

    if reference:
        return f"{reference.upper()} non trouvee chez CDG."
    return "Aucun resultat CDG. Precisez une reference ou un vehicule+piece."


def _format_cdg(header: str, results: list) -> str:
    """Format CDG results into text."""
    available = [r for r in results if r.available]
    rupture = [r for r in results if not r.available]
    lines = [header]
    if available:
        lines.append("Disponible:")
        for r in available:
            price_str = f"{r.price:.3f} TND" if r.price else "prix N/A"
            lines.append(f"  {r.reference} {r.description} -- {price_str}")
    if rupture:
        lines.append("Rupture:")
        for r in rupture:
            lines.append(f"  {r.reference} {r.description}")
    return "\n".join(lines)


async def get_db_stats(**_kwargs) -> str:
    stats = await repo.get_stats()
    return (
        f"Vehicules: {stats['vehicles']}\n"
        f"References: {stats['references']}\n"
        f"Patterns VIN: {stats['vin_patterns']}\n"
        f"Requetes aujourd'hui: {stats['requests_today']}"
    )


async def get_pa24_link(reference: str | None = None, query: str | None = None, **_kwargs) -> str:
    base = "https://www.piecesauto24.com"
    if reference:
        return f"Lien PA24: {base}/recherche?q={reference}"
    if query:
        return f"Lien PA24: {base}/recherche?q={query.replace(' ', '+')}"
    return f"Lien PA24: {base}"


async def get_cdg_link(reference: str, **_kwargs) -> str:
    return f"Lien CDG: {CDG_URL} (chercher {reference.upper()} dans le catalogue)"


async def propose_pa24_add(
    reference: str | None = None,
    brand: str | None = None, model: str | None = None, part_name: str | None = None,
    vehicle_name: str | None = None,
    **_kwargs,
) -> str:
    """Search PA24 and show preview. Does NOT save to DB — waits for user confirmation.

    Two modes:
    A) By reference: search PA24 directly with the reference code.
    B) By vehicle+part: first validate vehicle from DB (returns CHOICES),
       then search PA24 with the validated PA24 vehicle name + part name.
       Pass vehicle_name (from CHOICES) to skip validation and search directly.
    """
    from src.scraper.pa24 import search_pa24, _extracted_cache

    # Mode A: direct reference search
    if reference:
        return await _pa24_search_and_preview(reference)

    # Mode B: vehicle + part search
    if not brand and not model and not part_name and not vehicle_name:
        return "Pas de reference ni de piece a chercher."

    # If vehicle_name already validated, search PA24 directly
    if vehicle_name and part_name:
        query = f"{vehicle_name} {part_name}"
        return await _pa24_search_and_preview(query)

    # Need to validate vehicle first — show motorisation choices from DB
    if brand and model:
        if part_name:
            part_name = resolve_part_name(part_name)

        vehicles = await repo.search_vehicles_flexible(brand, model)
        if not vehicles:
            return f"Aucun vehicule {brand} {model} en base. Essayez avec une reference directe."

        # Group by motorisation (displacement, fuel, power_hp)
        seen: dict[tuple, str] = {}
        for v in vehicles:
            key = (v.displacement, v.fuel, v.power_hp)
            if key not in seen:
                label = _clean_model_name(v.model)
                parts = [brand, label]
                if v.displacement:
                    parts.append(str(v.displacement))
                if v.fuel:
                    parts.append(v.fuel.lower())
                if v.power_hp:
                    parts.append(f"{v.power_hp}CV")
                seen[key] = " ".join(parts)

        motorisations = list(seen.values())
        if len(motorisations) == 1:
            # Single motorisation — search PA24 directly
            query = motorisations[0]
            if part_name:
                query += f" {part_name}"
            return await _pa24_search_and_preview(query)

        choices = json.dumps(motorisations[:15], ensure_ascii=False)
        msg = f"Choisissez la motorisation pour la recherche PA24:"
        if part_name:
            msg = f"Piece: {part_name}\n{msg}"
        return f"{msg}\nCHOICES:{choices}"

    return "Precisez au moins la marque et le modele."


async def _pa24_search_and_preview(query: str) -> str:
    """Search PA24 with query, extract data, return preview."""
    from src.scraper.pa24 import search_pa24, _extracted_cache

    try:
        url = await search_pa24(query)
    except Exception as e:
        log.error("PA24 search error: %s", e)
        return f"Erreur lors de la recherche PA24: {e}"

    if not url:
        search_url = f"https://www.piecesauto24.com/rechercher?keyword={query.replace(' ', '+')}"
        return (
            f"Aucun resultat trouve sur PA24 pour '{query}'.\n"
            f"Lien de recherche: {search_url}\n"
            "Verifiez manuellement ou essayez avec une reference differente."
        )

    cached = _extracted_cache.get(url)
    if not cached:
        return f"Produit trouve: {url}\nMais pas de donnees extraites. Voulez-vous reessayer?"

    _, data = cached
    product = data.get("product", {})
    oe_refs = data.get("oe_refs", [])
    equivalents = data.get("equivalents", [])
    cross_refs = data.get("cross_refs", [])
    compat = data.get("compatible_vehicles", [])
    total_models = sum(len(cv.get("models", [])) for cv in compat)

    lines = [
        f"Produit trouve sur PA24: {url}",
        "",
        f"Produit: {product.get('brand', '?')} {product.get('reference', '?')}",
        f"Nom: {product.get('name', '?')}",
    ]
    if product.get("price_eur"):
        lines.append(f"Prix: {product['price_eur']:.2f} EUR")
    lines.append(f"References OE: {len(oe_refs)}")
    lines.append(f"Equivalents: {len(equivalents)}")
    lines.append(f"Cross-references: {len(cross_refs)}")
    lines.append(f"Vehicules compatibles: {len(compat)} marques, {total_models} modeles")

    if compat:
        lines.append("")
        for cv in compat[:5]:
            lines.append(f"  {cv.get('brand', '?')} ({len(cv.get('models', []))} modeles)")
        if len(compat) > 5:
            lines.append(f"  ... +{len(compat) - 5} autres marques")

    lines.append("")
    lines.append("Voulez-vous sauvegarder ces donnees en base?")

    return "\n".join(lines)


async def confirm_pa24_add(url: str, **_kwargs) -> str:
    """Save previously extracted PA24 data to DB + database.json.

    Uses cached extraction from propose_pa24_add.
    """
    from src.scraper.pa24 import scrape_pa24_page

    try:
        result = await scrape_pa24_page(url)
        return result
    except Exception as e:
        log.error("PA24 save error: %s", e)
        return f"Erreur lors de la sauvegarde: {e}"


# ---------------------------------------------------------------------------
# Dispatcher: function name -> handler
# ---------------------------------------------------------------------------

FUNCTION_MAP = {
    "list_brands": list_brands,
    "list_models": list_models,
    "list_engines": list_engines,
    "search_parts": search_parts,
    "search_by_reference": search_by_reference,
    "get_coverage": get_coverage,
    "get_compatible_vehicles": get_compatible_vehicles,
    "compare_vehicles": compare_vehicles,
    "identify_vehicle": identify_vehicle,
    "search_cdg": search_cdg,
    "get_db_stats": get_db_stats,
    "get_pa24_link": get_pa24_link,
    "get_cdg_link": get_cdg_link,
    "propose_pa24_add": propose_pa24_add,
    "confirm_pa24_add": confirm_pa24_add,
}


async def execute_tool_call(name: str, arguments: dict) -> str:
    """Execute a tool call by name. Returns the result string."""
    fn = FUNCTION_MAP.get(name)
    if not fn:
        return f"Fonction inconnue: {name}"
    try:
        return await fn(**arguments)
    except Exception as e:
        log.error("Tool call %s failed: %s", name, e)
        return f"Erreur: {e}"
