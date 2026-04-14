# VIN Tables: Research Approach and Lessons Learned

## Objective

Build local VIN decode tables mapping VIN positions to vehicle make, model, and engine
for the 12 most common car brands in Tunisia. The tables must be accurate enough to
reduce operator workload while never giving customers wrong information.

## VIN Structure Recap

A VIN is 17 characters. Positions 0-2 are the WMI (manufacturer). The remaining
positions encode model, engine, year, plant, and serial -- but the encoding is
**manufacturer-specific**. There is no universal standard for positions 3-8.

## Approach

### Phase 1: Initial build (wrong)

Generated tables from training data without verification. Produced 61 engine codes for
Peugeot with values like "KFU = 1.4 16V 88ch", "8HZ = 1.4 HDi 70ch",
"RFK = 2.0 16V 143ch". Marked many as HIGH confidence based on how confident the
LLM felt, not based on verified sources.

**Result:** When tested against a real VIN (VF7AAFHZ0H8876468 = Citroen Nemo), the
decoder returned a wrong model (C4 Picasso instead of Nemo) with HIGH confidence.
This proved that LLM confidence != data accuracy.

### Phase 2: Source verification

Fetched authoritative public sources for PSA engine codes:

| Source | URL | What it provided |
|--------|-----|------------------|
| Moteur PSA EB | fr.wikipedia.org/wiki/Moteur_PSA_EB | EB2 engine family: ZMZ, HMP, HMY, HMU, HMH, HMZ, HMR, HNK, HNZ, HNY, HNN |
| Moteur TU | fr.wikipedia.org/wiki/Moteur_TU | TU/ET3 family: CDY, CDZ, KFX, KFU, NFZ, NFU, NFS, NFP, NFX, etc. |
| Moteur DV/DLD | fr.wikipedia.org/wiki/Moteur_DV/DLD_PSA_/_Ford | DV4/DV6 diesel: 8HT, 8HX, 8HZ, 9HX, 9HZ, 9HP, BHY, BHZ, etc. |
| Moteur EW/DW | fr.wikipedia.org/wiki/Moteur_EW_/_DW | EW10/DW10/DW12: RFN, RFJ, RFK, RHY, RHZ, RHR, AH01, 4HL, etc. |
| Moteur EP | fr.wikipedia.org/wiki/Moteur_PSA/BMW_EP | EP6/Prince: 5FT, 5FX, 5FV, 5FM, 5GZ, 5FU, 5GT, N18, etc. |
| Wikibooks WMI | en.wikibooks.org/wiki/.../WMI | WMI codes per manufacturer |
| Web search | multiple | Confirmed HMG = EB2FAD 1.2 PureTech 75ch for 208 II |

### Phase 3: Corrections

Compared every entry against sources. The damage was extensive:

**20 wrong power values** (examples):
- 8HZ: 70ch -> 92ch (off by 31%)
- RFK: 143ch -> 177ch (off by 24%)
- 4HL: 130ch -> 204ch (off by 57%)
- BHY: 75ch -> 99ch
- BHW: 120ch -> 75ch (reversed with BHZ!)

**3 wrong engine families:**
- CDY/CDZ were labeled "1.0 VTi 68/72ch" but are actually TU9 0.95L 45/50ch
- NFS was labeled "1.6 VTi 120ch EP6" but is actually TU5 16V 125ch

**27 fabricated codes removed** (no source found):
HMT, HMV, HNR, HNS, HN0, HNB, 5FS, 5FW, 5G0, 8HR, 8HS, 9HC, 9HJ,
RHS, RHH, RHW, RHE, AHX, AHV, AHW, P22, 4HR, 4HM, RFG, KFV, KFT, KFZ

**39 verified codes added** from sources.

### Result

Before: 61 engines, 25 HIGH (40%), 36 MEDIUM (60%). Many HIGH values were wrong.
After: 87 engines, 86 HIGH (98%), 1 MEDIUM (1%). All HIGH verified against Wikipedia.

## Key Lessons

### 1. LLM confidence != data accuracy
The LLM was very confident about "KFU = 88ch" but the verified value is 90ch.
It was very confident about "8HZ = 70ch" but the real value is 92ch.
Confidence should mean "verified by a source", not "the LLM feels sure."

### 2. Better to have a gap than a wrong entry
A missing code returns MEDIUM confidence, which asks the customer to confirm.
A wrong code returns HIGH confidence with wrong data. Gaps are self-healing
(the operator fills them). Wrong data is actively harmful.

### 3. PSA is special
PSA (Peugeot/Citroen) encodes a unique 3-character engine type code at VIN
positions [5,6,7] that maps unambiguously to a specific engine. This is well
documented on French Wikipedia. No other manufacturer does this.

### 4. Non-PSA brands: model identification is the value
For VW, Renault, Hyundai, etc., VIN engine encoding uses 1 character which
is ambiguous (e.g., Renault "K" = both 1.5 dCi diesel and 1.6 petrol).
The real value is in MODEL identification. Returning "Golf VII, engine unknown,
MEDIUM confidence" is already useful -- the customer knows their engine.

### 5. VIN position mapping varies per manufacturer
- PSA: model=[3,4], engine=[5,6,7]
- VW group (VW, Seat, Skoda, Ford EU): model=[6,7], engine=[8] (ZZZ filler at 3-5)
- Renault/Dacia: model=[3,4], engine=[6]
- Hyundai/Kia: model=[3,4], engine=[7]
- Toyota: model=[3,4], engine=[6]
- Fiat: model=[3,4,5] (3-digit numeric), engine=[6]

### 6. French Wikipedia is the best source for PSA
English Wikipedia has engine family pages but NOT the 3-char VIN codes.
French Wikipedia (fr.wikipedia.org) has dedicated pages per engine family
(Moteur_PSA_EB, Moteur_TU, Moteur_DV/DLD, etc.) with the "repere moteur"
(engine marking codes) that correspond to VIN positions.

### 7. NHTSA API is useless for European cars
The NHTSA vPIC API only covers US-market vehicles. Tunisian-market cars
(mostly French/European) return empty results.

## How to add new codes

When the operator validates a VIN or the system encounters an unknown code:

1. Look up the 3-char engine code on French Wikipedia for PSA brands
2. Cross-reference with the specific model's Wikipedia page (e.g. Peugeot_208_II)
3. Search for the code on automotive parts sites (proxyparts.com, b-parts.com)
4. Only store with HIGH confidence if confirmed by at least one public source
5. Store with MEDIUM if only from operator validation (single data point)

## Current coverage

| Brand | Models | Engines | HIGH% | Source |
|-------|--------|---------|-------|--------|
| Peugeot | 37 | 87 | 98% | French Wikipedia |
| Citroen | 35 | 87 | 98% | French Wikipedia (same PSA engines) |
| Renault | 34 | 16 | 0% | Unverified single-char codes |
| Dacia | 13 | 10 | 0% | Unverified single-char codes |
| VW | 29 | 17 | 0% | Unverified single-char codes |
| Hyundai | 28 | 15 | 0% | Unverified single-char codes |
| Kia | 26 | 15 | 0% | Unverified single-char codes |
| Ford | 20 | 15 | 0% | Unverified single-char codes |
| Toyota | 19 | 15 | 0% | Unverified single-char codes |
| Skoda | 17 | 10 | 0% | Unverified single-char codes |
| Fiat | 14 | 13 | 0% | Unverified single-char codes |
| Seat | 13 | 10 | 0% | Unverified single-char codes |
