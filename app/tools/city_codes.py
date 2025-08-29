# app/tools/city_codes.py

from __future__ import annotations
from typing import Dict, List, Set, Tuple
import re
import unicodedata

# --- Minimal but high-signal catalog (expand anytime) -------------------------
# Each entry may be:
#   - a CITY (maps to one or more airports, incl. metro codes),
#   - a METRO code (e.g., LON -> [LHR, LGW, LCY, LTN, STN, SEN]),
#   - or a single AIRPORT code.
#
# IMPORTANT: You can safely extend these dicts without changing any code elsewhere.

CITY_TO_AIRPORTS: Dict[str, List[str]] = {
    # UK / Europe
    "london": ["LON", "LHR", "LGW", "LCY", "LTN", "STN", "SEN"],
    "athens": ["ATH"],
    "rome": ["ROM", "FCO", "CIA"],
    "paris": ["PAR", "CDG", "ORY", "BVA"],
    "milan": ["MIL", "MXP", "LIN", "BGY"],
    "amsterdam": ["AMS"],
    "frankfurt": ["FRA"],
    "munich": ["MUC"],
    "zurich": ["ZRH"],
    "vienna": ["VIE"],
    "barcelona": ["BCN"],
    "madrid": ["MAD"],
    "stockholm": ["STO", "ARN", "BMA"],
    "copenhagen": ["CPH"],
    "oslo": ["OSL"],

    # Middle East
    "dubai": ["DXB", "DWC"],         # DWC sometimes used for LCCs
    "abu dhabi": ["AUH"],
    "doha": ["DOH"],
    "kuwait": ["KWI"],
    "muscat": ["MCT"],
    "bahrain": ["BAH"],
    "jeddah": ["JED"],
    "riyadh": ["RUH"],

    # Türkiye
    "istanbul": ["IST", "SAW"],

    # Pakistan
    "lahore": ["LHE"],
    "karachi": ["KHI"],
    "islamabad": ["ISB"],
    "sialkot": ["SKT"],
    "peshawar": ["PEW"],
    "multan": ["MUX"],
    "quetta": ["UET"],

    # US (common)
    "new york": ["NYC", "JFK", "LGA", "EWR"],
    "chicago": ["CHI", "ORD", "MDW"],
    "los angeles": ["LAX"],
    "san francisco": ["SFO"],
    "miami": ["MIA"],
    "boston": ["BOS"],
    "seattle": ["SEA"],
    "dallas": ["DFW", "DAL"],

    # Asia hubs
    "singapore": ["SIN"],
    "tokyo": ["TYO", "HND", "NRT"],
    "seoul": ["SEL", "ICN", "GMP"],
    "hong kong": ["HKG"],
    "bangkok": ["BKK"],
    "kuala lumpur": ["KUL"],
    "delhi": ["DEL"],
    "mumbai": ["BOM"],

    # Africa (common hubs)
    "nairobi": ["NBO"],
    "johannesburg": ["JNB"],
    "casablanca": ["CMN"],
}

# Metro “city” codes to constituent airports (round out behavior for LON/NYC/etc.)
METRO_TO_AIRPORTS: Dict[str, List[str]] = {
    "LON": ["LHR", "LGW", "LCY", "LTN", "STN", "SEN"],
    "PAR": ["CDG", "ORY", "BVA"],
    "MIL": ["MXP", "LIN", "BGY"],
    "ROM": ["FCO", "CIA"],
    "NYC": ["JFK", "LGA", "EWR"],
    "CHI": ["ORD", "MDW"],
    "TYO": ["HND", "NRT"],
    "SEL": ["ICN", "GMP"],
    "STO": ["ARN", "BMA"],
}

# If your API needs a *single* airport when a metro code is given, prefer this one:
PREFERRED_AIRPORT_FOR_METRO: Dict[str, str] = {
    "LON": "LHR",
    "PAR": "CDG",
    "MIL": "MXP",
    "ROM": "FCO",
    "NYC": "JFK",
    "CHI": "ORD",
    "TYO": "HND",
    "SEL": "ICN",
    "STO": "ARN",
}

