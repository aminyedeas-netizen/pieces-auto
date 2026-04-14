# Project: Pieces Auto TN

## VERY IMPORTANT
- Be simple. Approach tasks in a simple, incremental way.
- Work incrementally ALWAYS. Small, simple steps. Validate and check each increment before moving on.
- Use LATEST apis as of NOW

## MANDATORY Code Style
- Do not overengineer. Do not program defensively. Use exception managers only when needed.
- Identify root cause before fixing issues. Prove with evidence, then fix.
- Work incrementally with small steps. Validate each increment.
- Use latest library APIs.
- Use uv as Python package manager. Always uv run xxx never python3 xxx, always uv add xxx never pip install xxx
- Favor clear, concise docstring comments. Be sparing with comments outside docstrings.
- Favor short modules, short methods and functions. Name things clearly.
- Never use emojis in code or in print statements or logging
- Keep README.md concise

## Important - debugging and fixing
- When troubleshooting problems, ALWAYS identify root cause BEFORE fixing
- Reproduce consistently
- PROVE THE PROBLEM FIRST - don't guess.
- Try one test at a time. Be methodical.
- Don't jump to conclusions. Don't apply workarounds.

## Project Context
Auto parts e-commerce platform for Tunisia. Two Telegram bots:
1. OPERATOR BOT: feeds part references (from PiecesAuto24 screenshots) and VIN
   mappings into the database. Used by the mechanic partner or data entry person.
2. CLIENT BOT: customers identify their vehicle and search for parts. Prices
   and availability come from CDG wholesaler in real-time.

PiecesAuto24 is the single source of truth for vehicle naming and part references.
CDG is the single source of truth for prices and availability.
The LLM NEVER guesses part references. References come ONLY from the database.

## Critical design rules
1. The LLM NEVER guesses part references. References come ONLY from the database.
2. VIN decoding: PSA brands use 3-char engine code at VIN positions 5-7, searched in vehicles table.
   Other brands use vin_patterns table (first 13 chars). Fallback: local JSON tables in data/vin_tables/.
3. Every operator validation enriches the database permanently.
4. Prices and stock are NEVER cached — always live from CDG scraper.
5. Both bots are on Telegram (free, unlimited, no token issues).
6. ZERO free text input for vehicle identification in operator bot. Always buttons from DB.

## Architecture
- Python + python-telegram-bot (latest)
- LLM via OpenRouter (google/gemini-2.0-flash-exp for vision, anthropic/claude-haiku-4.5 for text)
- Playwright for CDG scraping
- PostgreSQL (Supabase)
- uv as package manager

## Database Schema (6 tables)
- vehicles: exact names from PiecesAuto24 (pa24_full_name)
- vin_patterns: first 13 chars of VIN -> vehicle_id
- part_references: vehicle_id + part_name + brand + reference
- part_vehicle_compatibility: cross-reference compatible vehicles
- screenshots: local screenshot storage metadata
- requests_log: client request audit trail

## Environment variables
TELEGRAM_OPERATOR_BOT_TOKEN, TELEGRAM_CLIENT_BOT_TOKEN
OPENROUTER_API_KEY, CDG_URL, CDG_LOGIN, CDG_PASSWORD
DATABASE_URL

## How to run
- CLI testing: uv run python3 -m src <command>
- Both bots: uv run python3 -m src serve
- Init DB: uv run python3 -m src init-db

## Operator Bot Commands
- /ajouter_ref -- Screenshot ingestion from PiecesAuto24 (cancel button at every step)
- /vin -- VIN decode + vehicle association (clear instructions, case E / chassis)
- /get -- DB reference lookup (brand > model > year > engine > part buttons, no prices)
- /dispo -- CDG availability + price check (brand > model > year > engine, LLM text parsing, direct ref search)
- /stats -- DB statistics
- /guide -- Help with all commands

## Client Bot Features
- 3 vehicle ID paths: photo carte grise, VIN entry, model selection buttons
- Free text input: "Kia Picanto filtre a huile" -> LLM extracts brand+model+part
- Year selection: Brand > Model > Year buttons > Engine (auto-skips single options)
- LLM year extraction: "Peugeot 208 2019 courroie" -> filters by year_start
- Part matching: fuzzy SQL first, then LLM against available parts list
- Misspelling/franco-arabic support: "quit de distribusion" -> "Kit de distribution"
- Ambiguous parts: "Amortisseur" -> buttons [avant] [arriere]
- Confirmation before search: vehicle + part summary
- Direct reference search: bare ref code or "Gates K015578XS" -> CDG search
- Text confirmations: "ok", "oui" triggers pending actions
- Navigation: "Autre piece" (same vehicle) + "Nouvelle recherche" (reset)

