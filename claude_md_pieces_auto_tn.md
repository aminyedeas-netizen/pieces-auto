# CLAUDE.md — PIECES-AUTO-TN

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

## Architecture
- Python + python-telegram-bot (latest)
- LLM via OpenRouter (google/gemini-2.0-flash-exp for vision, anthropic/claude-haiku-4.5 for text)
- Playwright for CDG scraping
- PostgreSQL (Supabase)
- uv as package manager

## Environment variables

TELEGRAM_OPERATOR_BOT_TOKEN=...
TELEGRAM_CLIENT_BOT_TOKEN=...
OPENROUTER_API_KEY=sk-or-...
CDG_URL=http://www.cdgros.com/Site_CDG25
CDG_LOGIN=...
CDG_PASSWORD=...
DATABASE_URL=postgresql://...

## Database Schema

-- Vehicles: exact names from PiecesAuto24
CREATE TABLE vehicles (
    id SERIAL PRIMARY KEY,
    brand VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    chassis_code VARCHAR,
    displacement VARCHAR,
    power_hp INTEGER,
    fuel VARCHAR,
    year_start INTEGER,
    year_end INTEGER,
    engine_code VARCHAR,
    pa24_full_name VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pa24_full_name)
);

-- VIN patterns: 13 first chars -> vehicle
CREATE TABLE vin_patterns (
    id SERIAL PRIMARY KEY,
    vin_pattern VARCHAR(13) NOT NULL,
    vehicle_id INTEGER REFERENCES vehicles(id),
    confidence VARCHAR DEFAULT 'high',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(vin_pattern)
);

-- Part references extracted from PiecesAuto24
CREATE TABLE part_references (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER REFERENCES vehicles(id),
    part_name VARCHAR NOT NULL,
    brand VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    is_oe BOOLEAN DEFAULT FALSE,
    price_eur FLOAT,
    source VARCHAR DEFAULT 'piecesauto24',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(vehicle_id, part_name, brand, reference)
);

