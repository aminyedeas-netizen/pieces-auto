# Pieces Auto TN

Telegram-native auto-parts search for Tunisia. Two bots share a Supabase
Postgres database and a live CDG wholesaler scraper. Clients identify their
car (carte grise photo, VIN, or buttons) and get valid references with live
price and stock. An operator ingests references from PiecesAuto24
screenshots via LLM vision.

## Stack

Python 3.12 · `python-telegram-bot` · Playwright (CDG scraper) ·
OpenRouter (Gemini Flash for vision, Claude Haiku for text) ·
Supabase Postgres · `uv`

## Rules

- PiecesAuto24 is the single source of truth for vehicle names and references.
- CDG is the single source of truth for price and stock (never cached, always live).
- The LLM never invents references — they always come from the database.

## Run

```bash
uv sync
cp .env.example .env   # fill in tokens and DB URL
uv run python3 -m src serve
```

## Commands

**Client bot** — photo / VIN / model pickers, free text (French, Arabic,
Tunisian franco-arabic), direct reference search.

**Operator bot** — `/ajouter_ref`, `/vin`, `/ref`, `/dispo`, `/stats`, `/guide`.

## Layout

- `src/telegram/` — client and operator bot handlers, UI formatters
- `src/db/` — repository, schema, seed
- `src/scraper/` — Playwright CDG scraper
- `src/interpreter/` — OpenRouter LLM wrapper and text parser
- `src/vin/` — VIN decoding
- `docs/ui_display_contract.md` — read before adding a new picker UI
- `data/database.json` — canonical PiecesAuto24 dataset (re-seeded on startup)
