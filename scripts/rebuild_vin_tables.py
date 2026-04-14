"""Rebuild VIN JSON tables with correct model-engine associations.

Fixes the cartesian product problem where every engine was paired with every model.
Each model now lists ONLY the engines it actually used.
"""

import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vin_tables")

# =============================================================================
# PSA ENGINES (shared by Peugeot and Citroen)
# All verified against French Wikipedia
# =============================================================================

PSA_ENGINES = {
    # -- 1.0 TU9 (1986-2005) --
    "CDY": {"desc": "1.0 TU9 45ch", "fuel": "Essence", "confidence": "high"},
    "CDZ": {"desc": "1.0 TU9 50ch", "fuel": "Essence", "confidence": "high"},

    # -- 1.1 TU1 (1988-2005) --
    "HDZ": {"desc": "1.1 TU1 60ch", "fuel": "Essence", "confidence": "high"},
    "HFX": {"desc": "1.1 TU1 60ch", "fuel": "Essence", "confidence": "high"},

    # -- 1.0 EB0 (2012+) --
    "ZMZ": {"desc": "1.0 VTi 68ch EB0", "fuel": "Essence", "confidence": "high"},

    # -- 1.2 EB2 (2012+) --
    "HMP": {"desc": "1.2 PureTech 68ch EB2", "fuel": "Essence", "confidence": "high"},
    "HMY": {"desc": "1.2 VTi 72ch EB2", "fuel": "Essence", "confidence": "high"},
    "HMU": {"desc": "1.2 VTi 75ch EB2", "fuel": "Essence", "confidence": "high"},
    "HMH": {"desc": "1.2 PureTech 75ch S&S EB2", "fuel": "Essence", "confidence": "high"},
    "HMG": {"desc": "1.2 PureTech 75ch S&S EB2", "fuel": "Essence", "confidence": "high"},
    "HMZ": {"desc": "1.2 VTi 82ch EB2", "fuel": "Essence", "confidence": "high"},
    "HMR": {"desc": "1.2 PureTech 83ch S&S EB2", "fuel": "Essence", "confidence": "high"},
    "HNK": {"desc": "1.2 PureTech 100ch Turbo EB2", "fuel": "Essence", "confidence": "high"},
    "HNZ": {"desc": "1.2 PureTech 110ch Turbo EB2", "fuel": "Essence", "confidence": "high"},
    "HNY": {"desc": "1.2 PureTech 130ch Turbo EB2", "fuel": "Essence", "confidence": "high"},
    "HNN": {"desc": "1.2 PureTech 136ch Turbo EB2", "fuel": "Essence", "confidence": "high"},

    # -- 1.4 TU3 (1986-2012) --
    "KDX": {"desc": "1.4 TU3 75ch", "fuel": "Essence", "confidence": "high"},
    "KFX": {"desc": "1.4 TU3 75ch", "fuel": "Essence", "confidence": "high"},
    "KFW": {"desc": "1.4 TU3 75ch", "fuel": "Essence", "confidence": "medium"},

    # -- 1.4 ET3 16V (2003-2012) --
    "KFU": {"desc": "1.4 ET3J4 16V 90ch", "fuel": "Essence", "confidence": "high"},

    # -- 1.6 TU5 (1994-2012) --
    "NFZ": {"desc": "1.6 TU5 90ch", "fuel": "Essence", "confidence": "high"},
    "NFR": {"desc": "1.6 TU5 16V 90ch", "fuel": "Essence", "confidence": "high"},
    "NFT": {"desc": "1.6 TU5 100ch", "fuel": "Essence", "confidence": "high"},
    "NFW": {"desc": "1.6 TU5 103ch", "fuel": "Essence", "confidence": "high"},
    "NFY": {"desc": "1.6 TU5 105ch", "fuel": "Essence", "confidence": "high"},
    "NFU": {"desc": "1.6 TU5 16V 110ch", "fuel": "Essence", "confidence": "high"},
    "NFP": {"desc": "1.6 EC5 VVT 115ch", "fuel": "Essence", "confidence": "high"},
    "NFX": {"desc": "1.6 TU5 16V 120ch", "fuel": "Essence", "confidence": "high"},
    "NFS": {"desc": "1.6 TU5 16V 125ch", "fuel": "Essence", "confidence": "high"},

    # -- 1.6 EP6/Prince (2006+) --
    "N18": {"desc": "1.6 VTi 122ch EP6C", "fuel": "Essence", "confidence": "high"},
    "5FA": {"desc": "1.6 THP 125ch EP6CDTD", "fuel": "Essence", "confidence": "high"},
    "5FT": {"desc": "1.6 THP 150ch EP6DT", "fuel": "Essence", "confidence": "high"},
    "5FX": {"desc": "1.6 THP 150ch EP6DT", "fuel": "Essence", "confidence": "high"},
    "5FV": {"desc": "1.6 THP 156ch EP6CDT", "fuel": "Essence", "confidence": "high"},
    "5FM": {"desc": "1.6 THP 160ch EP6CDTM", "fuel": "Essence", "confidence": "high"},
    "5FY": {"desc": "1.6 THP 175ch EP6DTS", "fuel": "Essence", "confidence": "high"},
    "5FD": {"desc": "1.6 THP 175ch EP6DTS", "fuel": "Essence", "confidence": "high"},
    "5GZ": {"desc": "1.6 THP 200ch EP6FDT", "fuel": "Essence", "confidence": "high"},
    "5FU": {"desc": "1.6 THP 250ch EP6CDTX", "fuel": "Essence", "confidence": "high"},
    "5GT": {"desc": "1.6 THP 270ch EP6FDTX", "fuel": "Essence", "confidence": "high"},
    "5GP": {"desc": "1.6 PureTech 180ch EP6FDTR", "fuel": "Essence", "confidence": "high"},

    # -- 1.8 EW7 (2000-2008) --
    "6FZ": {"desc": "1.8 EW7 16V 117ch", "fuel": "Essence", "confidence": "high"},

    # -- 2.0 EW10 (1998-2012) --
    "RFR": {"desc": "2.0 EW10 137ch", "fuel": "Essence", "confidence": "high"},
    "RFN": {"desc": "2.0 EW10 16V 138ch", "fuel": "Essence", "confidence": "high"},
    "RFM": {"desc": "2.0 EW10 138ch", "fuel": "Essence", "confidence": "high"},
    "RLZ": {"desc": "2.0 EW10 140ch injection directe", "fuel": "Essence", "confidence": "high"},
    "RFJ": {"desc": "2.0 EW10 16V 143ch", "fuel": "Essence", "confidence": "high"},
    "RFK": {"desc": "2.0 EW10 16V 177ch", "fuel": "Essence", "confidence": "high"},

    # -- 2.2 EW12 (2000-2005) --
    "3FZ": {"desc": "2.2 EW12 16V 158ch", "fuel": "Essence", "confidence": "high"},
    "3FY": {"desc": "2.2 EW12 16V 163ch", "fuel": "Essence", "confidence": "high"},

    # -- 1.4 HDi DV4 (2001-2015) --
    "8HT": {"desc": "1.4 HDi 54ch DV4TD", "fuel": "Diesel", "confidence": "high"},
    "8HX": {"desc": "1.4 HDi 68ch DV4TD", "fuel": "Diesel", "confidence": "high"},
    "8HZ": {"desc": "1.4 HDi 92ch DV4TD", "fuel": "Diesel", "confidence": "high"},
    "8HY": {"desc": "1.4 HDi 92ch DV4TED4", "fuel": "Diesel", "confidence": "high"},

    # -- 1.9 D DW8 (1998-2005) --
    "WJZ": {"desc": "1.9 D 68ch DW8", "fuel": "Diesel", "confidence": "high"},
    "WJY": {"desc": "1.9 D 71ch DW8", "fuel": "Diesel", "confidence": "high"},

    # -- 1.6 HDi DV6 (2004+) --
    "9HW": {"desc": "1.6 HDi 75ch DV6BTED4", "fuel": "Diesel", "confidence": "high"},
    "9HN": {"desc": "1.6 HDi 75ch DV6ETED", "fuel": "Diesel", "confidence": "high"},
    "9HV": {"desc": "1.6 HDi 90ch DV6ATED4", "fuel": "Diesel", "confidence": "high"},
    "9HX": {"desc": "1.6 HDi 90ch DV6ATED4", "fuel": "Diesel", "confidence": "high"},
    "9HF": {"desc": "1.6 HDi 90ch DV6DTED", "fuel": "Diesel", "confidence": "high"},
    "9HP": {"desc": "1.6 e-HDi 92ch DV6DTED", "fuel": "Diesel", "confidence": "high"},
    "9HY": {"desc": "1.6 HDi 110ch DV6TED4", "fuel": "Diesel", "confidence": "high"},
    "9HZ": {"desc": "1.6 HDi 110ch DV6TED4", "fuel": "Diesel", "confidence": "high"},
    "9HR": {"desc": "1.6 HDi 112ch DV6CTED", "fuel": "Diesel", "confidence": "high"},
    "9HD": {"desc": "1.6 HDi 115ch DV6FCTED", "fuel": "Diesel", "confidence": "high"},
    "9HL": {"desc": "1.6 HDi 115ch DV6FCTED", "fuel": "Diesel", "confidence": "high"},
    "9HG": {"desc": "1.6 HDi 115ch DV6FCTED", "fuel": "Diesel", "confidence": "high"},

    # -- 1.6 BlueHDi DV6 (2013+) --
    "BHW": {"desc": "1.6 BlueHDi 75ch DV6FETED", "fuel": "Diesel", "confidence": "high"},
    "BHV": {"desc": "1.6 BlueHDi 99ch DV6TED4", "fuel": "Diesel", "confidence": "high"},
    "BHY": {"desc": "1.6 BlueHDi 99ch DV6TED4", "fuel": "Diesel", "confidence": "high"},
    "BHX": {"desc": "1.6 BlueHDi 115ch DV6FCTED", "fuel": "Diesel", "confidence": "high"},
    "BHZ": {"desc": "1.6 BlueHDi 120ch DV6FCTED", "fuel": "Diesel", "confidence": "high"},

    # -- 2.0 HDi DW10 (1999-2015) --
    "RHY": {"desc": "2.0 HDi 90ch DW10TD", "fuel": "Diesel", "confidence": "high"},
    "RHX": {"desc": "2.0 HDi 94ch DW10", "fuel": "Diesel", "confidence": "high"},
    "RHZ": {"desc": "2.0 HDi 109ch DW10", "fuel": "Diesel", "confidence": "high"},
    "RHR": {"desc": "2.0 HDi 130ch DW10BTED4", "fuel": "Diesel", "confidence": "high"},
    "RH0": {"desc": "2.0 HDi 98ch DW10", "fuel": "Diesel", "confidence": "high"},
    "AH0": {"desc": "2.0 BlueHDi 136-180ch DW10", "fuel": "Diesel", "confidence": "high"},

    # -- 2.2 HDi DW12 (2000-2015) --
    "4HV": {"desc": "2.2 HDi 104ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HW": {"desc": "2.2 HDi 128ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HX": {"desc": "2.2 HDi 136ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HN": {"desc": "2.2 HDi 156ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HT": {"desc": "2.2 HDi 170ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HP": {"desc": "2.2 HDi 170ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HL": {"desc": "2.2 HDi 204ch DW12", "fuel": "Diesel", "confidence": "high"},
    "4HU": {"desc": "2.2 HDi 120-170ch DW12", "fuel": "Diesel", "confidence": "high"},
}

# =============================================================================
# PEUGEOT
# =============================================================================

PEUGEOT = {
    "constructor": "Peugeot",
    "wmi_codes": ["VF3", "VR3"],
    "model_positions": [3, 4],
    "engine_positions": [5, 6, 7],
    "vin_models": {
        "1A": "106", "1C": "106",
        "2A": "206", "2B": "206", "2K": "206",
        "2D": "206+",
        "2C": "207", "2E": "207",
        "2N": "208 I", "2P": "208 I",
        "UP": "208 II",
        "3A": "306", "3B": "306",
        "3C": "307", "3D": "307", "3E": "307",
        "3H": "308 I",
        "3J": "308 II",
        "4A": "Partner I", "4H": "Partner II",
        "5E": "508 I", "5F": "508 II",
        "6C": "405", "6D": "406", "6E": "407",
        "8D": "Expert II", "8E": "Expert III",
        "9D": "Boxer II", "9E": "Boxer III",
        "A0": "2008 I", "A5": "2008 II",
        "D2": "301",
        "K9": "Rifter",
        "T7": "3008 I", "T8": "3008 II", "T9": "5008 II",
        "Y1": "Traveller",
    },
    "models": {
        "106": {
            "years": [1991, 2003],
            "engines": [
                "CDY", "CDZ",       # 1.0 TU9
                "HDZ", "HFX",       # 1.1 TU1
                "KFX", "KFW", "KDX",# 1.4 TU3
                "NFZ",              # 1.6 TU5 90ch
                "NFX",              # 1.6 TU5 16V 120ch (S16)
                "NFS",              # 1.6 TU5 16V 125ch (S16 ph2)
            ],
        },
        "206": {
            "years": [1998, 2012],
            "engines": [
                "HDZ", "HFX",       # 1.1 TU1
                "KFX", "KFW", "KDX",# 1.4 TU3 8V
                "KFU",              # 1.4 ET3 16V 90ch
                "NFZ", "NFR",       # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "NFX", "NFS",       # 1.6 TU5 16V 120-125ch (RC/S16)
                "RFN", "RFR",       # 2.0 EW10 (GT/S16)
                "8HT", "8HX",       # 1.4 HDi
                "WJZ", "WJY",       # 1.9D DW8
                "9HX",              # 1.6 HDi 90ch (late 206/206+)
                "RHY",              # 2.0 HDi 90ch
            ],
        },
        "206+": {
            "years": [2009, 2013],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "8HX",              # 1.4 HDi 68ch
                "9HX",              # 1.6 HDi 90ch
            ],
        },
        "207": {
            "years": [2006, 2014],
            "engines": [
                "KFW", "KFX",       # 1.4 TU3 75ch
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "NFP",              # 1.6 EC5 VVT 115ch
                "N18",              # 1.6 VTi 120ch EP6
                "5FA",              # 1.6 THP 125ch
                "5FT", "5FX",       # 1.6 THP 150ch
                "5FY", "5FD",       # 1.6 THP 175ch (RC)
                "8HX",              # 1.4 HDi 68ch
                "8HZ",              # 1.4 HDi 92ch
                "9HV", "9HX",       # 1.6 HDi 90ch
                "9HN", "9HW",       # 1.6 HDi 75ch
                "9HY", "9HZ",       # 1.6 HDi 110ch
            ],
        },
        "208 I": {
            "years": [2012, 2019],
            "engines": [
                "ZMZ",              # 1.0 VTi 68ch EB0
                "HMP", "HMY", "HMU",# 1.2 EB2 68-75ch
                "HMH", "HMG",       # 1.2 PureTech 75ch S&S
                "HMZ", "HMR",       # 1.2 EB2 82-83ch
                "HNK",              # 1.2 PureTech 110ch turbo
                "HNZ",              # 1.2 PureTech 110ch turbo
                "HNY",              # 1.2 PureTech 130ch turbo
                "N18",              # 1.6 VTi 120ch (early 208)
                "5FT",              # 1.6 THP 150ch (208 XY)
                "5FV",              # 1.6 THP 156ch
                "5FY", "5FD",       # 1.6 THP 175ch (208 GTi early)
                "5GZ",              # 1.6 THP 200ch (208 GTi)
                "9HP",              # 1.6 e-HDi 92ch
                "9HD", "9HL", "9HG",# 1.6 HDi 115ch
                "BHW",              # 1.6 BlueHDi 75ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "208 II": {
            "years": [2019, 2025],
            "engines": [
                "HMG",              # 1.2 PureTech 75ch
                "HNK",              # 1.2 PureTech 100ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNN",              # 1.2 PureTech 136ch
                # 1.5 BlueHDi (DV5) not in our engine dict
            ],
        },
        "301": {
            "years": [2012, 2022],
            "engines": [
                "HMU", "HMG",       # 1.2 VTi/PureTech 75ch
                "N18",              # 1.6 VTi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "9HD",              # 1.6 HDi 115ch
                "BHY",              # 1.6 BlueHDi 99ch
            ],
        },
        "306": {
            "years": [1993, 2002],
            "engines": [
                "HDZ", "HFX",       # 1.1 TU1
                "KFX", "KFW", "KDX",# 1.4 TU3
                "NFZ", "NFR",       # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "NFX", "NFS",       # 1.6 TU5 16V 120-125ch (S16)
                "RFN",              # 2.0 EW10 16V
                "WJZ", "WJY",       # 1.9D DW8
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
            ],
        },
        "307": {
            "years": [2001, 2008],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "NFP",              # 1.6 EC5 VVT 115ch
                "6FZ",              # 1.8 EW7 16V 117ch
                "RFN", "RFJ",       # 2.0 EW10 16V 138-143ch
                "8HX",              # 1.4 HDi 68ch
                "8HZ",              # 1.4 HDi 92ch
                "9HV", "9HX",       # 1.6 HDi 90ch
                "9HY", "9HZ",       # 1.6 HDi 110ch
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
                "RHR",              # 2.0 HDi 136ch
            ],
        },
        "308 I": {
            "years": [2007, 2013],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FA",              # 1.6 THP 125ch
                "5FT", "5FX",       # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "5FY", "5FD",       # 1.6 THP 175ch (GTi)
                "9HX",              # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD", "9HL",       # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "RHR",              # 2.0 HDi 136ch
            ],
        },
        "308 II": {
            "years": [2013, 2021],
            "engines": [
                "HMZ",              # 1.2 VTi 82ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNY",              # 1.2 PureTech 130ch (later)
                "5FV",              # 1.6 THP 156ch
                "5GZ",              # 1.6 THP 200ch (308 GTi)
                "5FU",              # 1.6 THP 250ch (308 GTi)
                "5GT",              # 1.6 THP 270ch (308 GTi by PS)
                "9HD", "9HL", "9HG",# 1.6 HDi 115ch (early)
                "BHW",              # 1.6 BlueHDi 75ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHX",              # 1.6 BlueHDi 115ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
        "405": {
            "years": [1987, 1997],
            "engines": [
                "KFX", "KDX",       # 1.4 TU3
                "NFZ",              # 1.6 TU5 90ch
                # XU-series engines not in our dict
            ],
        },
        "406": {
            "years": [1995, 2004],
            "engines": [
                "NFZ",              # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "6FZ",              # 1.8 EW7 16V 117ch
                "RFN", "RFR",       # 2.0 EW10 137-138ch
                "RFJ",              # 2.0 EW10 16V 143ch
                "3FZ", "3FY",       # 2.2 EW12 16V 158-163ch
                "WJZ", "WJY",       # 1.9D DW8
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
                "RHR",              # 2.0 HDi 136ch (late 406)
                "4HX",              # 2.2 HDi 136ch
            ],
        },
        "407": {
            "years": [2004, 2011],
            "engines": [
                "NFU",              # 1.6 TU5 16V 110ch (base)
                "NFP",              # 1.6 EC5 VVT 115ch
                "N18",              # 1.6 VTi 120ch (late 407)
                "6FZ",              # 1.8 EW7 16V 117ch
                "RFN",              # 2.0 EW10 16V 138ch
                "RFJ",              # 2.0 EW10 16V 143ch
                "RFK",              # 2.0 EW10 16V 177ch
                "5FT",              # 1.6 THP 150ch (late 407)
                "9HZ",              # 1.6 HDi 110ch
                "9HY",              # 1.6 HDi 110ch
                "RHR",              # 2.0 HDi 136ch
                "RHZ",              # 2.0 HDi 109ch
                "4HX",              # 2.2 HDi 136ch
                "4HN",              # 2.2 HDi 156ch
                "4HT",              # 2.2 HDi 170ch
            ],
        },
        "508 I": {
            "years": [2010, 2018],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FT",              # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "5FX",              # 1.6 THP 150ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "RHR",              # 2.0 HDi 136ch (early)
                "AH0",              # 2.0 BlueHDi 150-180ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "4HN",              # 2.2 HDi 156ch (early)
                "4HT", "4HP",       # 2.2 HDi 170ch
            ],
        },
        "508 II": {
            "years": [2018, 2025],
            "engines": [
                "HNZ",              # 1.2 PureTech 130ch
                "HNY",              # 1.2 PureTech 130ch
                "5GP",              # 1.6 PureTech 180ch
                "AH0",              # 2.0 BlueHDi 160-180ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "Partner I": {
            "years": [1996, 2008],
            "engines": [
                "KFW", "KFX",       # 1.4 TU3 75ch
                "NFZ", "NFR",       # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "8HT", "8HX",       # 1.4 HDi
                "WJZ", "WJY",       # 1.9D DW8
                "9HW",              # 1.6 HDi 75ch
                "9HX",              # 1.6 HDi 90ch
                "RHY",              # 2.0 HDi 90ch
            ],
        },
        "Partner II": {
            "years": [2008, 2018],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "N18",              # 1.6 VTi 120ch
                "8HX",              # 1.4 HDi 68ch
                "9HX", "9HV",       # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "Expert II": {
            "years": [2007, 2016],
            "engines": [
                "9HX",              # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "RHR",              # 2.0 HDi 136ch
                "RHZ",              # 2.0 HDi 109ch
                "AH0",              # 2.0 BlueHDi (late)
                "4HU",              # 2.2 HDi 120-170ch
            ],
        },
        "Expert III": {
            "years": [2016, 2025],
            "engines": [
                "BHX",              # 1.6 BlueHDi 115ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
        "Boxer II": {
            "years": [2002, 2006],
            "engines": [
                "RHZ",              # 2.0 HDi 109ch
                "RHR",              # 2.0 HDi 136ch
                "4HV",              # 2.2 HDi 104ch
                "4HW",              # 2.2 HDi 128ch
                "4HX",              # 2.2 HDi 136ch
            ],
        },
        "Boxer III": {
            "years": [2006, 2025],
            "engines": [
                "RHR",              # 2.0 HDi 136ch (early)
                "AH0",              # 2.0 BlueHDi (late)
                "4HU",              # 2.2 HDi 120-170ch
                "4HN",              # 2.2 HDi 156ch
                "4HT", "4HP",       # 2.2 HDi 170ch
                "4HL",              # 2.2 HDi 204ch
            ],
        },
        "2008 I": {
            "years": [2013, 2019],
            "engines": [
                "ZMZ",              # 1.0 VTi 68ch
                "HMU",              # 1.2 VTi 75ch
                "HMZ",              # 1.2 VTi 82ch
                "HMR",              # 1.2 PureTech 83ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "N18",              # 1.6 VTi 120ch (early)
                "5FT",              # 1.6 THP 150ch (early)
                "9HP",              # 1.6 e-HDi 92ch
                "9HD", "9HG",       # 1.6 HDi 115ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "2008 II": {
            "years": [2019, 2025],
            "engines": [
                "HMG",              # 1.2 PureTech 75ch
                "HNK",              # 1.2 PureTech 100ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNN",              # 1.2 PureTech 136ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "Rifter": {
            "years": [2018, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "3008 I": {
            "years": [2009, 2016],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FA",              # 1.6 THP 125ch
                "5FT",              # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "RHR",              # 2.0 HDi 136ch
                "AH0",              # 2.0 BlueHDi (late)
            ],
        },
        "3008 II": {
            "years": [2016, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 130ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNY",              # 1.2 PureTech 130ch
                "5GP",              # 1.6 PureTech 180ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
        "5008 II": {
            "years": [2017, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 130ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNY",              # 1.2 PureTech 130ch
                "5GP",              # 1.6 PureTech 180ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
        "Traveller": {
            "years": [2016, 2025],
            "engines": [
                "BHX",              # 1.6 BlueHDi 115ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
    },
    "engines": PSA_ENGINES,
}

# =============================================================================
# CITROEN
# =============================================================================

CITROEN = {
    "constructor": "Citroen",
    "wmi_codes": ["VF7", "VR7"],
    "model_positions": [3, 4],
    "engine_positions": [5, 6, 7],
    "vin_models": {
        "SA": "Saxo",
        "LC": "C2",
        "FC": "C3 I", "SC": "C3 II", "SX": "C3 III",
        "LA": "Xsara", "LB": "Xsara Picasso",
        "NB": "C4 I", "NC": "C4 II", "NE": "C4 Cactus", "NX": "C4 III",
        "DC": "Xantia",
        "RE": "C5 I", "RD": "C5 II", "RW": "C5 III",
        "GA": "Berlingo I", "GB": "Berlingo II", "GJ": "Berlingo III",
        "EA": "Jumpy I", "EB": "Jumpy II", "EE": "Jumpy III",
        "YA": "Jumper I", "YB": "Jumper II", "YE": "Jumper III",
        "TB": "C8",
        "DD": "DS3", "DE": "DS4", "DF": "DS5",
        "N1": "C-Elysee",
        "A0": "C4 Aircross", "A5": "C3 Aircross",
        "JA": "C4 Picasso I", "JZ": "C4 SpaceTourer",
        "UA": "C5 Aircross",
        "AA": "Nemo",
    },
    "models": {
        "Saxo": {
            "years": [1996, 2004],
            "engines": [
                "CDY", "CDZ",       # 1.0 TU9
                "HDZ", "HFX",       # 1.1 TU1
                "KFX", "KFW", "KDX",# 1.4 TU3
                "NFZ",              # 1.6 TU5 90ch (SX)
                "NFX",              # 1.6 TU5 16V 120ch (VTS)
                "NFS",              # 1.6 TU5 16V 125ch (VTS ph2)
            ],
        },
        "C2": {
            "years": [2003, 2009],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "KFX", "KFW",       # 1.4 TU3 75ch
                "NFU",              # 1.6 TU5 16V 110ch (VTS)
                "NFS",              # 1.6 TU5 16V 125ch (VTS)
                "8HX",              # 1.4 HDi 68ch
            ],
        },
        "C3 I": {
            "years": [2002, 2009],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "KFX", "KFW",       # 1.4 TU3 75ch
                "NFU",              # 1.6 TU5 16V 110ch
                "8HX",              # 1.4 HDi 68ch
                "8HZ",              # 1.4 HDi 92ch
                "9HX",              # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
            ],
        },
        "C3 II": {
            "years": [2009, 2016],
            "engines": [
                "ZMZ",              # 1.0 VTi 68ch
                "HMP", "HMY", "HMU",# 1.2 EB2
                "HMH", "HMG",       # 1.2 PureTech 75ch
                "HMZ", "HMR",       # 1.2 EB2 82-83ch
                "HNK",              # 1.2 PureTech 110ch
                "KFU",              # 1.4 ET3 16V 90ch (early)
                "N18",              # 1.6 VTi 120ch
                "8HX",              # 1.4 HDi 68ch (early)
                "9HP",              # 1.6 e-HDi 92ch
                "9HD",              # 1.6 HDi 115ch
                "BHW",              # 1.6 BlueHDi 75ch
                "BHY",              # 1.6 BlueHDi 99ch
            ],
        },
        "C3 III": {
            "years": [2016, 2025],
            "engines": [
                "HMG",              # 1.2 PureTech 75ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "BHY",              # 1.6 BlueHDi 99ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "Xsara": {
            "years": [1997, 2006],
            "engines": [
                "HDZ", "HFX",       # 1.1 TU1
                "KFX", "KFW",       # 1.4 TU3
                "NFZ", "NFR",       # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "RFN",              # 2.0 EW10 16V
                "WJZ", "WJY",       # 1.9D DW8
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
            ],
        },
        "Xsara Picasso": {
            "years": [1999, 2012],
            "engines": [
                "NFU",              # 1.6 TU5 16V 110ch
                "NFP",              # 1.6 EC5 VVT 115ch
                "6FZ",              # 1.8 EW7 117ch
                "RFN",              # 2.0 EW10 16V 138ch
                "WJZ", "WJY",       # 1.9D DW8
                "8HX",              # 1.4 HDi 68ch
                "9HX",              # 1.6 HDi 90ch
                "9HY", "9HZ",       # 1.6 HDi 110ch
                "RHY",              # 2.0 HDi 90ch
            ],
        },
        "C4 I": {
            "years": [2004, 2010],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "N18",              # 1.6 VTi 120ch (late)
                "5FT",              # 1.6 THP 150ch (late)
                "RFN", "RFJ",       # 2.0 EW10 16V 138-143ch
                "8HX",              # 1.4 HDi 68ch
                "9HX",              # 1.6 HDi 90ch
                "9HY", "9HZ",       # 1.6 HDi 110ch
                "RHR",              # 2.0 HDi 136ch
            ],
        },
        "C4 II": {
            "years": [2010, 2018],
            "engines": [
                "HMZ",              # 1.2 VTi 82ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "N18",              # 1.6 VTi 120ch
                "5FA",              # 1.6 THP 125ch
                "5FV",              # 1.6 THP 156ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi
            ],
        },
        "C4 Cactus": {
            "years": [2014, 2020],
            "engines": [
                "HMZ",              # 1.2 VTi 82ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "BHW",              # 1.6 BlueHDi 75ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "C4 III": {
            "years": [2020, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 100ch
                "HNZ",              # 1.2 PureTech 130ch
                "HNN",              # 1.2 PureTech 136ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "Xantia": {
            "years": [1993, 2001],
            "engines": [
                "NFZ",              # 1.6 TU5 90ch
                "6FZ",              # 1.8 EW7 117ch
                "RFN",              # 2.0 EW10 16V 138ch
                "3FZ",              # 2.2 EW12 16V 158ch
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
            ],
        },
        "C5 I": {
            "years": [2001, 2004],
            "engines": [
                "NFU",              # 1.6 TU5 16V 110ch
                "6FZ",              # 1.8 EW7 117ch
                "RFN",              # 2.0 EW10 16V 138ch
                "3FZ", "3FY",       # 2.2 EW12 16V
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
                "RHR",              # 2.0 HDi 136ch
                "4HX",              # 2.2 HDi 136ch
            ],
        },
        "C5 II": {
            "years": [2004, 2008],
            "engines": [
                "NFU",              # 1.6 TU5 16V 110ch
                "6FZ",              # 1.8 EW7 117ch
                "RFN", "RFJ",       # 2.0 EW10 16V
                "RFK",              # 2.0 EW10 16V 177ch
                "3FZ", "3FY",       # 2.2 EW12 16V
                "9HY", "9HZ",       # 1.6 HDi 110ch
                "RHR",              # 2.0 HDi 136ch
                "RHZ",              # 2.0 HDi 109ch
                "4HX",              # 2.2 HDi 136ch
                "4HN",              # 2.2 HDi 156ch
                "4HT",              # 2.2 HDi 170ch
            ],
        },
        "C5 III": {
            "years": [2008, 2017],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FT",              # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "RFK",              # 2.0 EW10 16V 177ch (early)
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "RHR",              # 2.0 HDi 136ch
                "AH0",              # 2.0 BlueHDi
                "4HN",              # 2.2 HDi 156ch (early)
                "4HT", "4HP",       # 2.2 HDi 170ch
                "4HL",              # 2.2 HDi 204ch
            ],
        },
        "Berlingo I": {
            "years": [1996, 2008],
            "engines": [
                "KFW", "KFX",       # 1.4 TU3 75ch
                "NFZ", "NFR",       # 1.6 TU5 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "8HT", "8HX",       # 1.4 HDi
                "WJZ", "WJY",       # 1.9D DW8
                "9HW",              # 1.6 HDi 75ch
                "9HX",              # 1.6 HDi 90ch
            ],
        },
        "Berlingo II": {
            "years": [2008, 2018],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch
                "NFU",              # 1.6 TU5 16V 110ch
                "N18",              # 1.6 VTi 120ch
                "HNK",              # 1.2 PureTech 110ch (late)
                "8HX",              # 1.4 HDi 68ch
                "9HX", "9HV",       # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "Berlingo III": {
            "years": [2018, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "Jumpy I": {
            "years": [1995, 2006],
            "engines": [
                "NFZ",              # 1.6 TU5 90ch (base)
                "RFN",              # 2.0 EW10 16V
                "WJZ", "WJY",       # 1.9D DW8
                "RHY",              # 2.0 HDi 90ch
                "RHZ",              # 2.0 HDi 109ch
            ],
        },
        "Jumpy II": {
            "years": [2007, 2016],
            "engines": [
                "9HX",              # 1.6 HDi 90ch
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "RHR",              # 2.0 HDi 136ch
                "RHZ",              # 2.0 HDi 109ch
                "AH0",              # 2.0 BlueHDi (late)
                "4HU",              # 2.2 HDi 120-170ch
            ],
        },
        "Jumpy III": {
            "years": [2016, 2025],
            "engines": [
                "BHX",              # 1.6 BlueHDi 115ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150-180ch
            ],
        },
        "Jumper I": {
            "years": [1994, 2006],
            "engines": [
                "RHZ",              # 2.0 HDi 109ch
                "RHR",              # 2.0 HDi 136ch
                "4HV",              # 2.2 HDi 104ch
                "4HW",              # 2.2 HDi 128ch
                "4HX",              # 2.2 HDi 136ch
            ],
        },
        "Jumper II": {
            "years": [2006, 2014],
            "engines": [
                "RHR",              # 2.0 HDi 136ch (early)
                "4HU",              # 2.2 HDi 120-170ch
                "4HN",              # 2.2 HDi 156ch
                "4HT", "4HP",       # 2.2 HDi 170ch
            ],
        },
        "Jumper III": {
            "years": [2014, 2025],
            "engines": [
                "AH0",              # 2.0 BlueHDi
                "4HU",              # 2.2 HDi 120-170ch
                "4HN",              # 2.2 HDi 156ch
                "4HT", "4HP",       # 2.2 HDi 170ch
                "4HL",              # 2.2 HDi 204ch
            ],
        },
        "C8": {
            "years": [2002, 2014],
            "engines": [
                "RFN", "RFJ",       # 2.0 EW10 16V
                "9HZ",              # 1.6 HDi 110ch
                "RHR",              # 2.0 HDi 136ch
                "AH0",              # 2.0 BlueHDi (late)
                "4HX",              # 2.2 HDi 136ch (early)
                "4HN",              # 2.2 HDi 156ch
                "4HT",              # 2.2 HDi 170ch
            ],
        },
        "DS3": {
            "years": [2009, 2019],
            "engines": [
                "ZMZ",              # 1.0 VTi 68ch (late)
                "HMZ",              # 1.2 VTi 82ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "N18",              # 1.6 VTi 120ch
                "5FT", "5FX",       # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "5FY", "5FD",       # 1.6 THP 175ch (DS3 Racing)
                "5GZ",              # 1.6 THP 200ch (DS3 Racing)
                "9HP",              # 1.6 e-HDi 92ch
                "9HD",              # 1.6 HDi 115ch
                "BHW",              # 1.6 BlueHDi 75ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
            ],
        },
        "DS4": {
            "years": [2011, 2018],
            "engines": [
                "HNK",              # 1.2 PureTech 130ch
                "HNZ",              # 1.2 PureTech 130ch
                "N18",              # 1.6 VTi 120ch
                "5FV",              # 1.6 THP 156ch
                "5FM",              # 1.6 THP 160ch
                "5GZ",              # 1.6 THP 200ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi
            ],
        },
        "DS5": {
            "years": [2011, 2018],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FV",              # 1.6 THP 156ch
                "5FM",              # 1.6 THP 160ch
                "5GZ",              # 1.6 THP 200ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi
            ],
        },
        "C-Elysee": {
            "years": [2012, 2020],
            "engines": [
                "HMU", "HMG",       # 1.2 VTi/PureTech 75ch
                "N18",              # 1.6 VTi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "9HD",              # 1.6 HDi 115ch
                "BHY",              # 1.6 BlueHDi 99ch
            ],
        },
        "C4 Aircross": {
            "years": [2012, 2017],
            "engines": [
                "N18",              # 1.6 VTi 117ch
                "9HD",              # 1.6 HDi 115ch
                "AH0",              # 2.0 BlueHDi (rare, 4WD)
            ],
        },
        "C3 Aircross": {
            "years": [2017, 2025],
            "engines": [
                "HMG",              # 1.2 PureTech 82ch
                "HNK",              # 1.2 PureTech 110ch
                "HNZ",              # 1.2 PureTech 130ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                # 1.5 BlueHDi DV5 not in our dict
            ],
        },
        "C4 Picasso I": {
            "years": [2006, 2013],
            "engines": [
                "N18",              # 1.6 VTi 120ch
                "5FT",              # 1.6 THP 150ch
                "5FV",              # 1.6 THP 156ch
                "RFJ",              # 2.0 EW10 16V 143ch (early)
                "9HZ",              # 1.6 HDi 110ch
                "9HR",              # 1.6 HDi 112ch
                "9HD",              # 1.6 HDi 115ch
                "9HP",              # 1.6 e-HDi 92ch
                "RHR",              # 2.0 HDi 136ch
            ],
        },
        "C4 SpaceTourer": {
            "years": [2013, 2022],
            "engines": [
                "HNK",              # 1.2 PureTech 130ch
                "HNZ",              # 1.2 PureTech 130ch
                "5FV",              # 1.6 THP 156ch (early)
                "5GP",              # 1.6 PureTech 180ch
                "9HD",              # 1.6 HDi 115ch (early)
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 150ch
            ],
        },
        "C5 Aircross": {
            "years": [2018, 2025],
            "engines": [
                "HNK",              # 1.2 PureTech 130ch
                "HNZ",              # 1.2 PureTech 130ch
                "5GP",              # 1.6 PureTech 180ch
                "BHY",              # 1.6 BlueHDi 99ch
                "BHZ",              # 1.6 BlueHDi 120ch
                "AH0",              # 2.0 BlueHDi 180ch
            ],
        },
        "Nemo": {
            "years": [2008, 2017],
            "engines": [
                "KFU",              # 1.4 ET3 16V 90ch (petrol)
                "8HX",              # 1.4 HDi 68ch
                "8HZ",              # 1.4 HDi 75ch
            ],
        },
    },
    "engines": PSA_ENGINES,
}

# =============================================================================
# NON-PSA BRANDS (single-char engine codes, MEDIUM confidence)
# For these, engine codes map to broad categories.
# =============================================================================

RENAULT = {
    "constructor": "Renault",
    "wmi_codes": ["VF1", "VF2"],
    "model_positions": [3, 4],
    "engine_positions": [6],
    "vin_models": {
        "BB": "Clio II", "BR": "Clio III", "RS": "Clio III",
        "5R": "Clio IV", "BF": "Clio V",
        "BM": "Megane II", "KM": "Megane III", "RM": "Megane III",
        "RF": "Megane IV",
        "JM": "Scenic II", "JZ": "Scenic III", "RK": "Scenic IV",
        "FC": "Kangoo I", "FW": "Kangoo II", "FK": "Kangoo III",
        "BG": "Laguna II", "BT": "Laguna III",
        "LZ": "Fluence",
        "L8": "Symbol / Thalia",
        "J5": "Captur I", "JB": "Captur II",
        "HF": "Kadjar",
        "HJ": "Koleos II",
        "JD": "Master II", "MA": "Master III",
        "FL": "Trafic II", "FG": "Trafic III",
        "CN": "Twingo I", "CT": "Twingo II", "AH": "Twingo III",
        "BS": "Sandero I", "SD": "Sandero II",
        "HS": "Duster I", "HM": "Duster II",
        "LS": "Logan I", "L5": "Logan II",
        "LT": "Latitude",
        "JK": "Espace V",
        "RJ": "Talisman",
        "RH": "Arkana",
        "L7": "Logan (Renault)",
    },
    "models": {
        "Clio II":   {"years": [1998, 2012], "engines": ["P", "B", "C", "D", "K"]},
        "Clio III":  {"years": [2005, 2014], "engines": ["P", "B", "C", "D", "K", "F"]},
        "Clio IV":   {"years": [2012, 2019], "engines": ["H", "N", "F", "D", "K"]},
        "Clio V":    {"years": [2019, 2025], "engines": ["H", "N", "G", "D"]},
        "Megane II": {"years": [2002, 2009], "engines": ["B", "C", "D", "K", "A", "E"]},
        "Megane III":{"years": [2008, 2016], "engines": ["C", "F", "D", "K", "A", "E", "L"]},
        "Megane IV": {"years": [2016, 2025], "engines": ["F", "G", "D", "K", "L", "M"]},
        "Scenic II": {"years": [2003, 2009], "engines": ["B", "C", "D", "K", "E"]},
        "Scenic III":{"years": [2009, 2016], "engines": ["C", "F", "D", "K", "E"]},
        "Scenic IV": {"years": [2016, 2022], "engines": ["F", "G", "D", "K"]},
        "Kangoo I":  {"years": [1997, 2007], "engines": ["P", "B", "C", "D"]},
        "Kangoo II": {"years": [2008, 2021], "engines": ["C", "F", "D", "K"]},
        "Kangoo III":{"years": [2021, 2025], "engines": ["G", "D"]},
        "Laguna II": {"years": [2001, 2007], "engines": ["C", "D", "A", "E", "L"]},
        "Laguna III":{"years": [2007, 2015], "engines": ["C", "F", "D", "A", "E", "L"]},
        "Fluence":   {"years": [2009, 2017], "engines": ["C", "D", "K"]},
        "Symbol / Thalia": {"years": [2008, 2013], "engines": ["P", "B", "C", "D"]},
        "Captur I":  {"years": [2013, 2019], "engines": ["H", "F", "D", "K"]},
        "Captur II": {"years": [2019, 2025], "engines": ["N", "G", "D"]},
        "Kadjar":    {"years": [2015, 2022], "engines": ["F", "G", "D", "K"]},
        "Koleos II": {"years": [2017, 2025], "engines": ["G", "D"]},
        "Master II": {"years": [1998, 2010], "engines": ["E", "R"]},
        "Master III":{"years": [2010, 2025], "engines": ["E", "R"]},
        "Trafic II": {"years": [2001, 2014], "engines": ["D", "E"]},
        "Trafic III":{"years": [2014, 2025], "engines": ["D", "E"]},
        "Twingo I":  {"years": [1993, 2007], "engines": ["P", "B", "C"]},
        "Twingo II": {"years": [2007, 2014], "engines": ["P", "D"]},
        "Twingo III":{"years": [2014, 2024], "engines": ["H", "N"]},
        "Sandero I": {"years": [2008, 2012], "engines": ["P", "C", "D"]},
        "Sandero II":{"years": [2012, 2020], "engines": ["H", "N", "F", "D", "K"]},
        "Duster I":  {"years": [2010, 2017], "engines": ["C", "F", "D", "K"]},
        "Duster II": {"years": [2018, 2025], "engines": ["F", "G", "D", "K"]},
        "Logan I":   {"years": [2004, 2012], "engines": ["P", "B", "C", "D"]},
        "Logan II":  {"years": [2012, 2020], "engines": ["H", "N", "F", "D", "K"]},
        "Logan (Renault)": {"years": [2004, 2020], "engines": ["P", "B", "C", "D", "K"]},
        "Latitude":  {"years": [2010, 2015], "engines": ["C", "D", "E"]},
        "Espace V":  {"years": [2015, 2023], "engines": ["F", "G", "D", "E"]},
        "Talisman":  {"years": [2015, 2022], "engines": ["F", "G", "D", "E", "L"]},
        "Arkana":    {"years": [2021, 2025], "engines": ["G", "D"]},
    },
    "engines": {
        "H": {"desc": "1.0 SCe Essence", "fuel": "Essence", "confidence": "medium"},
        "N": {"desc": "1.0 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "P": {"desc": "1.2 Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.4 Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "F": {"desc": "1.2 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "G": {"desc": "1.3 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "L": {"desc": "1.8 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "M": {"desc": "2.0 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "1.5 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "K": {"desc": "1.5 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "A": {"desc": "1.6 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "E": {"desc": "2.0 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "R": {"desc": "2.3 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
    },
}

DACIA = {
    "constructor": "Dacia",
    "wmi_codes": ["UU1", "VGA"],
    "model_positions": [3, 4],
    "engine_positions": [6],
    "vin_models": {
        "SD": "Sandero I", "B5": "Sandero II", "BJ": "Sandero III",
        "LS": "Logan I", "L5": "Logan II", "LJ": "Logan III",
        "HS": "Duster I", "HM": "Duster II", "HN": "Duster III",
        "YS": "Lodgy", "FK": "Dokker",
        "6A": "Spring", "RJ": "Jogger",
        "KS": "Logan MCV",
    },
    "models": {
        "Sandero I":  {"years": [2008, 2012], "engines": ["P", "C", "D"]},
        "Sandero II": {"years": [2012, 2020], "engines": ["H", "N", "F", "D"]},
        "Sandero III":{"years": [2020, 2025], "engines": ["H", "N", "G", "D"]},
        "Logan I":    {"years": [2004, 2012], "engines": ["P", "C", "D"]},
        "Logan II":   {"years": [2012, 2020], "engines": ["H", "N", "F", "D"]},
        "Logan III":  {"years": [2020, 2025], "engines": ["H", "N", "G", "D"]},
        "Duster I":   {"years": [2010, 2017], "engines": ["C", "F", "D"]},
        "Duster II":  {"years": [2018, 2025], "engines": ["F", "G", "D"]},
        "Duster III": {"years": [2024, 2025], "engines": ["G", "D"]},
        "Lodgy":      {"years": [2012, 2022], "engines": ["F", "D"]},
        "Dokker":     {"years": [2012, 2021], "engines": ["F", "D"]},
        "Spring":     {"years": [2021, 2025], "engines": ["E"]},
        "Jogger":     {"years": [2022, 2025], "engines": ["H", "G"]},
        "Logan MCV":  {"years": [2006, 2020], "engines": ["P", "C", "F", "D"]},
    },
    "engines": {
        "H": {"desc": "1.0 SCe Essence", "fuel": "Essence", "confidence": "medium"},
        "N": {"desc": "1.0 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "P": {"desc": "1.2 Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "F": {"desc": "1.2 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "G": {"desc": "1.3 TCe Turbo Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "1.5 dCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "E": {"desc": "Electrique", "fuel": "Electrique", "confidence": "medium"},
    },
}

VOLKSWAGEN = {
    "constructor": "Volkswagen",
    "wmi_codes": ["WVW"],
    "model_positions": [6, 7],
    "engine_positions": [8],
    "vin_models": {
        "6R": "Polo V", "AW": "Polo VI",
        "1J": "Golf IV / Bora", "1K": "Golf V / Jetta III",
        "5K": "Golf VI", "AU": "Golf VII", "CD": "Golf VIII",
        "3C": "Passat B6 / B7", "3G": "Passat B8",
        "5N": "Tiguan I", "AD": "Tiguan II",
        "1T": "Touran I / II", "5T": "Touran III",
        "2K": "Caddy IV / V",
        "7H": "Transporter T5", "SG": "Transporter T6", "SH": "Transporter T6.1",
        "A1": "T-Roc", "C1": "T-Cross",
        "3H": "Arteon",
        "AA": "Up!",
        "7L": "Touareg I", "7P": "Touareg II", "CR": "Touareg III",
        "16": "Jetta V", "AJ": "Jetta VI",
        "13": "Scirocco III",
        "7N": "Sharan II",
        "9N": "Polo IV", "6N": "Polo III",
        "3B": "Passat B5",
    },
    "models": {
        "Polo III":     {"years": [1994, 2001], "engines": ["B", "C", "E", "S"]},
        "Polo IV":      {"years": [2001, 2009], "engines": ["A", "B", "C", "E", "F", "S"]},
        "Polo V":       {"years": [2009, 2017], "engines": ["A", "B", "C", "E", "F"]},
        "Polo VI":      {"years": [2017, 2025], "engines": ["A", "B", "E", "F"]},
        "Golf IV / Bora":      {"years": [1997, 2003], "engines": ["B", "C", "D", "E", "F", "G"]},
        "Golf V / Jetta III":  {"years": [2003, 2008], "engines": ["A", "B", "C", "D", "E", "F", "G"]},
        "Golf VI":      {"years": [2008, 2012], "engines": ["A", "B", "C", "D", "F", "G"]},
        "Golf VII":     {"years": [2012, 2019], "engines": ["A", "B", "D", "F", "G", "H"]},
        "Golf VIII":    {"years": [2019, 2025], "engines": ["A", "B", "D", "F", "G", "H"]},
        "Passat B5":    {"years": [1996, 2005], "engines": ["C", "D", "G", "N"]},
        "Passat B6 / B7":  {"years": [2005, 2014], "engines": ["C", "D", "G", "L", "N"]},
        "Passat B8":    {"years": [2014, 2025], "engines": ["D", "G", "H"]},
        "Tiguan I":     {"years": [2007, 2016], "engines": ["B", "D", "F", "G"]},
        "Tiguan II":    {"years": [2016, 2025], "engines": ["A", "D", "G", "H"]},
        "Touran I / II":{"years": [2003, 2015], "engines": ["B", "C", "D", "F", "G"]},
        "Touran III":   {"years": [2015, 2025], "engines": ["A", "D", "G"]},
        "Caddy IV / V": {"years": [2015, 2025], "engines": ["A", "D", "F", "G"]},
        "Transporter T5":  {"years": [2003, 2015], "engines": ["D", "G", "N"]},
        "Transporter T6":  {"years": [2015, 2019], "engines": ["D", "G"]},
        "Transporter T6.1":{"years": [2019, 2025], "engines": ["D", "G"]},
        "T-Roc":        {"years": [2017, 2025], "engines": ["A", "D", "G"]},
        "T-Cross":      {"years": [2018, 2025], "engines": ["A", "D"]},
        "Arteon":       {"years": [2017, 2025], "engines": ["D", "G"]},
        "Up!":          {"years": [2011, 2023], "engines": ["A"]},
        "Touareg I":    {"years": [2002, 2010], "engines": ["G", "N"]},
        "Touareg II":   {"years": [2010, 2018], "engines": ["D", "G", "N"]},
        "Touareg III":  {"years": [2018, 2025], "engines": ["G"]},
        "Jetta V":      {"years": [2005, 2010], "engines": ["B", "C", "D", "F", "G"]},
        "Jetta VI":     {"years": [2010, 2018], "engines": ["B", "D", "F", "G"]},
        "Scirocco III": {"years": [2008, 2017], "engines": ["B", "D", "G"]},
        "Sharan II":    {"years": [2010, 2022], "engines": ["D", "G"]},
        "Polo IV":      {"years": [2001, 2009], "engines": ["A", "B", "C", "E", "F", "S"]},
    },
    "engines": {
        "A": {"desc": "1.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2/1.4 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.4 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.5 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "L": {"desc": "2.2 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "N": {"desc": "2.5 / 3.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "S": {"desc": "1.4 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
    },
}

SEAT = {
    "constructor": "Seat",
    "wmi_codes": ["VSS"],
    "model_positions": [6, 7],
    "engine_positions": [8],
    "vin_models": {
        "6J": "Ibiza IV", "KJ": "Ibiza V",
        "1P": "Leon II / Toledo III", "5F": "Leon III", "KL": "Leon IV",
        "5P": "Altea",
        "7N": "Alhambra II",
        "KN": "Arona", "KM": "Ateca",
        "AA": "Mii",
        "KP": "Tarraco",
        "6L": "Ibiza III", "1M": "Leon I / Toledo II",
        "6K": "Cordoba II",
    },
    "models": {
        "Ibiza III":     {"years": [2002, 2008], "engines": ["B", "C", "E", "F"]},
        "Ibiza IV":      {"years": [2008, 2017], "engines": ["A", "B", "C", "E", "F"]},
        "Ibiza V":       {"years": [2017, 2025], "engines": ["A", "B", "F"]},
        "Leon I / Toledo II":  {"years": [1999, 2005], "engines": ["B", "C", "D", "F", "G"]},
        "Leon II / Toledo III":{"years": [2005, 2012], "engines": ["B", "C", "D", "F", "G"]},
        "Leon III":      {"years": [2012, 2020], "engines": ["A", "B", "D", "F", "G", "H"]},
        "Leon IV":       {"years": [2020, 2025], "engines": ["A", "D", "G", "H"]},
        "Altea":         {"years": [2004, 2015], "engines": ["B", "C", "D", "F", "G"]},
        "Alhambra II":   {"years": [2010, 2022], "engines": ["D", "G"]},
        "Arona":         {"years": [2017, 2025], "engines": ["A", "B", "F"]},
        "Ateca":         {"years": [2016, 2025], "engines": ["A", "D", "F", "G"]},
        "Mii":           {"years": [2011, 2021], "engines": ["A"]},
        "Tarraco":       {"years": [2018, 2025], "engines": ["D", "G"]},
        "Cordoba II":    {"years": [2002, 2009], "engines": ["B", "C", "E", "F"]},
    },
    "engines": {
        "A": {"desc": "1.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2/1.4 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.4 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.5 TSI Essence", "fuel": "Essence", "confidence": "medium"},
    },
}

SKODA = {
    "constructor": "Skoda",
    "wmi_codes": ["TMB"],
    "model_positions": [6, 7],
    "engine_positions": [8],
    "vin_models": {
        "6Y": "Fabia I", "5J": "Fabia II / Roomster",
        "NJ": "Fabia III", "PJ": "Fabia IV",
        "1Z": "Octavia II", "5E": "Octavia III", "NX": "Octavia IV",
        "3T": "Superb II", "3V": "Superb III",
        "NH": "Rapid", "NW": "Scala",
        "5L": "Yeti", "NU": "Karoq",
        "NS": "Kodiaq",
        "NE": "Kamiq",
        "1U": "Octavia I", "3U": "Superb I",
    },
    "models": {
        "Fabia I":       {"years": [1999, 2007], "engines": ["B", "C", "E", "F"]},
        "Fabia II / Roomster": {"years": [2007, 2015], "engines": ["A", "B", "C", "E", "F"]},
        "Fabia III":     {"years": [2014, 2021], "engines": ["A", "B", "F"]},
        "Fabia IV":      {"years": [2021, 2025], "engines": ["A", "H"]},
        "Octavia I":     {"years": [1996, 2004], "engines": ["B", "C", "F", "G"]},
        "Octavia II":    {"years": [2004, 2013], "engines": ["B", "C", "D", "F", "G"]},
        "Octavia III":   {"years": [2013, 2020], "engines": ["A", "B", "D", "F", "G", "H"]},
        "Octavia IV":    {"years": [2020, 2025], "engines": ["A", "D", "G", "H"]},
        "Superb I":      {"years": [2001, 2008], "engines": ["C", "D", "G"]},
        "Superb II":     {"years": [2008, 2015], "engines": ["B", "C", "D", "G"]},
        "Superb III":    {"years": [2015, 2025], "engines": ["B", "D", "G", "H"]},
        "Rapid":         {"years": [2012, 2019], "engines": ["A", "B", "F"]},
        "Scala":         {"years": [2019, 2025], "engines": ["A", "H"]},
        "Yeti":          {"years": [2009, 2017], "engines": ["B", "D", "F", "G"]},
        "Karoq":         {"years": [2017, 2025], "engines": ["A", "D", "G", "H"]},
        "Kodiaq":        {"years": [2017, 2025], "engines": ["D", "G"]},
        "Kamiq":         {"years": [2019, 2025], "engines": ["A", "H"]},
    },
    "engines": {
        "A": {"desc": "1.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2/1.4 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 TSI Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.4 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 TDI Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.5 TSI Essence", "fuel": "Essence", "confidence": "medium"},
    },
}

HYUNDAI = {
    "constructor": "Hyundai",
    "wmi_codes": ["KMH"],
    "model_positions": [3, 4],
    "engine_positions": [7],
    "vin_models": {
        "BA": "i10 I", "BB": "i10 II", "BI": "i10 III",
        "DA": "i20 I", "DB": "i20 II", "DI": "i20 III",
        "FD": "i30 FD", "GD": "i30 GD", "PD": "i30 PD",
        "CA": "Accent II", "CB": "Accent / Verna III",
        "CD": "Accent IV", "CI": "Accent V",
        "AA": "Elantra HD", "AB": "Elantra MD", "AD": "Elantra AD",
        "LM": "Tucson I (JM)", "TL": "ix35 / Tucson II",
        "N4": "Tucson III", "NX": "Tucson IV",
        "CM": "Santa Fe II (CM)", "DM": "Santa Fe III", "TM": "Santa Fe IV",
        "KN": "Kona", "KE": "Kona II",
        "EA": "Getz", "FA": "Matrix",
        "NF": "Sonata NF", "LF": "Sonata LF", "DN": "Sonata DN8",
        "HA": "H-1 / Starex",
        "GS": "Grand i10",
        "SU": "Creta", "BN": "Bayon", "QX": "Venue",
    },
    "models": {
        "i10 I":        {"years": [2008, 2013], "engines": ["A", "B"]},
        "i10 II":       {"years": [2013, 2019], "engines": ["A", "B"]},
        "i10 III":      {"years": [2019, 2025], "engines": ["A", "B"]},
        "i20 I":        {"years": [2008, 2014], "engines": ["B", "C", "E", "F"]},
        "i20 II":       {"years": [2014, 2020], "engines": ["A", "B", "C", "E", "F"]},
        "i20 III":      {"years": [2020, 2025], "engines": ["A", "B", "C"]},
        "i30 FD":       {"years": [2007, 2011], "engines": ["C", "D", "F", "G"]},
        "i30 GD":       {"years": [2012, 2017], "engines": ["C", "D", "F", "G"]},
        "i30 PD":       {"years": [2017, 2025], "engines": ["B", "C", "D", "F", "G"]},
        "Accent II":    {"years": [1999, 2005], "engines": ["B", "C"]},
        "Accent / Verna III": {"years": [2005, 2010], "engines": ["B", "C", "F"]},
        "Accent IV":    {"years": [2010, 2017], "engines": ["B", "C", "F"]},
        "Accent V":     {"years": [2017, 2025], "engines": ["B", "C"]},
        "Elantra HD":   {"years": [2006, 2010], "engines": ["C", "D", "F"]},
        "Elantra MD":   {"years": [2010, 2015], "engines": ["C", "D", "F"]},
        "Elantra AD":   {"years": [2016, 2020], "engines": ["C", "D", "F"]},
        "Tucson I (JM)":{"years": [2004, 2009], "engines": ["D", "G"]},
        "ix35 / Tucson II": {"years": [2010, 2015], "engines": ["C", "D", "F", "G"]},
        "Tucson III":   {"years": [2015, 2020], "engines": ["C", "D", "F", "G"]},
        "Tucson IV":    {"years": [2020, 2025], "engines": ["C", "D", "G", "H"]},
        "Santa Fe II (CM)": {"years": [2006, 2012], "engines": ["D", "G"]},
        "Santa Fe III": {"years": [2012, 2018], "engines": ["D", "G"]},
        "Santa Fe IV":  {"years": [2018, 2025], "engines": ["D", "G", "H"]},
        "Kona":         {"years": [2017, 2025], "engines": ["A", "B", "C", "F"]},
        "Kona II":      {"years": [2023, 2025], "engines": ["A", "B", "C", "H"]},
        "Getz":         {"years": [2002, 2011], "engines": ["A", "B", "E"]},
        "Matrix":       {"years": [2001, 2010], "engines": ["C", "F"]},
        "Grand i10":    {"years": [2013, 2019], "engines": ["A", "B"]},
        "Sonata NF":    {"years": [2005, 2010], "engines": ["D", "G"]},
        "Sonata LF":    {"years": [2014, 2019], "engines": ["D", "G"]},
        "Sonata DN8":   {"years": [2019, 2025], "engines": ["D", "H"]},
        "H-1 / Starex": {"years": [2007, 2025], "engines": ["G"]},
        "Creta":        {"years": [2015, 2025], "engines": ["B", "C", "F"]},
        "Bayon":        {"years": [2021, 2025], "engines": ["A", "B"]},
        "Venue":        {"years": [2019, 2025], "engines": ["A", "B"]},
    },
    "engines": {
        "A": {"desc": "1.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2 Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.1 Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 CRDi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 CRDi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.6 T-GDI / Hybride Essence", "fuel": "Essence", "confidence": "medium"},
    },
}

KIA = {
    "constructor": "Kia",
    "wmi_codes": ["KNA", "KND"],
    "model_positions": [3, 4],
    "engine_positions": [7],
    "vin_models": {
        "TA": "Picanto I", "TB": "Picanto II", "TI": "Picanto III",
        "DC": "Rio II", "DE": "Rio III", "YB": "Rio IV",
        "ED": "Ceed I", "JD": "Ceed II", "CD": "Ceed III",
        "TD": "Cerato / Forte II", "YD": "Cerato / Forte III",
        "SL": "Sportage III", "QL": "Sportage IV", "NQ": "Sportage V",
        "XM": "Sorento II", "UM": "Sorento III", "MQ": "Sorento IV",
        "YN": "Venga",
        "AM": "Soul I", "PS": "Soul II",
        "TF": "Optima / K5 III", "JF": "Optima / K5 IV", "DL": "K5 V",
        "UN": "Carens III", "RP": "Carens IV",
        "VQ": "Carnival III", "KA": "Carnival IV",
        "BD": "Stonic", "CG": "XCeed",
        "SG": "Niro", "CV": "Seltos",
    },
    "models": {
        "Picanto I":  {"years": [2004, 2011], "engines": ["A", "B"]},
        "Picanto II": {"years": [2011, 2017], "engines": ["A", "B"]},
        "Picanto III":{"years": [2017, 2025], "engines": ["A", "B"]},
        "Rio II":     {"years": [2005, 2011], "engines": ["B", "C", "E", "F"]},
        "Rio III":    {"years": [2011, 2017], "engines": ["B", "C", "E", "F"]},
        "Rio IV":     {"years": [2017, 2025], "engines": ["A", "B", "C", "F"]},
        "Ceed I":     {"years": [2006, 2012], "engines": ["C", "D", "F", "G"]},
        "Ceed II":    {"years": [2012, 2018], "engines": ["C", "D", "F", "G"]},
        "Ceed III":   {"years": [2018, 2025], "engines": ["B", "C", "D", "F", "G"]},
        "Cerato / Forte II":  {"years": [2009, 2013], "engines": ["C", "D", "F"]},
        "Cerato / Forte III": {"years": [2013, 2018], "engines": ["C", "D", "F"]},
        "Sportage III":{"years": [2010, 2015], "engines": ["C", "D", "G"]},
        "Sportage IV": {"years": [2016, 2021], "engines": ["C", "D", "F", "G"]},
        "Sportage V":  {"years": [2021, 2025], "engines": ["C", "D", "G", "H"]},
        "Sorento II":  {"years": [2009, 2014], "engines": ["D", "G"]},
        "Sorento III": {"years": [2015, 2020], "engines": ["D", "G"]},
        "Sorento IV":  {"years": [2020, 2025], "engines": ["D", "G", "H"]},
        "Venga":       {"years": [2010, 2019], "engines": ["B", "C", "F"]},
        "Soul I":      {"years": [2009, 2013], "engines": ["C", "F"]},
        "Soul II":     {"years": [2014, 2019], "engines": ["C", "F"]},
        "Optima / K5 III": {"years": [2010, 2015], "engines": ["D", "G"]},
        "Optima / K5 IV":  {"years": [2016, 2020], "engines": ["D", "G"]},
        "K5 V":        {"years": [2020, 2025], "engines": ["D", "H"]},
        "Carens III":  {"years": [2006, 2012], "engines": ["C", "D", "G"]},
        "Carens IV":   {"years": [2013, 2019], "engines": ["C", "D", "F", "G"]},
        "Carnival III":{"years": [2006, 2014], "engines": ["G"]},
        "Carnival IV": {"years": [2014, 2025], "engines": ["G"]},
        "Stonic":      {"years": [2017, 2025], "engines": ["A", "B", "C", "F"]},
        "XCeed":       {"years": [2019, 2025], "engines": ["B", "C", "D", "F", "G"]},
        "Niro":        {"years": [2016, 2025], "engines": ["H"]},
        "Seltos":      {"years": [2019, 2025], "engines": ["B", "C", "F"]},
    },
    "engines": {
        "A": {"desc": "1.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2 Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.1 CRDi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 CRDi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 CRDi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.6 T-GDI / Hybride Essence", "fuel": "Essence", "confidence": "medium"},
    },
}

TOYOTA = {
    "constructor": "Toyota",
    "wmi_codes": ["SB1", "JTD"],
    "model_positions": [3, 4],
    "engine_positions": [6],
    "vin_models": {
        "P1": "Yaris I", "P9": "Yaris II", "PJ": "Yaris III", "PA": "Yaris IV",
        "E1": "Corolla IX (E120)", "E1": "Corolla X (E140)",
        "ZR": "Corolla XI (E170)", "ZW": "Corolla XII",
        "ZE": "Auris I", "ZR": "Auris II",
        "T2": "Avensis II", "T2": "Avensis III",
        "A3": "RAV4 III", "A4": "RAV4 IV", "A5": "RAV4 V",
        "J1": "Land Cruiser 150", "J2": "Land Cruiser 200",
        "N2": "Hilux VII", "N3": "Hilux VIII",
        "X1": "C-HR", "B0": "Aygo I",
        "G3": "Camry XV70",
        "ZZ": "Corolla / Auris", "ZE": "Corolla / Auris",
        "ZW": "Corolla XII (E210)",
    },
    "models": {
        "Yaris I":    {"years": [1999, 2005], "engines": ["A", "B", "D"]},
        "Yaris II":   {"years": [2005, 2011], "engines": ["A", "B", "D"]},
        "Yaris III":  {"years": [2011, 2020], "engines": ["A", "B", "D", "H"]},
        "Yaris IV":   {"years": [2020, 2025], "engines": ["A", "H"]},
        "Corolla IX (E120)":  {"years": [2001, 2006], "engines": ["B", "C", "D"]},
        "Corolla X (E140)":   {"years": [2006, 2012], "engines": ["B", "C", "D"]},
        "Corolla XI (E170)":  {"years": [2013, 2019], "engines": ["B", "C", "D"]},
        "Corolla XII":        {"years": [2018, 2025], "engines": ["B", "C", "H"]},
        "Corolla XII (E210)": {"years": [2018, 2025], "engines": ["B", "C", "H"]},
        "Corolla / Auris":    {"years": [2006, 2018], "engines": ["B", "C", "D", "H"]},
        "Auris I":    {"years": [2006, 2012], "engines": ["B", "C", "D", "H"]},
        "Auris II":   {"years": [2012, 2018], "engines": ["B", "C", "D", "H"]},
        "Avensis II": {"years": [2003, 2008], "engines": ["C", "D", "E"]},
        "Avensis III":{"years": [2009, 2018], "engines": ["C", "D", "E"]},
        "RAV4 III":   {"years": [2005, 2012], "engines": ["C", "D", "E"]},
        "RAV4 IV":    {"years": [2013, 2018], "engines": ["C", "D", "E"]},
        "RAV4 V":     {"years": [2018, 2025], "engines": ["C", "H"]},
        "Land Cruiser 150": {"years": [2009, 2025], "engines": ["E", "F"]},
        "Land Cruiser 200": {"years": [2007, 2021], "engines": ["F"]},
        "Hilux VII":  {"years": [2005, 2015], "engines": ["E"]},
        "Hilux VIII": {"years": [2015, 2025], "engines": ["E"]},
        "C-HR":       {"years": [2016, 2025], "engines": ["B", "C", "H"]},
        "Aygo I":     {"years": [2005, 2014], "engines": ["A"]},
        "Camry XV70": {"years": [2017, 2025], "engines": ["C", "H"]},
    },
    "engines": {
        "A": {"desc": "1.0 Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.2/1.3 Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6/1.8 Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "1.4 D-4D Diesel", "fuel": "Diesel", "confidence": "medium"},
        "E": {"desc": "2.0/2.2 D-4D Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "2.8/3.0 D-4D Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "Hybride Essence", "fuel": "Essence", "confidence": "medium"},
    },
}

FORD = {
    "constructor": "Ford",
    "wmi_codes": ["WF0"],
    "model_positions": [6, 7],
    "engine_positions": [8],
    "vin_models": {
        "AX": "Ka II",
        "WF": "Fiesta VI / VII", "JH": "Fiesta VIII",
        "DA": "Focus I", "DB": "Focus II / C-Max I",
        "GC": "Focus III", "GE": "Focus IV",
        "GB": "Mondeo IV", "GD": "Mondeo V",
        "GA": "C-Max II / Grand C-Max",
        "DR": "Kuga I", "UW": "Kuga I", "ZG": "Kuga II / III",
        "E1": "EcoSport", "CX": "Puma",
        "AB": "Transit Custom", "AH": "Transit Connect", "TT": "Transit",
        "FA": "Galaxy II", "FD": "S-Max I / II",
    },
    "models": {
        "Ka II":       {"years": [2008, 2016], "engines": ["A", "B", "S"]},
        "Fiesta VI / VII": {"years": [2008, 2017], "engines": ["A", "B", "C", "E", "F", "S"]},
        "Fiesta VIII": {"years": [2017, 2023], "engines": ["A", "H", "K", "E", "M"]},
        "Focus I":     {"years": [1998, 2004], "engines": ["B", "C", "F", "G"]},
        "Focus II / C-Max I": {"years": [2004, 2011], "engines": ["B", "C", "D", "F", "G"]},
        "Focus III":   {"years": [2011, 2018], "engines": ["A", "C", "D", "E", "F", "G"]},
        "Focus IV":    {"years": [2018, 2025], "engines": ["A", "H", "J", "M"]},
        "Mondeo IV":   {"years": [2007, 2014], "engines": ["C", "D", "F", "G", "N"]},
        "Mondeo V":    {"years": [2014, 2022], "engines": ["D", "G", "J"]},
        "C-Max II / Grand C-Max": {"years": [2010, 2019], "engines": ["A", "C", "E", "F", "G"]},
        "Kuga I":      {"years": [2008, 2012], "engines": ["D", "G"]},
        "Kuga II / III": {"years": [2012, 2025], "engines": ["A", "D", "E", "G", "J"]},
        "EcoSport":    {"years": [2013, 2022], "engines": ["A", "E"]},
        "Puma":        {"years": [2019, 2025], "engines": ["A", "H", "K", "M"]},
        "Transit Custom": {"years": [2013, 2025], "engines": ["G", "J"]},
        "Transit Connect": {"years": [2002, 2025], "engines": ["E", "F", "G", "J"]},
        "Transit":     {"years": [2000, 2025], "engines": ["G", "J", "L"]},
        "Galaxy II":   {"years": [2006, 2015], "engines": ["C", "D", "G"]},
        "S-Max I / II":{"years": [2006, 2025], "engines": ["C", "D", "G", "J"]},
    },
    "engines": {
        "A": {"desc": "1.0 EcoBoost Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.25/1.4 Duratec Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.6 Ti-VCT/Duratec Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "2.0 GDi/EcoBoost Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.5 TDCi/EcoBlue Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 TDCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 TDCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.5 EcoBoost Essence", "fuel": "Essence", "confidence": "medium"},
        "J": {"desc": "2.0 EcoBlue Diesel", "fuel": "Diesel", "confidence": "medium"},
        "K": {"desc": "1.0 EcoBoost Hybride Essence", "fuel": "Essence", "confidence": "medium"},
        "L": {"desc": "2.2 TDCi Diesel", "fuel": "Diesel", "confidence": "medium"},
        "M": {"desc": "1.5 EcoBlue Diesel", "fuel": "Diesel", "confidence": "medium"},
        "N": {"desc": "2.5 Duratec Essence", "fuel": "Essence", "confidence": "medium"},
        "S": {"desc": "1.4 TDCi Diesel", "fuel": "Diesel", "confidence": "medium"},
    },
}

FIAT = {
    "constructor": "Fiat",
    "wmi_codes": ["ZFA"],
    "model_positions": [3, 4, 5],
    "engine_positions": [6],
    "vin_models": {
        "169": "Panda II",
        "312": "Panda III / 500",
        "343": "Panda III",
        "150": "500 II",
        "334": "500L",
        "356": "500X",
        "188": "Punto II",
        "199": "Grande Punto / Punto Evo",
        "330": "Tipo",
        "225": "Fiorino / Qubo",
        "263": "Doblo II",
        "250": "Ducato III",
        "290": "Ducato III",
        "198": "Bravo II / Linea",
    },
    "models": {
        "Panda II":      {"years": [2003, 2011], "engines": ["A", "B", "D", "E"]},
        "Panda III / 500": {"years": [2011, 2025], "engines": ["A", "D", "H", "N", "E"]},
        "Panda III":     {"years": [2011, 2025], "engines": ["A", "D", "H", "N", "E"]},
        "500 II":        {"years": [2007, 2025], "engines": ["A", "D", "H", "N", "E"]},
        "500L":          {"years": [2012, 2022], "engines": ["D", "H", "E", "F"]},
        "500X":          {"years": [2014, 2025], "engines": ["C", "D", "E", "F", "G"]},
        "Punto II":      {"years": [1999, 2010], "engines": ["A", "B", "E", "F"]},
        "Grande Punto / Punto Evo": {"years": [2005, 2018], "engines": ["A", "B", "C", "D", "E", "F"]},
        "Tipo":          {"years": [2015, 2025], "engines": ["B", "C", "D", "E", "F"]},
        "Fiorino / Qubo":{"years": [2007, 2022], "engines": ["A", "B", "E"]},
        "Doblo II":      {"years": [2010, 2022], "engines": ["B", "C", "E", "F"]},
        "Ducato III":    {"years": [2006, 2025], "engines": ["G", "K", "L"]},
        "Bravo II / Linea": {"years": [2007, 2014], "engines": ["B", "C", "E", "F"]},
    },
    "engines": {
        "A": {"desc": "1.2 8V Fire Essence", "fuel": "Essence", "confidence": "medium"},
        "B": {"desc": "1.4 8V Fire Essence", "fuel": "Essence", "confidence": "medium"},
        "C": {"desc": "1.4 16V MultiAir Essence", "fuel": "Essence", "confidence": "medium"},
        "D": {"desc": "0.9 TwinAir Essence", "fuel": "Essence", "confidence": "medium"},
        "E": {"desc": "1.3 MultiJet Diesel", "fuel": "Diesel", "confidence": "medium"},
        "F": {"desc": "1.6 MultiJet Diesel", "fuel": "Diesel", "confidence": "medium"},
        "G": {"desc": "2.0 MultiJet Diesel", "fuel": "Diesel", "confidence": "medium"},
        "H": {"desc": "1.0 FireFly Essence", "fuel": "Essence", "confidence": "medium"},
        "J": {"desc": "1.6 E-Torq Essence", "fuel": "Essence", "confidence": "medium"},
        "K": {"desc": "2.3 MultiJet Diesel", "fuel": "Diesel", "confidence": "medium"},
        "L": {"desc": "3.0 MultiJet Diesel", "fuel": "Diesel", "confidence": "medium"},
        "N": {"desc": "1.0 FireFly Hybride Essence", "fuel": "Essence", "confidence": "medium"},
    },
}


# =============================================================================
# Generate all JSON files
# =============================================================================

ALL_BRANDS = [
    ("peugeot.json", PEUGEOT),
    ("citroen.json", CITROEN),
    ("renault.json", RENAULT),
    ("dacia.json", DACIA),
    ("volkswagen.json", VOLKSWAGEN),
    ("seat.json", SEAT),
    ("skoda.json", SKODA),
    ("hyundai.json", HYUNDAI),
    ("kia.json", KIA),
    ("toyota.json", TOYOTA),
    ("ford.json", FORD),
    ("fiat.json", FIAT),
]


def write_json(filename, data):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {path}")


def generate_csv():
    """Generate vehicles.csv from the new JSON structure."""
    import csv

    rows = []
    for filename, data in ALL_BRANDS:
        brand = data["constructor"]
        engines_dict = data["engines"]
        for model_name, model_info in data["models"].items():
            y_start, y_end = model_info["years"]
            for eng_code in model_info["engines"]:
                eng = engines_dict.get(eng_code)
                if not eng:
                    print(f"  WARNING: {brand} {model_name} references unknown engine {eng_code}")
                    continue
                rows.append({
                    "brand": brand,
                    "model": model_name,
                    "year_start": y_start,
                    "year_end": y_end,
                    "engine_code": eng_code,
                    "engine_desc": eng["desc"],
                    "fuel": eng.get("fuel", ""),
                    "confidence": eng.get("confidence", "medium"),
                })

    csv_path = os.path.join(OUTPUT_DIR, "..", "..", "vehicles.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "brand", "model", "year_start", "year_end",
            "engine_code", "engine_desc", "fuel", "confidence",
        ])
        w.writeheader()
        w.writerows(rows)

    return rows


def validate(rows):
    """Run sanity checks on the generated data."""
    errors = []
    for r in rows:
        model = r["model"]
        y_end = int(r["year_end"])
        desc = r["engine_desc"].lower()
        brand = r["brand"]

        # Timeline checks
        if y_end < 2006 and "thp" in desc:
            errors.append(f"THP in pre-2006 {brand} {model}")
        if y_end < 2012 and "puretech" in desc:
            errors.append(f"PureTech in pre-2012 {brand} {model}")
        if y_end < 2013 and "bluehdi" in desc:
            errors.append(f"BlueHDi in pre-2013 {brand} {model}")
        if y_end < 2012 and "eb2" in desc:
            errors.append(f"EB2 in pre-2012 {brand} {model}")

        # Size checks for small cars
        small_cars = {"106", "Saxo", "C2", "Aygo I", "i10 I", "i10 II", "i10 III",
                      "Picanto I", "Picanto II", "Picanto III", "Up!", "Mii",
                      "Panda II", "500 II", "Twingo I", "Twingo II", "Twingo III",
                      "Ka II", "Grand i10", "Getz", "Bayon", "Venue"}
        if model in small_cars:
            # Extract displacement
            for part in desc.split():
                if part.replace(".", "").replace(",", "").isdigit():
                    disp = float(part.replace(",", "."))
                    if disp > 1.6:
                        errors.append(f"Engine >1.6L ({desc}) in small car {brand} {model}")
                    break

        # Vans should not have tiny engines
        vans = {"Boxer II", "Boxer III", "Jumper I", "Jumper II", "Jumper III",
                "Ducato III", "Transit", "Master II", "Master III",
                "H-1 / Starex", "Carnival III", "Carnival IV"}
        if model in vans:
            for part in desc.split():
                if part.replace(".", "").replace(",", "").isdigit():
                    disp = float(part.replace(",", "."))
                    if disp < 1.4 and "electr" not in desc:
                        errors.append(f"Engine <1.4L ({desc}) in van {brand} {model}")
                    break

    return errors


def print_model_engines(rows, brand, model):
    """Print all engines for a specific model."""
    model_engines = [r for r in rows if r["brand"] == brand and r["model"] == model]
    print(f"\n  {brand} {model} ({len(model_engines)} engines):")
    for r in model_engines:
        print(f"    {r['engine_code']}: {r['engine_desc']} ({r['fuel']})")


if __name__ == "__main__":
    print("Generating VIN JSON files...")
    for filename, data in ALL_BRANDS:
        write_json(filename, data)

    print("\nGenerating vehicles.csv...")
    rows = generate_csv()

    print(f"\nTotal rows: {len(rows)}")
    print(f"Unique brands: {len(set(r['brand'] for r in rows))}")
    print(f"Unique models: {len(set((r['brand'], r['model']) for r in rows))}")

    # Per-brand stats
    print("\nPer brand:")
    for filename, data in ALL_BRANDS:
        brand = data["constructor"]
        brand_rows = [r for r in rows if r["brand"] == brand]
        models = set(r["model"] for r in brand_rows)
        engines = set(r["engine_code"] for r in brand_rows)
        print(f"  {brand}: {len(models)} models, {len(engines)} engines, {len(brand_rows)} rows")

    # Validation
    print("\nValidation:")
    errors = validate(rows)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
    else:
        print("  All checks passed!")

    # Specific model checks
    print_model_engines(rows, "Citroen", "Saxo")
    print_model_engines(rows, "Peugeot", "106")
    print_model_engines(rows, "Peugeot", "206")
    print_model_engines(rows, "Peugeot", "208 II")