# Common aliases / spellings / languages → canonical city key in CITY_TO_AIRPORTS
ALIASES: Dict[str, str] = {
    # Istanbul
    "istambul": "istanbul",
    "istanbol": "istanbul",
    "istanbul sabiha": "istanbul",
    "sabiha gokcen": "istanbul",
    # Dubai
    "deira": "dubai",
    "dxbcity": "dubai",
    # London
    "uk london": "london",
    "london city": "london",
    "heathrow": "london",
    "gatwick": "london",
    # Lahore
    "lahor": "lahore",
    # Athens
    "athina": "athens",
    # Karachi / Islamabad
    "khi": "karachi",
    "isl": "islamabad",
    # Abbreviations
    "nyc": "new york",
    "lon": "london",
    "par": "paris",
    "rom": "rome",
    "tyo": "tokyo",
}

IATA_AIRPORTS: Set[str] = (
    set(a for v in CITY_TO_AIRPORTS.values() for a in v)
    | set(a for v in METRO_TO_AIRPORTS.values() for a in v)
)

# --- Normalization ------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s

# Build a lookup from normalized phrase → list of airport codes
def build_city_lookup() -> Dict[str, List[str]]:
    lut: Dict[str, List[str]] = {}
    for city, airports in CITY_TO_AIRPORTS.items():
        lut[_norm(city)] = airports
    for alias, city in ALIASES.items():
        if city in CITY_TO_AIRPORTS:
            lut[_norm(alias)] = CITY_TO_AIRPORTS[city]
    return lut

CITY_LOOKUP = build_city_lookup()

# --- Public helpers -----------------------------------------------------------

def resolve_phrase_to_airports(phrase: str) -> Tuple[str, List[str]]:
    """
    Given any phrase ("istanbul", "lhr", "new york", "LON", "Heathrow"),
    return (preferred_code, all_possible_codes).

    If an explicit IATA airport is found (3 letters), that wins.
    If a metro code (LON/NYC/ROM/…) is found, return the preferred single airport,
    and list of all airports for that metro.
    Otherwise try to match city/alias strings from CITY_LOOKUP.
    """
    if not phrase:
        return "", []

    raw = phrase.strip().upper()
    if len(raw) == 3 and raw.isalpha():
        # Looks like an IATA code
        if raw in METRO_TO_AIRPORTS:
            alts = METRO_TO_AIRPORTS[raw]
            return PREFERRED_AIRPORT_FOR_METRO.get(raw, alts[0]), alts
        return raw, [raw]

    norm = _norm(phrase)

    # Direct city/alias match
    if norm in CITY_LOOKUP:
        alts = CITY_LOOKUP[norm]
        # If first is a metro, map to preferred single airport for payloads that need one
        first = alts[0]
        if first in METRO_TO_AIRPORTS:
            metro = first
            return PREFERRED_AIRPORT_FOR_METRO.get(metro, METRO_TO_AIRPORTS[metro][0]), METRO_TO_AIRPORTS[metro]
        return alts[0], alts

    # Try token window search (multi-word phrases in a longer sentence)
    tokens = norm.split()
    for win in range(min(4, len(tokens)), 0, -1):
        for i in range(0, len(tokens) - win + 1):
            chunk = " ".join(tokens[i:i+win])
            if chunk in CITY_LOOKUP:
                alts = CITY_LOOKUP[chunk]
                first = alts[0]
                if first in METRO_TO_AIRPORTS:
                    metro = first
                    return PREFERRED_AIRPORT_FOR_METRO.get(metro, METRO_TO_AIRPORTS[metro][0]), METRO_TO_AIRPORTS[metro]
                return alts[0], alts

    # No match
    return "", []