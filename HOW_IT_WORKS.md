# How the Bots Operate

Quick reference for understanding what happens when a user sends a message.

---

## Two Bots, Two Audiences

| Bot | Who uses it | Main purpose |
|-----|------------|--------------|
| **Operator** (@piece_line_admin_bot) | Mechanic partner | Search refs, check CDG stock/prices, add new parts from PA24 |
| **Client** (@piece_line_client_bot) | End customers | Identify their car, find parts, see live prices |

Both run in one Python process (`uv run python3 -m src serve`).

---

## Operator Bot: Message Flow

```
User message (free text or /command)
       |
       v
  [ai_layer.py] -- sends to LLM (Gemini 2.5 Flash via OpenRouter)
       |            with system prompt + tool definitions
       v
  LLM returns tool_call (e.g. search_parts, search_cdg)
       |
       v
  [ai_functions.py] -- executes the tool call
       |               resolves part aliases first
       |               queries DB via repository.py
       v
  Result text returned to LLM
       |
       v
  LLM formats final response (or calls another tool)
       |
       v
  Bot sends message to user (with CHOICES buttons if applicable)
```

### Key behaviors:
- LLM always calls a function first, never answers from its own knowledge
- "pompe essence bmw serie 2" -> resolves alias to "Pompe a carburant", strips "Serie", searches DB
- If part not found exactly, fuzzy search returns CHOICES as buttons
- If LLM result contains `CHOICES:[...]`, operator_bot.py renders them as Telegram buttons

### Slash commands bypass the LLM:
- `/ref` -> button flow: Brand > Model > Fuel > Motorisation > Category > Part
- `/dispo` -> same flow + CDG live search
- `/vin` -> VIN decode + vehicle association
- `/ajouter_ref` -> PA24 screenshot ingestion via LLM vision

---

## Client Bot: Message Flow

```
User message (free text, photo, or button tap)
       |
       v
  [client_bot.py] -- determines intent:
       |
       +-- Photo? -> LLM vision extracts carte grise info
       +-- VIN text? -> decoder.py resolves vehicle
       +-- Free text? -> LLM parses "brand model part"
       +-- Button tap? -> advance selection flow
       |
       v
  Vehicle identified -> button flow:
    Fuel > Motorisation > Part Category > Part
       |
       v
  [chain.py] search_part() -- full search pipeline
       |
       v
  Formatted result with prices sent to user
```

---

## Part Search Pipeline (chain.py + ai_functions.py)

This is the core pipeline that both bots use:

```
1. Resolve part name alias
   "pompe essence" -> "Pompe a carburant"
   (src/part_aliases.py)

2. Find vehicles in DB
   search_vehicles_flexible(brand, model, fuel, power_hp)
   - Substring matching, accent-insensitive
   - Strips "Serie/Serie" prefix for BMW
   - Progressive relaxation: retry without fuel/power if no match

3. Look up references in DB
   lookup_references_multi(vehicle_ids, part_name)
   - Deduplicates across vehicle variants
   - Returns OE refs first, then aftermarket

4. Search CDG for each reference
   cdg.search(ref) for each ref code
   - Normalized (no spaces/dashes/dots)
   - Skips known-not-found refs (catalog_cache)

5. If no CDG hits -> Designation fallback
   cdg.search_designation_fallback(part_name, oe_refs)
   - Tries all alias variants as CDG search terms
   - Cross-references CDG results against our OE ref codes
   - Matches if CDG description embeds one of our OE codes

6. Format and return
   - Available items with price
   - Rupture (out of stock) items
   - Not found items
```

---

## Part Name Aliases

Users type things like "pompe essence", "bouji", "plakat frin avant". The alias
system (`src/part_aliases.py`) normalizes these to standard DB names before any
query runs.

The same aliases feed CDG designation search: when searching by part name on CDG,
we try all known aliases as search terms (e.g. "POMPE A CARBURANT", "POMPE ESSENCE",
"POMPE GASOIL") to maximize chances of finding a match.

