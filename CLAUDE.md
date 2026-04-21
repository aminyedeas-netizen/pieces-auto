# Project: Pieces Auto TN

Auto parts search platform for Tunisia. Two Telegram bots connect customers to
auto parts via a PiecesAuto24 reference database and CDG wholesaler live pricing.

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

## What This Project Does

1. **OPERATOR BOT** (@piece_line_admin_bot): Used by the mechanic partner to:
   - `/ajouter_ref` — Ingest PiecesAuto24 screenshots via LLM vision, extract references
   - `/vin` — Decode VIN numbers and associate them with DB vehicles
   - `/ref` — Look up DB references (brand > model > fuel > motorisation > part category > part)
   - `/dispo` — Check CDG availability + live pricing (same flow + CDG search)
   - `/stats` — DB statistics
   - `/guide` — Help text
   - Free text — auto-parses "brand model part" or direct reference codes

2. **CLIENT BOT** (@piece_line_client_bot): Used by customers to:
   - Identify vehicle via: photo carte grise (OCR), VIN text entry, or button selection
   - Search parts via: free text ("Kia Picanto filtre a huile"), button selection (fuel > motorisation > part category > part), or direct ref code
   - See live CDG prices and availability for matching references
   - Franco-Arabic/misspelling tolerance ("quit de distribusion" -> "Kit de distribution")

## Critical Design Rules
1. The LLM NEVER guesses part references. References come ONLY from the database.
2. VIN decoding: PSA brands use 3-char engine code at VIN positions 5-7, searched in vehicles table.
   Other brands use vin_patterns table (first 13 chars). Fallback: local JSON tables in data/vin_tables/.
3. Every operator validation enriches the database permanently.
4. Prices and stock are NEVER cached — always live from CDG scraper.
5. Both bots are on Telegram (free, unlimited, no token issues).
6. ZERO free text input for vehicle identification in operator bot. Always buttons from DB.
7. PiecesAuto24 is the single source of truth for vehicle naming and part references.
8. CDG is the single source of truth for prices and availability.

## Architecture

```
src/
  __main__.py          — CLI entry point (decode-vin, init-db, seed, stats, serve)
  main.py              — asyncio.run(_serve()) starts both bots + seeds DB
  chain.py             — orchestrator: DB refs -> CDG search -> format results
  part_aliases.py      — part name alias table + resolve/variant helpers
  db/
    models.py          — dataclasses: Vehicle, StoredReference, CDGResult, etc.
    repository.py      — asyncpg pool, all DB queries (CRUD for 6 tables)
    schema.sql         — DDL for 6 tables
    seed.py            — incremental seed from data/database.json (COPY + chunking + retry)
  interpreter/
    llm.py             — OpenRouter LLM calls (vision + text), parse_vehicle_query()
  scraper/
    cdg.py             — Playwright headless browser, CDG login/search/parse + designation fallback
    pa24.py            — PA24 scraper via CDP (Chrome port 9222), search + extract + save
    catalog_cache.py   — reads cdg_stock_results.json to skip known-not-found refs
  telegram/
    operator_bot.py    — all operator bot handlers and commands
    client_bot.py      — all client bot handlers and commands
    ai_layer.py        — LLM conversation layer (system prompt, tool declarations, handle_message)
    ai_functions.py    — tool function implementations (search_parts, search_cdg, propose_pa24_add, etc.)
    ui.py              — shared UI: keyboard builders, label formatters, escape_md
  vin/
    decoder.py         — VIN decoding (WMI, year, PSA engine code, JSON fallback)
scripts/
  cdg_stock_check.py   — batch-search DB refs on CDG, save results JSON
  generate_cdg_report.py — HTML+PDF report from CDG results
  generate_project_guide.py — project overview PDF for sharing
data/
  database.json        — PA24 scraped data (structured: vehicle dict + product dict)
  vin_tables/          — local JSON VIN decode tables
  cdg_stock_results.json — CDG search cache (built by scripts)
```

### Tech Stack
- Python 3.12 + python-telegram-bot (latest)
- LLM via OpenRouter (google/gemini-2.0-flash-exp for vision, anthropic/claude-haiku-4.5 for text)
- Playwright for CDG scraping (headless Chromium)
- PostgreSQL via Supabase (asyncpg connection pool)
- uv as package manager