-- Compatible vehicles for a given part reference
CREATE TABLE part_vehicle_compatibility (
    id SERIAL PRIMARY KEY,
    reference_id INTEGER REFERENCES part_references(id),
    compatible_vehicle_name VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Screenshots stored locally
CREATE TABLE screenshots (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER REFERENCES vehicles(id),
    part_name VARCHAR,
    filename VARCHAR NOT NULL,
    screenshot_type VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Client request logs
CREATE TABLE requests_log (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    vehicle_id INTEGER,
    part_name VARCHAR,
    vin VARCHAR,
    vin_confidence VARCHAR,
    cdg_results_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

## VIN Decoding Logic

Two things decoded automatically for ALL brands (universal ISO standard):
- Characters 1-3 (WMI): brand + country. Hardcoded lookup table.
- Character 10: model year. Hardcoded lookup table.

For PSA brands ONLY (Peugeot, Citroen, DS), additionally:
- Characters 5-7: engine code (3 letters like KFU, 9HX, HMZ).
- Search this code in the vehicles table engine_code column.
- If found: automatic identification with HIGH confidence.

For ALL OTHER BRANDS:
- Search first 13 characters in vin_patterns table.
- If found: automatic identification.
- If not found: ask user (client) or operator to identify.
- Store new pattern after identification.

The bot explains its logic to the user:

PSA example:
"VIN: VF32KKFUF44254841
 VF3 = Peugeot (France)
 Caractere 10 = 4 = annee 2004
 Positions 5-7 = KFU = 1.4 16V 88ch Essence (famille ET3J4)
 Resultat: PEUGEOT 206 (2A/C) 1.4 16V 88CV Essence KFU"

Other brand example:
"VIN: KNADN512AL6123456
 KNA = Kia (Coree du Sud)
 Caractere 10 = L = annee 2020
 Le code moteur Kia est en position 8 (un seul caractere).
 Identification automatique non disponible pour cette marque.
 Pattern non trouve en base.
 Veuillez selectionner votre motorisation."

## WMI Table (hardcoded)

WMI_TABLE = {
    "VF3": "Peugeot", "VR3": "Peugeot",
    "VF7": "Citroen", "VR7": "Citroen",
    "VR1": "DS",
    "VF1": "Renault", "VF2": "Renault",
    "UU1": "Dacia", "VGA": "Dacia",
    "WVW": "Volkswagen", "WV2": "Volkswagen",
    "VSS": "Seat",
    "TMB": "Skoda",
    "KMH": "Hyundai", "MAL": "Hyundai",
    "KNA": "Kia", "KND": "Kia", "KNB": "Kia",
    "SB1": "Toyota", "JTD": "Toyota", "MR0": "Toyota",
    "WF0": "Ford",
    "ZFA": "Fiat", "ZFC": "Fiat",
    "TSM": "Suzuki", "JS2": "Suzuki",
    "JMB": "Mitsubishi", "JMY": "Mitsubishi",
    "SJN": "Nissan", "JN1": "Nissan",
    "JMZ": "Mazda",
    "MP1": "Isuzu",
    "LB3": "Geely", "L6T": "Geely",
    "LVT": "Chery", "LWD": "Chery",
    "LC0": "Haval", "LGX": "Haval",
    "LZW": "MG", "LSJ": "MG",
    "LA6": "Baic",
}

PSA_BRANDS = {"Peugeot", "Citroen", "DS"}

## Year Code Table (hardcoded)

YEAR_TABLE = {
    "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005,
    "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
    "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
    "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
    "S": 2025, "T": 2026,
}

---

# OPERATOR BOT

---

## Command: /ref — Add references from PiecesAuto24 screenshots

### Flow

Operator: /ref
Bot: "Envoyez les screenshots de la page PiecesAuto24.
      IMPORTANT: Le premier screenshot doit montrer le haut de la page
      avec le nom complet du vehicule et de la piece.
      Exemple de titre attendu:
      RIDEX 9F0009 Filtre a carburant
      avec en haut: PEUGEOT 208 II 3/5 portes (UB_, UP_...) 1.2 PureTech
      Envoyez le premier screenshot maintenant."

Operator: [sends screenshot 1]
Bot: [checks if screenshot contains vehicle name + part name at the top]
     If YES: "Vehicle: PEUGEOT 208 II (...) 1.2 PureTech
              Piece: Filtre a carburant
              Screenshot 1 recu.
              Voulez-vous envoyer d'autres screenshots ou lancer l'ingestion?
              [Envoyer un autre] [Lancer l'ingestion]"
     If NO: "Je ne detecte pas le nom du vehicule en haut du screenshot.
             Le premier screenshot doit montrer le titre de la page produit
             PiecesAuto24 avec le nom du vehicule. Reessayez."

Operator: [sends screenshot 2 - equivalents]
Bot: "Screenshot 2 recu. Envoyer un autre ou lancer l'ingestion?
      [Envoyer un autre] [Lancer l'ingestion]"

Operator: [sends screenshot 3 - cross refs]
Bot: "Screenshot 3 recu. Envoyer un autre ou lancer l'ingestion?
      [Envoyer un autre] [Lancer l'ingestion]"

Operator: [clicks Lancer l'ingestion]
Bot: [sends ALL screenshots to LLM vision for extraction]
Bot: "Extraction terminee:
      Vehicule: KIA Picanto (JA) 1.0 67CV Essence G4LA
      Piece: Filtre a huile
      Produit principal: RIDEX 7O0012 — 3.68 EUR
      References OE: 15400-RBA-F01, 2630035505, 46 544 820
      Equivalents extraits: 6
      Cross-references: 2
      Vehicules compatibles: 30+ marques
      Total: 23 references
      [Valider et enregistrer] [Annuler]"

Operator: [clicks Valider et enregistrer]
Bot: "23 references enregistrees pour
      KIA Picanto (JA) 1.0 67CV G4LA — Filtre a huile
      (8 nouvelles, 15 deja en base)"

### Screenshot storage
Screenshots saved locally:
screenshots/{vehicle_sanitized}/{part_sanitized}/screenshot_001.png
Plus data.json with same format as PIECES-AUTO-PARSER output.

### Folder and file naming rule
Use the EXACT vehicle name as displayed on PiecesAuto24 for folder names,
sanitized for filesystem (replace spaces with _, remove special chars except
parentheses and dots, lowercase).
Example: "KIA Rio III 3/5 portes (UB) 1.2 69 CV Essence G4LA"
becomes: kia_rio-iii_3-5-portes_(ub)_1.2_69cv_essence_g4la/
The full PiecesAuto24 name must be recoverable from the folder name.

### LLM Vision prompt for screenshot extraction

You are extracting auto part data from PiecesAuto24.com screenshots.
Extract ALL of the following if visible:
1. VEHICLE: the full vehicle name from the page header
2. PART: the part name and main product (brand + reference + price)
3. SPECS: technical specifications table (key-value pairs)
4. OE REFERENCES: original equipment references (field "Similaires a des numeros OE")
5. EQUIVALENTS: products under "Produits totalement equivalents" (brand, reference, price)
6. CROSS REFERENCES: table "pieces detachees possedant les memes caracteristiques" (brand, reference, price)
7. COMPATIBLE VEHICLES: all vehicles under "Vehicules concernes" (brand and full model name)

Return ONLY valid JSON with this structure:
{
  "vehicle": "...",
  "part_searched": "...",
  "product_scraped": {"brand": "...", "reference": "...", "name": "...", "price_eur": ..., "ean": "..."},
  "specs": {"key": "value"},
  "oe_references": [{"brand": "...", "ref": "..."}],
  "equivalents": [{"brand": "...", "reference": "...", "price_eur": ...}],
  "cross_references": [{"brand": "...", "reference": "...", "price_eur": ...}],
  "compatible_vehicles": [{"brand": "...", "models": ["..."]}]
}

---

## Command: /vin — Add VIN pattern to database

### Flow

Operator: /vin KNADN512AL6123456
Bot: "VIN: KNADN512AL6123456
      Decodage automatique:
      - KNA = Kia (Coree du Sud)
      - Caractere 10 = L = annee 2020
      - Code moteur: non identifiable automatiquement pour Kia
        (Kia encode le moteur en position 8 avec un seul caractere)
      - Pattern KNADN512AL612 non trouve en base.
      Selectionnez le vehicule:"

Bot: [inline buttons with ALL Kia vehicles in database]
     [Picanto (JA) 1.0 67CV Essence G4LA]
     [Rio IV (YB) 1.0 100CV Essence G3LC]
     ... (all Kia vehicles in DB)
     [Vehicule non liste]

Operator: [clicks a vehicle]
Bot: "Pattern KNADN512AL612 -> KIA Picanto (JA) 1.0 67CV Essence G4LA
      [Confirmer] [Annuler]"

Operator: [Confirmer]
Bot: "Enregistre."

### PSA auto-detection
Operator: /vin VF32KKFUF44254841
Bot: "VIN: VF32KKFUF44254841
      Decodage automatique:
      - VF3 = Peugeot (France)
      - Caractere 10 = 4 = annee 2004
      - Positions 5-7 = KFU
        Chez Peugeot/Citroen/DS, les positions 5-7 du VIN contiennent
        le code moteur a 3 lettres. KFU = 1.4 16V 88ch Essence (ET3J4)
      Vehicule identifie: PEUGEOT 206 (2A/C) 1.4 16V 88CV Essence KFU
      [Confirmer] [Corriger]"

### Unknown brand
If WMI not found: bot asks brand first, then model, then motorisation.
All via buttons from the database. ZERO free text input for vehicle identification.
If "Vehicule non liste" selected:
Bot: "Ce vehicule n'est pas dans la base. Ajoutez-le d'abord via /ref."

## Command: /stats
Bot: "Vehicules: X | References: X | Patterns VIN: X | Requetes aujourd'hui: X"

---

# CLIENT BOT

---

## Entry point

Client opens bot:
Bot: "Bienvenue! Comment identifier votre vehicule?
      [Photo carte grise] [Entrer VIN] [Choisir modele]"

## Path 1: Photo carte grise

Client sends photo -> LLM vision extracts VIN -> run VIN decode logic.
If vehicle identified: "Vehicule: PEUGEOT 206 ... C'est correct? [Oui] [Non]"
  Oui -> part selection
  Non -> Path 3
If not identified but brand/year found: show motorisations buttons for that brand
If unreadable: "Photo non lisible. [Reprendre photo] [Entrer VIN] [Choisir modele]"
MAX 1 RETRY on photo. After second failure -> force to Path 3.

## Path 2: Enter VIN

Client types VIN -> validate 17 chars no I/O/Q -> run VIN decode logic.
If invalid: "VIN invalide. [Reessayer] [Choisir modele]"
MAX 1 RETRY. After second failure -> force to Path 3.

## Path 3: Choisir modele (BUTTONS ONLY)

Bot: "Selectionnez la marque:" [Peugeot] [Kia] [Hyundai] [Renault] ...
-> Client clicks brand
Bot: "Selectionnez le modele:" [Picanto] [Rio] [Sportage] ...
   (only models in DB for that brand)
-> Client clicks model
Bot: "Selectionnez la motorisation:" [1.0 67CV Essence G4LA] [1.2 84CV Essence G4LA] ...
   (only motorisations in DB for that model)
-> Client clicks -> vehicle identified -> part selection

## Part selection (categories -> sub-categories, buttons)

Bot: "Que recherchez-vous?
      [Filtration] [Freinage] [Distribution] [Embrayage]
      [Suspension] [Electricite] [Moteur] [Autre]"

Categories mapping:
Filtration: Filtre a huile, Filtre a air, Filtre habitacle, Filtre a carburant
Freinage: Plaquettes frein avant/arriere, Disques frein avant/arriere
Distribution: Kit distribution, Courroie accessoire, Galet tendeur, Pompe a eau
Embrayage: Kit embrayage
Suspension: Amortisseur avant/arriere, Rotule direction, Biellette stabilisatrice, Roulement roue avant/arriere
Electricite: Bougies allumage/prechauffage, Bobine allumage, Demarreur, Alternateur, Sonde lambda
Moteur: Joint culasse, Thermostat, Radiateur, Vanne EGR

## Free text input (LLM interpretation)

At ANY point, client can type free text instead of clicking buttons.
LLM interprets franco-arabic:
"filtre zit" = Filtre a huile
"plakette frin" = Plaquettes de frein avant
"joint koulass" = Joint de culasse
"kourwa distribision" = Kit de distribution
"amortisor" = Amortisseur avant
"bouji" = Bougie d'allumage
"pompe lo" = Pompe a eau
"disque frin" = Disque de frein avant
"rotil" = Rotule de direction
"roulmon" = Roulement de roue avant
"ambriaj" = Kit embrayage
"demareur" = Demarreur
"alternatir" = Alternateur

LLM returns JSON: {"vin": ..., "vehicle_hint": ..., "part_name": ..., "raw_text": ...}

## CDG Search Logic

When vehicle + part identified:
1. Get ALL references for this vehicle + part from DB
2. Search reference 1 on CDG -> no result -> try next
3. Search reference 2 on CDG -> no result -> try next
4. Search reference 3 on CDG -> HIT! CDG shows this ref + all equivalents with prices
5. STOP. Display everything CDG returned.
6. If NO reference finds a hit: "Piece non disponible chez notre fournisseur."

Result format:
"KIA Picanto 1.0 67CV — Filtre a huile
 [DISPO] VALEO 586170 — 12.500 TND
 [DISPO] MANN W 7040 — 15.200 TND
 [RUPTURE] RIDEX 7O0012
 Autre piece? [Oui] [Non]"

## Session management

In-memory dict per telegram user_id:
- vehicle_id, vehicle_name, vin (optional), state, retry_count (max 1)
Vehicle stays active for subsequent part searches until changed.

---

## Build order (ONE AT A TIME)

Step 1:  Project init, deps, file structure, .env, schema.sql
         --- STOP ---

Step 2:  VIN decoder: WMI table, year table, PSA engine code search
         TEST: decode VF32KKFUF44254841 -> Peugeot 206 KFU 2004
         TEST: decode KNADN512AL6123456 -> Kia, 2020, engine unknown
         --- STOP ---

Step 3:  DB repository: vehicles CRUD, vin_patterns CRUD, part_references CRUD
         Seed DB with test vehicles from PiecesAuto24 data.json files
         --- STOP ---

Step 4:  Operator bot: /ref command only
         Screenshot collection, vehicle name detection, LLM extraction,
         JSON + DB + screenshot storage
         TEST: send screenshots, verify data.json output
         --- STOP ---

Step 5:  Operator bot: /vin command
         VIN decode with explanation, vehicle selection via buttons, pattern storage
         TEST: PSA VIN (auto) + Kia VIN (manual select)
         --- STOP ---

Step 6:  Client bot: vehicle identification
         Photo carte grise, manual VIN, model selection buttons
         Retry logic (max 1 then fallback)
         TEST: all three paths
         --- STOP ---

Step 7:  Client bot: part selection
         Category buttons + free text LLM interpretation
         TEST: buttons and free text
         --- STOP ---

Step 8:  CDG scraper: login, search by reference, parse results
         TEST: search a known reference on CDG
         --- STOP ---

Step 9:  Client bot: full chain
         Vehicle + part -> iterate refs on CDG -> display results
         TEST: end-to-end
         --- STOP ---

Step 10: Operator bot: /stats
         --- STOP ---

Start with Step 1. Stop after Step 1.

---

# OPERATOR NOTIFICATIONS (from client bot)

---

When the client bot cannot fulfill a request, it sends a notification to the
operator bot automatically. The operator receives these in their Telegram chat.

## Notification 1: Reference missing (no refs in DB)

To client:
"Nous recherchons cette piece pour vous.
 Vous recevrez une notification des que disponible."

To operator:
"-----------------------------
 REFERENCE MANQUANTE
-----------------------------
 Vehicule: KIA Picanto (JA) 1.0 67CV Essence G4LA
 Piece: Filtre a huile
 VIN: KNADN512AL6123456
 Client: @username
 
 Aucune reference en base pour cette combinaison.
 -> Ajoutez via /ref avec des screenshots PiecesAuto24
-----------------------------"

## Notification 2: CDG unavailable (refs exist but none found at CDG)

To client:
"Cette piece n'est pas disponible chez notre
 fournisseur actuellement. Nous vous notifierons
 si la situation change."

To operator:
"-----------------------------
 CDG INDISPONIBLE
-----------------------------
 Vehicule: KIA Picanto (JA) 1.0 67CV Essence G4LA
 Piece: Filtre a huile
 References testees (0/15 chez CDG):
 RIDEX 7O0012, MANN W 7040, VALEO 586170,
 STARK SKOF-0860011, HERTH+BUSS J1310507...
 
 -> Verifier si CDG distribue cette categorie
 -> Envisager un autre grossiste
-----------------------------"

## Notification 3: Unknown VIN (no pattern match, client identified via buttons)

To operator:
"-----------------------------
 NOUVEAU VIN
-----------------------------
 VIN: KNADN512AL6123456
 Identifie par le client comme:
 KIA Picanto (JA) 1.0 67CV Essence G4LA
 
 Pattern KNADN512AL612 enregistre automatiquement.
 -> Verifiez si correct via /vin
-----------------------------"

---

# TELEGRAM FORMATTING GUIDELINES

---

## Client bot: visual style

The client bot must feel clean, professional and easy to read on mobile.
Use Telegram MarkdownV2 formatting.

### Rules:
- Use bold for vehicle names and part names
- Use line breaks generously — never pack info into dense paragraphs
- Use checkmark and cross icons for availability (unicode, not emoji)
- Prices in bold
- Keep messages short. Split long content into multiple messages if needed.
- Use horizontal separators (dashes) between sections
- NEVER use emoji. Use unicode symbols only: check mark, cross, bullet, arrow

### Welcome message example:
"Bienvenue chez *PiecesAutoTN* !

Identifiez votre vehicule pour commencer :

  > Carte grise — envoyez une photo
  > VIN — tapez votre numero a 17 caracteres
  > Modele — selectionnez dans la liste"

### Vehicle confirmed example:
"Vehicule identifie :

*KIA Picanto (JA) 1.0 67CV Essence*
Annee : 2017 - 2023

Que recherchez-vous ?"

### CDG results example (the most important message):
"*KIA Picanto 1.0 67CV — Filtre a huile*
━━━━━━━━━━━━━━━━━━━━━

  En stock :
  > VALEO 586170 — *12.500 TND*
  > MANN-FILTER W 7040 — *15.200 TND*

  Rupture :
  > RIDEX 7O0012
  > STARK SKOF-0860011

━━━━━━━━━━━━━━━━━━━━━
Autre piece ? Tapez ou selectionnez."

### No results example:
"*KIA Picanto 1.0 67CV — Filtre a huile*
━━━━━━━━━━━━━━━━━━━━━

Piece non disponible actuellement.
Nous vous notifierons des qu'elle sera
en stock.

━━━━━━━━━━━━━━━━━━━━━
Autre piece ? Tapez ou selectionnez."

### VIN decode explanation example:
"Decodage VIN :

  VIN : VF32KKFUF44254841
  > VF3 = Peugeot (France)
  > Annee = 2004 (caractere 10 = 4)
  > Moteur = KFU (positions 5-7)
    1.4 16V 88ch Essence

Vehicule : *PEUGEOT 206 (2A/C) 1.4 16V 88CV*

C'est correct ?"

### Error / retry example:
"Le VIN saisi semble incorrect.
Verifiez qu'il contient 17 caracteres
(lettres et chiffres, sans I, O ou Q).

Reessayez ou choisissez une autre methode."

### Part category selection example:
"Selectionnez une categorie :

  > Filtration
  > Freinage
  > Distribution
  > Embrayage
  > Suspension
  > Electricite
  > Moteur"

## Operator bot: visual style

The operator bot is more functional, less styled. But still clean.
Use dashes for separators, clear labels, and structured layout.