Alias resolution happens in three places:
- `ai_functions.search_parts()` -- operator chatbot
- `ai_functions.search_cdg()` -- CDG price check
- `chain.search_part()` -- button-flow pipeline (both bots)

---

## PA24 Scraping (Adding New Parts)

Two modes for adding parts from PA24:

### Mode A: By reference
Operator sends "ajouter 560118":
```
1. propose_pa24_add(reference="560118")
   -> Searches PA24 directly, returns preview
2. Operator confirms -> confirm_pa24_add(url)
   -> Saves to DB + database.json
```

### Mode B: By vehicle + part
Operator sends "ajouter pompe a eau mercedes classe A":
```
1. propose_pa24_add(brand="MERCEDES-BENZ", model="Classe A", part_name="Pompe a eau")
   -> Looks up vehicle in our DB
   -> Returns CHOICES of motorisations (buttons)
2. Operator picks motorisation (e.g. "MERCEDES-BENZ Classe A 2.0 diesel 140CV")
   -> propose_pa24_add(vehicle_name="...", part_name="Pompe a eau")
   -> Searches PA24 with validated vehicle name + part
   -> Returns preview (link, refs count, compatible vehicles)
3. Operator confirms -> confirm_pa24_add(url)
   -> Saves to DB + database.json
```

### Extraction details
- Connects to Chrome via CDP (port 9222, bypasses Cloudflare)
- Searches PA24 homepage search field
- Extracts: product info, specs, equivalents, OE refs, cross-refs
- Clicks each brand accordion to load compatible vehicles (AJAX)
- Saves one DB entry per compatible vehicle found on the page

---

## CDG Scraping (Live Prices)

CDG is the wholesaler. Prices/stock are NEVER cached in the bot -- always live.

```
CDG Scraper (Playwright headless Chromium)
  - Login with credentials
  - Search by reference: #A20 form
  - Search by designation: #A33 form (fallback)
  - Parse results table: reference, designation, price, availability
  - asyncio.Lock prevents concurrent searches (CDG is session-based)
```

Separate from the bot, `scripts/cdg_stock_check.py` batch-searches all DB refs
on CDG and saves results to `data/cdg_stock_results.json` for reporting.

---

## Database

PostgreSQL on Supabase, 6 tables:

| Table | Purpose | Key constraint |
|-------|---------|---------------|
| `vehicles` | Cars from PA24 | UNIQUE pa24_full_name |
| `vin_patterns` | VIN prefix -> vehicle | UNIQUE vin_pattern |
| `part_references` | Parts per vehicle | UNIQUE (vehicle_id, part_name, brand, reference) |
| `part_vehicle_compatibility` | Cross-vehicle compatibility | UNIQUE (reference_id, vehicle_name) |
| `screenshots` | Ingested screenshot metadata | -- |
| `requests_log` | Client request audit trail | -- |

Seeded from `data/database.json` on every startup (incremental -- only inserts new data).

---

## Vehicle Selection Flow

Both bots use the same flow for narrowing down a vehicle:

```
Brand -> Model (family grouping if many) -> Fuel (skipped if single) -> Motorisation -> Part Category -> Part
```

- Motorisation = (displacement, fuel, power_hp) -- groups multiple vehicle_ids
- Family grouping: "A3 (4)" shows 4 A3 variants on tap
- Category grouping: "Filtration (4)" shows 4 filter types on tap
- Button labels are cleaned: no chassis codes, no year ranges

---

## LLM Integration

- **Model**: Gemini 2.5 Flash (via OpenRouter) for operator chatbot function calling
- **Vision**: Gemini 2.0 Flash for screenshot/carte grise OCR
- **Text**: Claude Haiku 4.5 for simpler text tasks
- System prompt forces function calls first, never free-text guessing
- CHOICES format: LLM passes through `CHOICES:[...]` from tool results, bot renders as buttons