## Build Progress
- [x] Step 1: Project init, deps, file structure, .env, schema.sql
- [x] Step 2: VIN decoder (41 WMI codes, year table, PSA engine code DB search, JSON fallback)
- [x] Step 3: DB repository (full CRUD for 6 tables) + seed from data/database.json
- [x] Step 4: Operator bot /ajouter_ref (multi-screenshot, LLM vision, cancel buttons)
- [x] Step 5: Operator bot /vin (VIN decode, button-based vehicle selection, pattern storage)
- [x] Step 6: Client bot vehicle identification (photo, VIN, model selection, max 1 retry)
- [x] Step 7: Client bot part selection (dynamic from DB, LLM fuzzy matching)
- [x] Step 8: CDG scraper (headless Playwright, search_all for all refs)
- [x] Step 9: Full chain (DB refs -> CDG -> available/rupture/non-ref sections)
- [x] Step 10: Operator /stats + /guide + /get (DB refs) + /dispo (CDG search)
- [x] Step 11: Reference lookup both bots (grouped OE/equiv/cross, index-based callbacks)
- [x] Step 12: Smart text input (LLM brand+model+part+ref extraction, franco-arabic)
- [x] Step 13: Direct reference search (bare ref or brand+ref -> CDG)
- [x] Step 14: Bug fixes (callback truncation, VIN state, retry counter, insert_reference count)
- [x] Step 15: Year selection buttons (Brand > Model > Year > Engine in both bots, LLM year extraction)
- [x] Step 16: Code review fixes (8 issues), CDG equivalents, back buttons, operator text handler
- [ ] Step 17: CDG stock catalog (ongoing — batch searching DB refs on CDG, building availability map)

## Current State (April 2026)

### Database
- 275 vehicles, 21,196 references (seeded from data/database.json)
- Re-seed: `uv run python3 -m src seed` (auto-seeds on `serve` startup too)
- database.json is maintained in a separate Claude Code session and updated regularly

### CDG Scraper (src/scraper/cdg.py)
Key behaviors implemented:
- **Equivalents expansion**: after each search, clicks the equiv count button (e.g. "5") to
  show all equivalent references CDG carries for that part. Then navigates back to catalog.
- **Session recovery**: checks page title before each search; re-logins if CDG session expired.
- **Concurrency lock**: asyncio.Lock serializes all search calls (both bots share one scraper).
- **Price extraction**: prices come from `<input>` values near "Prix HT" labels, paired by index
  with references. Known limitation: index-based pairing can misalign if page has extra elements.

### CDG Stock Check Scripts (scripts/)
- `scripts/cdg_stock_check.py` — batch-searches DB references on CDG. Key features:
  - Priority order: kit distribution > embrayage > freinage > roulements > pompe eau >
    amortisseurs > direction > demarreurs > alternateurs > thermostat > joint > courroie
    accessoire > filtres > bougies (CDG-likely parts first, filters last)
  - Vehicle priority: 208 PureTech, Logan, Sandero, Clio, Picanto, i10, Polo, Yaris, etc.
  - `--resume` flag: skips already-searched refs, fetches new ones from DB
  - `--limit N`: max refs to search (default 200)
  - `--brand` / `--vehicle`: filter by brand or vehicle pattern
  - Exact ref matching only (CDG does fuzzy search, we filter to exact matches)
  - Saves screenshots for found refs to data/cdg_screenshots/
  - Auto-saves every 25 searches to data/cdg_stock_results.json
  - Auto-generates HTML+PDF report at end of run
- `scripts/generate_cdg_report.py` — generates data/cdg_report.html + .pdf from results JSON.
  Report organized by vehicle brand > vehicle card > reference table with clean separators.

### CDG Search Results So Far
- ~800/2000 refs searched (background search still running)
- CDG overlap is low (~5% hit rate) but finds high-value mechanical parts
- CDG carries VALEO embrayage kits, OE distribution tensioners
- CDG does NOT carry most aftermarket brands in our DB (RIDEX, MAPCO, FEBI, etc.)
- Filters/bougies: CDG unlikely to have them (low priority, searched last)
- Google verification confirmed accuracy: CDG descriptions match actual parts

### Recent Fixes Applied (Step 16)
1. CDG session recovery (re-login on expiry)
2. CDG concurrency lock (asyncio.Lock)
3. Fixed broken import `decode_vin_with_db` -> `decode_vin` in src/interpreter/llm.py
4. Fixed wrong `notify_operator` import in client_bot.py (was from operator_bot, now from chain)
5. Seed FK cascade: deletes vin_patterns, screenshots, part_vehicle_compatibility before vehicles
6. VIN regex word boundaries (\b) to prevent false matches
7. CDG equivalents: scraper clicks equiv button to show all equivalent refs
8. Back buttons (Retour) at every selection step in both bots
9. Operator bot text handler: free text for reference search + vehicle+part parsing (like client bot)

### Known Issues / Limitations
- CDG price extraction uses index pairing (Prix HT label index -> reference index). If CDG page
  layout has extra elements, prices can misalign. Needs DOM row-based extraction for 100% accuracy.
- In-memory sessions lost on bot restart (acceptable for now, would need DB persistence to fix).
- 208 PureTech appears as "208 CC" and "208 Phase 2" in model selection — this is correct per
  PiecesAuto24 naming, not a bug.
