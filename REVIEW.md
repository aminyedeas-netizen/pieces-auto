# Code Review: PIECES-AUTO

**Date:** 2026-04-03
**Reviewer:** Claude Opus 4.6
**Scope:** All source files under `src/` and `scripts/`
**Focus:** Data accuracy, business correctness, security, reliability

---

## CRITICAL (wrong data shown to customers)

### 1. CDG Scraper: Price-to-Reference Misalignment

**File:** `src/scraper/cdg.py`, lines 78-130

The `_parse_results` method extracts prices via JavaScript (scanning DOM for "Prix HT" labels with nearby `<input>` values) and extracts references via text parsing (scanning `body.innerText` for "Reference" lines). It pairs them **by index** (`price_idx`).

If ANY "Prix HT" label on the page has a nearby input that matches the price regex but does NOT correspond to a product row (e.g., a header, summary, or cart element), or if a product row exists without a "Prix HT" label, the prices shift and **every subsequent result gets the WRONG PRICE**.

**Impact:** A customer could see a price for the wrong part and order based on it.

**Fix:** Extract both price and reference from the same DOM row container, rather than extracting them independently and pairing by index.

---

### 2. CDG Scraper: No Session Recovery

**File:** `src/scraper/cdg.py`, lines 52-61; `src/chain.py`, lines 24-29

The singleton `CDGScraper` logs in once and never re-authenticates. When the CDG session expires (common after inactivity), `search()` executes against a login page or error page. The text parser finds no "Reference" lines and returns `[]`. `chain.py` then tells the customer **"Piece non disponible actuellement"** — which is false.

**Impact:** After any period of inactivity, ALL customer searches incorrectly report parts as unavailable until app restart.

**Fix:** Add session health checks after each search (verify page looks like results page). Re-login automatically when session is stale.

---

## HIGH (data loss / broken functionality)

### 3. `decode_vin_with_db` Import Does Not Exist

**File:** `src/interpreter/llm.py`, line 108

`interpret_message` imports `decode_vin_with_db` from `src.vin.decoder`, but this function does not exist — only `decode_vin` exists. Any call through the carte grise OCR interpretation path will raise `ImportError`.

**Fix:** Change to `from src.vin.decoder import decode_vin` and update the call.

---

### 4. `notify_operator` Import from Wrong Module

**File:** `src/telegram/client_bot.py`, line 800

`_auto_store_vin_pattern` imports `notify_operator` from `src.telegram.operator_bot`, but no such function exists there. Wrapped in try/except, so it silently fails — the operator is **never notified** when a client auto-stores a VIN pattern.

**Fix:** Import from `src.chain` instead: `from src.chain import notify_operator`

---

### 5. Seed Deletion Misses FK Dependencies

**File:** `src/db/seed.py`, lines 144-154

The seed cleanup deletes stale `part_references` and `vehicles`, but does NOT delete dependent records in:
- `vin_patterns` (FK to `vehicles.id`)
- `screenshots` (FK to `vehicles.id`)
- `part_vehicle_compatibility` (FK to `part_references.id`)

If `database.json` removes a vehicle that has VIN patterns or screenshots, the `DELETE FROM vehicles` fails with FK constraint violation, and the **entire seed (and bot startup) fails**.

**Fix:** Add cascade deletes for `vin_patterns`, `screenshots`, and `part_vehicle_compatibility` before the existing deletes in Phase 0.

---

### 6. CDG Scraper: Concurrent Access Corruption

**File:** `src/scraper/cdg.py` (single `_page`); `src/chain.py` (singleton `_scraper`)

Both bots share one `CDGScraper` with a single Playwright page. If two users search simultaneously (client + operator `/dispo`), the async operations interleave: one search fills the input while another's results are being parsed, producing **corrupted or wrong results**.

**Fix:** Add `asyncio.Lock` around the `search` method:
```python
async def search(self, reference: str) -> list[CDGResult]:
    async with self._lock:
        # existing code
```

---

## MEDIUM (reliability)

### 7. In-Memory Sessions Lost on Restart

**File:** `src/telegram/client_bot.py`, line 38; `src/telegram/operator_bot.py`, lines 29-37

All session state (vehicle selection progress, pending confirmations) is in Python dicts. On restart (every deployment), all users mid-flow get stuck. Critically, operator `pending_confirms` data (VIN patterns, references) is permanently lost with no indication.

**Fix:** Persist critical pending operations (especially operator confirmations) to the database, or inform users gracefully when sessions expire.

---

### 8. VIN Pattern Regex Accepts Too Much

**File:** `src/telegram/client_bot.py`, line 24

`VIN_PATTERN = r"[A-HJ-NPR-Z0-9]{17}"` without word boundaries. Any 17+ alphanumeric substring in user text triggers VIN processing (false positives).

**Fix:** Add word boundaries: `re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")`

---

## Summary

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | CRITICAL | CDG price misalignment | Wrong prices shown to customers |
| 2 | CRITICAL | CDG session expiry | All searches falsely report "unavailable" |
| 3 | HIGH | Broken import `decode_vin_with_db` | Carte grise OCR flow crashes |
| 4 | HIGH | Wrong `notify_operator` import | Operator never notified of VIN patterns |
| 5 | HIGH | Seed FK cascade missing | Bot startup can fail after data changes |
| 6 | HIGH | CDG concurrent access | Wrong results when multiple users search |
| 7 | MEDIUM | In-memory session loss | Users stuck after restart |
| 8 | MEDIUM | VIN regex too broad | False VIN detection in user messages |

**Priority order for fixes:** Issues 1 and 2 (customer-facing data accuracy), then 3-6 (functionality), then 7-8 (reliability).
