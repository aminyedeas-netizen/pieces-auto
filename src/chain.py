"""Orchestrates: vehicle+part -> DB refs -> CDG search -> format results."""

import logging

from src.db.models import CDGResult, StoredReference
from src.scraper.cdg import CDGScraper
from src.scraper.catalog_cache import filter_searchable, is_known_not_found

log = logging.getLogger(__name__)

# Singleton scraper
_scraper: CDGScraper | None = None

# Reference to operator bot app (set at startup)
_operator_app = None
_operator_chat_id: int | None = None


def set_operator_app(app, chat_id: int):
    global _operator_app, _operator_chat_id
    _operator_app = app
    _operator_chat_id = chat_id


async def get_scraper() -> CDGScraper:
    global _scraper
    if _scraper is None:
        _scraper = CDGScraper()
        await _scraper.start()
    return _scraper


async def close_scraper() -> None:
    global _scraper
    if _scraper:
        await _scraper.close()
        _scraper = None


async def search_reference(reference: str) -> str:
    """Search a single reference directly on CDG. No vehicle needed."""
    if is_known_not_found(reference):
        log.info("Cache short-circuit: %s known not on CDG", reference)
        return (
            f"\U0001F50D *Reference : {_escape_md(reference)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\u274C Cette reference n'est pas distribuee par CDG\\."
        )

    try:
        scraper = await get_scraper()
        results = await scraper.search(reference)
    except Exception as e:
        log.error("CDG scraper error: %s", e)
        results = []

    if not results:
        return (
            f"\U0001F50D *Reference : {_escape_md(reference)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\u26A0\uFE0F Non trouvee chez CDG\\."
        )

    available = [r for r in results if r.available]
    rupture = [r for r in results if not r.available]

    lines = [
        f"\U0001F50D *Reference : {_escape_md(reference)}*",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
    ]

    if available:
        lines.append("\u2705 *En stock :*")
        for r in available:
            price_str = f"\U0001F4B0 *{_escape_md(f'{r.price:.3f} TND')}*" if r.price else "prix N/A"
            desc = _escape_md(f"{r.reference} {r.description}".strip())
            lines.append(f"  \u2022 {desc} \u2014 {price_str}")
        lines.append("")

    if rupture:
        lines.append("\u274C *Rupture :*")
        for r in rupture:
            desc = _escape_md(f"{r.reference} {r.description}".strip())
            lines.append(f"  \u2022 {desc}")
        lines.append("")

    return "\n".join(lines)


async def search_part(vehicle_id: int | list[int], vehicle_name: str, part_name: str) -> str:
    """Full chain: DB lookup -> CDG search all refs -> formatted result.

    vehicle_id can be a single int or a list of ints (grouped motorisations).
    """
    if isinstance(vehicle_id, list):
        from src.db.repository import lookup_references_multi
        refs = await lookup_references_multi(vehicle_id, part_name)
    else:
        from src.db.repository import lookup_references
        refs = await lookup_references(vehicle_id, part_name)

    if not refs:
        await _notify_operator_refs_missing(vehicle_name, part_name)
        return (
            f"\U0001F697 *{_escape_md(vehicle_name)}*\n"
            f"\U0001F527 *{_escape_md(part_name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\u26A0\uFE0F Nous recherchons cette piece pour vous\\.\n"
            "Vous recevrez une notification des que disponible\\."
        )

    # Cache short-circuit: drop refs already proven not on CDG
    ref_codes = [r.reference for r in refs]
    oe_codes = {r.reference for r in refs if r.is_oe}
    to_search, known_not_found = filter_searchable(ref_codes)
    if known_not_found:
        log.info(
            "Cache filtered %d/%d refs for %s / %s",
            len(known_not_found), len(ref_codes), vehicle_name, part_name,
        )

    if not to_search:
        # Every ref was previously proven absent from CDG.
        await _notify_operator_cdg_unavailable(vehicle_name, part_name, ref_codes)
        return (
            f"\U0001F697 *{_escape_md(vehicle_name)}*\n"
            f"\U0001F527 *{_escape_md(part_name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\u274C Cette piece n'est pas distribuee par CDG\\.\n"
            "Nous vous notifierons des qu'elle sera disponible\\."
        )

    try:
        scraper = await get_scraper()
        all_results = await scraper.search_all(to_search)
    except Exception as e:
        log.error("CDG scraper error: %s", e)
        all_results = {}

    # Classify live results
    available: list[CDGResult] = []
    rupture: list[CDGResult] = []
    not_found: list[str] = list(known_not_found)
    oe_hit = False
    equiv_hit = False

    for ref_code in to_search:
        cdg_hits = all_results.get(ref_code, [])
        if not cdg_hits:
            not_found.append(ref_code)
            continue
        is_oe_ref = ref_code in oe_codes
        for hit in cdg_hits:
            if hit.available:
                available.append(hit)
            else:
                rupture.append(hit)
            if is_oe_ref:
                oe_hit = True
            else:
                equiv_hit = True

    if not available and not rupture:
        await _notify_operator_cdg_unavailable(vehicle_name, part_name, ref_codes)
        return (
            f"\U0001F697 *{_escape_md(vehicle_name)}*\n"
            f"\U0001F527 *{_escape_md(part_name)}*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\u274C Piece non disponible actuellement\\.\n"
            "Nous vous notifierons des qu'elle sera en stock\\."
        )

    equivalent_only = equiv_hit and not oe_hit and bool(oe_codes)
    return _format_cdg_results(
        vehicle_name, part_name, available, rupture, not_found,
        equivalent_only=equivalent_only,
    )