## Database Schema (6 tables)
- `vehicles` — exact names from PA24 (UNIQUE pa24_full_name). Fields: brand, model, displacement, power_hp, fuel, year_start, year_end, engine_code
- `vin_patterns` — first 13 chars of VIN -> vehicle_id (UNIQUE vin_pattern)
- `part_references` — vehicle_id + part_name + brand + reference (UNIQUE combo). source: oe/main_product/equivalent/cross_reference
- `part_vehicle_compatibility` — reference_id + compatible_vehicle_name (UNIQUE combo)
- `screenshots` — vehicle_id + filename metadata
- `requests_log` — client request audit trail

## Data Flow

### database.json Format (structured)
Each entry has:
- `vehicle`: dict with `brand`, `model_generation`, `displacement`, `cv`, `fuel`, `year_start`, `year_end`, `engine_code`, `raw_vehicle`
- `part`: string (part name)
- `product`: dict with `brand`, `reference`, `name`
- `specs`: dict of part specifications
- `equivalents`: list of {brand, reference, price_eur}
- `cross_references`: list of {brand, reference, price_eur}
- `compatible_vehicles`: list of compatible vehicle descriptions

### Seed Process
`seed_vehicles()` in seed.py runs on every `serve` startup (incremental):
1. Collects all `raw_vehicle` names from database.json
2. Deletes stale vehicles not in current data (via temp table JOIN)
3. Upserts vehicles via COPY + staging table (fast for any size)
4. Compares ref counts per vehicle (DB vs database.json) — skips unchanged vehicles
5. Inserts only new refs in 10k-row chunks with fresh connections + retry (handles Supabase connection drops)

### Part Name Aliases (src/part_aliases.py)
- `PART_ALIASES` maps standard DB names to customer/mechanic aliases (franco-arabic, misspellings, CDG names)
- `resolve_part_name(input)` normalizes user input to DB name before any query (accent-insensitive)
- `get_cdg_variants(name)` returns all alias variants for CDG designation search
- Applied in: `search_parts()`, `search_cdg()`, `chain.search_part()`, CDG `_fuzzy_part_names()`
- Examples: "pompe essence" -> "Pompe a carburant", "bouji" -> "Bougie d'allumage", "plakat frin avant" -> "Plaquettes de frein avant"

### CDG Search Flow
1. User selects vehicle + part -> part name resolved via aliases -> DB query returns references (OE refs first, then aftermarket)
2. References normalized (strip spaces/dashes/dots) before CDG search. Tries normalized first, original as fallback.
3. References split via catalog_cache: skip known-not-found, search the rest
4. CDG scraper searches each ref via #A20 (Trouver la reference) with asyncio.Lock
5. If NO results from reference search, **designation fallback**:
   - Search CDG by part name via #A33 (Trouver la designation)
   - Tries all alias variants first (e.g. "Pompe a carburant" also tries "pompe essence", "pompe gasoil", etc.)
   - Then fuzzy fallbacks: without filler words, first word only
   - Cross-reference CDG results against our OE refs: if a CDG result description contains one of our OE codes (normalized), it's a match
   - Return that CDG reference with price/availability
6. Results formatted: available (with price), rupture, non-ref sections
7. Operator notified if no refs exist in DB for requested vehicle+part

### PA24 Scraping (chatbot "ajouter" command)
- Uses CDP connection to a running Chrome instance (port 9222) to bypass Cloudflare
- Two modes:
  A) By reference: `propose_pa24_add(reference="560118")` — searches PA24 directly
  B) By vehicle+part: `propose_pa24_add(brand, model, part_name)` — first validates vehicle from DB (returns CHOICES of motorisations), then searches PA24 with validated vehicle name + part
