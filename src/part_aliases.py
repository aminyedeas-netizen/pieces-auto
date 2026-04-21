"""Part name aliases for normalizing user input and CDG search variants."""

import unicodedata


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


PART_ALIASES: dict[str, list[str]] = {
    # === FREINAGE ===
    "Plaquettes de frein avant": [
        "plaquettes frein avant", "plakettes avant", "plakat frin avant",
        "patins frein avant", "patins avant",
        "garnitures frein avant", "jeu plaquettes avant",
    ],
    "Plaquettes de frein arriere": [
        "plaquettes frein arriere", "plakat arriere",
        "patins frein arriere", "patins arriere",
        "garnitures frein arriere",
    ],
    "Disques de frein avant": [
        "disques frein avant", "disque avant",
        "plateau frein avant",
    ],
    "Disques de frein arriere": [
        "disques frein arriere", "disque arriere",
        "plateau frein arriere",
    ],
    "Etrier de frein avant": [
        "etrier avant", "etrier frein avant",
    ],
    "Etrier de frein arriere": [
        "etrier arriere", "etrier frein arriere",
    ],
    # === SUSPENSION ===
    "Amortisseur avant": [
        "amortisseur avant", "amortisor avant", "shock avant",
    ],
    "Amortisseur arriere": [
        "amortisseur arriere", "amortisor arriere", "shock arriere",
    ],
    "Biellette barre stabilisatrice": [
        "biellette stabilisatrice", "biel de suspension",
        "biellette anti roulis", "tirant barre stab",
        "biellette barre anti roulis",
    ],
    "Triangle de suspension": [
        "triangle", "traingle", "bras de suspension",
        "bras inferieur", "bras oscillant",
    ],
    "Silentbloc de triangle": [
        "silentbloc triangle", "silentbloc bras",
        "silent bloc", "bague triangle",
    ],
    "Butee amortisseur": [
        "toc amortisseur", "butee amortisseur",
        "coupelle amortisseur", "butee de suspension",
    ],
    "Roulement amortisseur": [
        "roulement amortisseur", "roulement coupelle",
        "roulement butee amortisseur", "roulement suspension",
    ],
    "Roulement de roue avant": [
        "roulement roue avant", "roulmon avant",
        "moyeu avant", "kit roulement avant",
    ],
    "Roulement de roue arriere": [
        "roulement roue arriere", "roulmon arriere",
        "moyeu arriere", "kit roulement arriere",
    ],
    # === DIRECTION ===
    "Rotule de direction": [
        "rotule direction", "rotil direction",
        "rotule axiale", "rotule exterieure",
        "rotule biellette direction",
    ],
    "Rotule de cremaillere": [
        "rotule cremaillere", "rotule interieure",
        "rotule de barre de direction",
        "rotule axiale interieure",
    ],
    "Rotule de suspension": [
        "rotule pivot", "rotule inferieure",
        "rotule de triangle", "rotule bras",
    ],
    "Soufflet de cremaillere": [
        "soufflet cremaillere", "soufflet direction",
        "cache poussiere cremaillere",
        "souflet cremaillere",
    ],
    # === DISTRIBUTION ===
    "Kit de distribution": [
        "kit distribution", "kit chaine", "kit courroie distribution",
        "kourwa distribision", "courroie distribution",
    ],
    "Galet tendeur distribution": [
        "galet tendeur", "tendeur distribution",
        "galet distribution",
    ],
    "Courroie d'accessoires": [
        "courroie accessoires", "courroie alternateur",
        "courroie poly v", "courroie striee",
    ],
    "Pompe a eau": [
        "pompe eau", "pompe lo", "pompe a eau",
        "pompe refroidissement",
    ],
    # === TRANSMISSION ===
    "Kit embrayage": [
        "embrayage", "ambriaj", "kit embrayage complet",
        "mecanisme embrayage", "disque embrayage",
    ],
    "Volant moteur": [
        "mayeu", "volant moteur", "volant bimasse",
        "volant embrayage", "volant mono masse",
    ],
    "Tete de cardan": [
        "tete cardan", "tete cardon", "joint homocinetique",
        "cardan cote roue", "bol cardan",
    ],
    "Soufflet de cardan": [
        "soufflet cardan", "soufflet transmission",
        "cache poussiere cardan",
    ],
    # === FILTRATION ===
    "Filtre a huile": [
        "filtre huile", "filtre zit", "filtre a huile",
    ],
    "Filtre a air": [
        "filtre air", "filtre hwa", "filtre a air",
    ],
    "Filtre habitacle": [
        "filtre habitacle", "filtre climatisation",
        "filtre pollen", "filtre interieur",
    ],
    "Filtre a carburant": [
        "filtre carburant", "filtre gasoil", "filtre essence",
        "filtre mazout",
    ],
    # === ALLUMAGE / PRECHAUFFAGE ===
    "Bougie d'allumage": [
        "bougie allumage", "bouji", "bougies",
        "bougie essence",
    ],
    "Bougie de prechauffage": [
        "bougie prechauffage", "bougie diesel",
        "crayon prechauffage",
    ],
    "Bobine d'allumage": [
        "bobine allumage", "bobine", "bobine haute tension",
    ],
    "Sonde lambda": [
        "sonde lambda", "capteur oxygene",
        "sonde echappement", "sonde o2",
    ],
    # === MOTEUR ===
    "Joint de culasse": [
        "joint culasse", "joint koulass", "joint de culasse",
    ],
    "Thermostat": [
        "thermostat", "calorstat", "thermostat eau",
    ],
    "Radiateur": [
        "radiateur", "radiateur moteur", "radiateur eau",
    ],
    "Vanne EGR": [
        "vanne egr", "valve egr", "egr",
    ],
    # === ELECTRIQUE ===
    "Demarreur": [
        "demarreur", "demareur", "demarreur moteur",
    ],
    "Alternateur": [
        "alternateur", "alternatir",
    ],
    # === ALIMENTATION ===
    "Pompe a carburant": [
        "pompe essence", "ecrou pompe essence",
        "pompe a essence", "pompe carburant",
        "pompe gasoil",
    ],
}

# Build reverse lookup: alias (normalized) -> standard name
_ALIAS_LOOKUP: dict[str, str] = {}
for _std, _aliases in PART_ALIASES.items():
    _key = _strip_accents(_std).lower().strip()
    _ALIAS_LOOKUP[_key] = _std
    for _alias in _aliases:
        _akey = _strip_accents(_alias).lower().strip()
        _ALIAS_LOOKUP[_akey] = _std


def resolve_part_name(user_input: str) -> str:
    """Resolve user input to the standard DB part name, or return as-is."""
    key = _strip_accents(user_input).lower().strip()
    return _ALIAS_LOOKUP.get(key, user_input)


def get_cdg_variants(part_name: str) -> list[str]:
    """Get CDG search variants from aliases for a given standard part name.

    Returns the standard name + all aliases (accent-stripped, uppercased).
    """
    key = _strip_accents(part_name).lower().strip()
    # Find the standard name
    std = _ALIAS_LOOKUP.get(key, part_name)
    aliases = PART_ALIASES.get(std, [])
    variants = [_strip_accents(std).upper()]
    for a in aliases:
        v = _strip_accents(a).upper()
        if v not in variants:
            variants.append(v)
    return variants
