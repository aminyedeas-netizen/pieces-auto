"""CDG catalog cache.

Reads data/cdg_stock_results.json (built by scripts/cdg_stock_check.py) and
exposes lookups so the /dispo flow can short-circuit refs already proven to
not exist on CDG. Refs that were found (in stock OR rupture only) are NOT
short-circuited because prices and stock are never cached.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_RESULTS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cdg_stock_results.json"

_cache: dict[str, dict] | None = None
_mtime: float | None = None


def _normalize(ref: str) -> str:
    return ref.replace(" ", "").replace("-", "").upper()


def _load() -> dict[str, dict]:
    """Load (or reload) the catalog from disk if the file mtime changed."""
    global _cache, _mtime
    if not _RESULTS_FILE.exists():
        _cache = {}
        return _cache
    mtime = _RESULTS_FILE.stat().st_mtime
    if _cache is not None and _mtime == mtime:
        return _cache
    try:
        data = json.loads(_RESULTS_FILE.read_text())
    except Exception as e:
        log.warning("Could not read catalog cache: %s", e)
        _cache = {}
        return _cache
    searched = data.get("searched", {})
    _cache = {_normalize(ref): entry for ref, entry in searched.items()}
    _mtime = mtime
    log.info("Loaded CDG catalog cache: %d refs", len(_cache))
    return _cache


def is_known_not_found(reference: str) -> bool:
    """True if this ref was searched on CDG before and not found."""
    cache = _load()
    entry = cache.get(_normalize(reference))
    if not entry:
        return False
    if entry.get("error"):
        return False
    return entry.get("cdg_found") is False


def filter_searchable(references: list[str]) -> tuple[list[str], list[str]]:
    """Split refs into (to_search, known_not_found).

    to_search: refs that are unknown OR previously found (need fresh live data).
    known_not_found: refs catalog-confirmed as never on CDG, safe to skip.
    """
    to_search: list[str] = []
    known_not_found: list[str] = []
    for ref in references:
        if is_known_not_found(ref):
            known_not_found.append(ref)
        else:
            to_search.append(ref)
    return to_search, known_not_found
