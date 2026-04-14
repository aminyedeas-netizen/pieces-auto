# UI Display Contract

Read this before adding a new button picker (brand / model / year / engine /
part) in either bot.

## Rule

**Display formatting is one-way and ephemeral. The database always sees the
original value.**

Buttons in Telegram are rendered with cleaned-up labels (brand prefix
stripped, body-style noise removed, casing fixed, chassis codes uppercased,
mid-truncation), but every callback resolves the user's tap back to the
*original DB string* before any query runs.

## Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. Repository fetch                                                    │
│     get_distinct_models("CITROEN")                                      │
│       → ["Berlingo First Van", "Citroën C3 Phase 1", ...]               │
│     The repository may collapse engine-suffix duplicates                │
│     (see _canonical_model in src/db/repository.py) but the surviving    │
│     value is still a real DB-shaped string.                             │
│                                                                         │
│  2. Cache the raw list                                                  │
│     session["models"] = models   ← UNTOUCHED, used later for queries    │
│                                                                         │
│  3. Render labels                                                       │
│     for i, raw in enumerate(models):                                    │
│         label = format_model_label(brand, raw)   ← display only         │
│         button = InlineKeyboardButton(label, callback_data=f"model:{i}")│
│     The callback carries the INDEX, never the formatted label.          │
│                                                                         │
│  4. Resolve on tap                                                      │
│     idx = int(data.split(":")[1])                                       │
│     raw = session["models"][idx]   ← back to the DB-shaped string       │
│     await get_distinct_years_for_model(brand, raw)   ← uses raw value   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Why callbacks carry an index, not the label

- Telegram limits `callback_data` to 64 bytes; long model names overflow.
- Decoupling display from identity means we can rename labels freely without
  breaking active sessions.
- It guarantees the DB is queried with a value it actually contains.

## Where the formatters live

All in `src/telegram/ui.py`:

| Function | Purpose | Used in |
|---|---|---|
| `format_model_label(brand, model)` | strip brand prefix, body noise, normalize case, mid-truncate | operator `/get`, client model picker |
| `format_engine_label(vehicle)` | compact "1.6 90CV Diesel 9HX" | (helper, not yet wired everywhere) |
| `grid_buttons(items, cols)` | lay out `(label, callback_data)` tuples in N columns | engine pickers (operator + client) |
| `build_parts_keyboard(parts, prefix, tail_rows)` | group parts into Freinage / Filtration / Distribution / Suspension / Moteur with `── divider ──` rows | operator `/get` parts step |
| `PART_CATEGORIES` | the categorization map | edit here to add a new family |

## DB-side normalization (related but distinct)

`src/db/repository.py::_canonical_model` strips engine-suffix patterns
(BlueHDi, PureTech, "131 CV", year ranges) **inside** model names so that
"Peugeot 308 III 3/5 portes BlueHDi 131 CV..." collapses with its PureTech
and e-308 siblings. This is still a server-side dedup that returns a real
DB-shaped value (just the shorter base). The display formatter then makes it
pretty.

`get_vehicles_for_model`, `get_distinct_years_for_model`, and
`get_vehicles_for_model_year` use a prefix-match
(`LOWER(model) = $2 OR LOWER(model) LIKE $2 || ' %'`) so picking the
canonical "Peugeot 308 III" still surfaces all three engine variants stored
in the DB.

## Adding a new picker — checklist

1. Cache the raw DB list in the session before rendering.
2. Render labels through a formatter in `ui.py` (or add one).
3. Use indices in `callback_data`, never the formatted label.
4. In the handler, look the raw value back out of the session and use *that*
   for the next query.
5. If you need to dedupe at the DB layer, add the logic next to
   `_canonical_model` and keep the returned values DB-shaped.

## Adding a new formatter

Put it in `src/telegram/ui.py`. Give it a docstring describing what it
strips, what it preserves, and the max length. Never call it from the
repository layer or anywhere that touches the DB.