def _format_cdg_results(
    vehicle_name: str, part_name: str,
    available: list[CDGResult], rupture: list[CDGResult],
    not_found: list[str],
    equivalent_only: bool = False,
) -> str:
    """Format CDG results for Telegram MarkdownV2."""
    lines = [
        f"\U0001F697 *{_escape_md(vehicle_name)}*",
        f"\U0001F527 *{_escape_md(part_name)}*",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
    ]

    if equivalent_only:
        lines.append(
            "\u2139\uFE0F *Piece d'origine non disponible chez CDG\\.*"
        )
        lines.append(
            "Nous avons trouve un equivalent compatible :"
        )
        lines.append("")

    if available:
        lines.append("\u2705 *En stock :*")
        for r in available:
            price_str = f"\U0001F4B0 *{_escape_md(f'{r.price:.3f} TND')}*" if r.price else "prix N/A"
            desc = _escape_md(f"{r.reference} {r.description}".strip())
            lines.append(f"  \u2022 {desc} \u2014 {price_str}")
        lines.append("")

    if rupture:
        lines.append("\u274C *Rupture :*")
        for r in rupture:
            desc = _escape_md(f"{r.reference} {r.description}".strip())
            lines.append(f"  \u2022 {desc}")
        lines.append("")

    if not_found:
        lines.append("\u2753 *Non reference CDG :*")
        for ref in not_found:
            lines.append(f"  \u2022 {_escape_md(ref)}")
        lines.append("")

    return "\n".join(lines)


from src.telegram.ui import escape_md as _escape_md


async def _notify_operator_refs_missing(vehicle_name: str, part_name: str) -> None:
    """Notify operator: no references in DB for this vehicle+part."""
    if not _operator_app or not _operator_chat_id:
        log.warning("Operator app not set, cannot notify")
        return
    text = (
        "-----------------------------\n"
        "REFERENCE MANQUANTE\n"
        "-----------------------------\n"
        f"Vehicule: {vehicle_name}\n"
        f"Piece: {part_name}\n\n"
        "Aucune reference en base pour cette combinaison.\n"
        "-> Ajoutez via /ref avec des screenshots PiecesAuto24\n"
        "-----------------------------"
    )
    try:
        await _operator_app.bot.send_message(chat_id=_operator_chat_id, text=text)
    except Exception as e:
        log.error("Failed to notify operator: %s", e)


async def _notify_operator_cdg_unavailable(
    vehicle_name: str, part_name: str, ref_codes: list[str],
) -> None:
    """Notify operator: refs exist but none found at CDG."""
    if not _operator_app or not _operator_chat_id:
        log.warning("Operator app not set, cannot notify")
        return
    refs_str = ", ".join(ref_codes[:10])
    if len(ref_codes) > 10:
        refs_str += f"... (+{len(ref_codes) - 10})"
    text = (
        "-----------------------------\n"
        "CDG INDISPONIBLE\n"
        "-----------------------------\n"
        f"Vehicule: {vehicle_name}\n"
        f"Piece: {part_name}\n"
        f"References testees (0/{len(ref_codes)} chez CDG):\n"
        f"{refs_str}\n\n"
        "-> Verifier si CDG distribue cette categorie\n"
        "-----------------------------"
    )
    try:
        await _operator_app.bot.send_message(chat_id=_operator_chat_id, text=text)
    except Exception as e:
        log.error("Failed to notify operator: %s", e)


async def notify_operator(text: str) -> None:
    """Send arbitrary text notification to operator."""
    if not _operator_app or not _operator_chat_id:
        log.warning("Operator app not set, cannot notify")
        return
    try:
        await _operator_app.bot.send_message(chat_id=_operator_chat_id, text=text)
    except Exception as e:
        log.error("Failed to notify operator: %s", e)