- Two-step confirmation: preview first (`propose_pa24_add`), save only after user confirms (`confirm_pa24_add`)
- Search uses the homepage search field (not URL params — URL-based search is unreliable with CDP)
- Extraction happens while on the product page (no second navigation)
- Results cached 5min to prevent duplicate scrapes if LLM calls the function twice
- HTML parsing with BeautifulSoup: product info, specs, equivalents, cross-refs, OE refs (#oem section), compatible vehicles (#compatibility section with data-toggle-maker accordions)
- Saves one DB entry per compatible vehicle found on the page
- Also appends to data/database.json so data survives re-seed

## Environment Variables
```
TELEGRAM_OPERATOR_BOT_TOKEN    — operator bot token
TELEGRAM_CLIENT_BOT_TOKEN      — client bot token
TELEGRAM_OPERATOR_CHAT_ID      — chat ID for operator notifications
OPENROUTER_API_KEY             — LLM API key
CDG_URL                        — CDG wholesaler base URL
CDG_LOGIN / CDG_PASSWORD       — CDG credentials
DATABASE_URL                   — Supabase PostgreSQL connection string
```

## How to Run
- Both bots: `uv run python3 -m src serve` (auto-seeds DB on startup)
- Seed only: `uv run python3 -m src seed`
- Init schema: `uv run python3 -m src init-db`
- CLI VIN decode: `uv run python3 -m src decode-vin <VIN>`
- DB stats: `uv run python3 -m src stats`

## UI Architecture (src/telegram/ui.py)

### Display Contract
Button labels are display-only transforms. DB values are cached in session at original form.
Callbacks carry indices (e.g. `model:3`), handlers resolve back to original DB value.

### Model Picker — Family Grouping
For brands with many models (>6, with families having 2+ variants):
- First shows family buttons (e.g. "A3 (4)", "A4 (3)")
- On tap, shows variants within that family
- Falls back to flat list for small brands
- `model_family(m)` = first token of model string
- `render_model_keyboard()` / `render_variants_keyboard()` handle this

### Label Formatting
- `format_model_label()`: strips brand prefix, abbreviates body styles (Sportback->Sportb.), end-truncates at 30 chars
- `format_engine_label()`: compact "1.6 90CV Diesel 9HX"
- `adaptive_grid()`: 2-col if all labels <=22 chars, else 1-col
- `build_parts_keyboard()`: categorized parts with divider headers

### Part Category Grouping
When a vehicle has parts in multiple categories, an intermediary step shows category buttons
(e.g. "Filtration (4)", "Freinage (3)") before listing individual parts.
- `categorize_parts()`: groups parts into categories, returns (cat_idx, cat_name, part_indices)
- `build_category_keyboard()`: category buttons with counts. Returns [] if single category (skips step).
- `build_category_parts_keyboard()`: parts within a selected category
- Applied in all three flows: client bot, operator /ref, operator /dispo

### Vehicle Selection Flow
Both bots use Fuel > Motorisation (not Year > Engine):
- Brand > Model (with family grouping) > Fuel (skipped if single) > Motorisation > Part category > Part
- Motorisation groups vehicles by (displacement, fuel, power_hp), maps to multiple vehicle_ids
- Format: "1.6 essence 102CV"

## Current State (April 2026)

### Database
- 10,000+ vehicles, ~100,000+ references (seeded from data/database.json)
- database.json maintained in a separate Claude Code session, growing continuously

### Known Limitations
- CDG price extraction uses index pairing (known misalignment risk with rupture items — mitigated by only incrementing price_idx for available items)
- In-memory sessions lost on bot restart (acceptable for now)
- `/ajouter_ref` creates vehicles from LLM-scraped names which may not match PA24 naming exactly — can cause near-duplicates in the vehicles table. Design fix: select vehicle from DB buttons instead of LLM-generated names.
- CDG stock check script and bot scraper can race on cdg_stock_results.json reads (mitigated: partial read falls back to existing cache instead of clearing)
- PA24 scraping requires a Chrome instance running with `--remote-debugging-port=9222` (Cloudflare blocks headless Playwright)

### Build Progress
- [x] Steps 1-16: Full platform implemented (both bots, all commands, CDG scraper, UI improvements)
- [ ] Step 17: CDG stock catalog (ongoing — batch searching DB refs on CDG)
- [x] Step 18: Code review fixes (15 issues from REVIEW.md)
- [x] Step 19: Vehicle selection rewrite (Fuel > Motorisation instead of Year > Engine)
- [x] Step 20: Part category intermediary step (both bots)
- [x] Step 21: Incremental seed with COPY + chunking + retry
- [x] Step 22: AI chatbot layer (operator bot free-text, LLM function calling, system prompt)
- [x] Step 23: PA24 chatbot scraping ("ajouter [ref]" — search + extract + save in one call)
- [x] Step 24: CDG designation fallback (fuzzy part name search + OE cross-reference)
- [x] Step 25: Part name aliases (normalize customer/mechanic slang to DB names, CDG variant search)
- [x] Step 26: PA24 vehicle+part search (validate vehicle from DB before PA24 search, CHOICES flow)
