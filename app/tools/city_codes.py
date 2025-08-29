# app/tools/city_codes.py

from __future__ import annotations
from typing import Dict, List, Set, Tuple

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
    "berlin": ["BER", "TXL"],  # BER is the new main airport, TXL was the old one
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

# Metro "city" codes to constituent airports (round out behavior for LON/NYC/etc.)
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

# --- Public helpers -----------------------------------------------------------

def resolve_phrase_to_airports(phrase: str) -> Tuple[str, List[str]]:
    """
    Given any phrase ("istanbul", "lhr", "new york", "LON"),
    return (preferred_code, all_possible_codes).

    If an explicit IATA airport is found (3 letters), that wins.
    If a metro code (LON/NYC/ROM/…) is found, return the preferred single airport.
    Otherwise try to match city strings from CITY_TO_AIRPORTS.
    """
    if not phrase:
        return "", []

    # Check if it's already a 3-letter IATA code
    raw = phrase.strip().upper()
    if len(raw) == 3 and raw.isalpha():
        # Looks like an IATA code
        if raw in METRO_TO_AIRPORTS:
            alts = METRO_TO_AIRPORTS[raw]
            return PREFERRED_AIRPORT_FOR_METRO.get(raw, alts[0]), alts
        return raw, [raw]

    # Direct city match (case insensitive)
    city_key = phrase.strip().lower()
    if city_key in CITY_TO_AIRPORTS:
        alts = CITY_TO_AIRPORTS[city_key]
        # If first is a metro, map to preferred single airport
        first = alts[0]
        if first in METRO_TO_AIRPORTS:
            metro = first
            return PREFERRED_AIRPORT_FOR_METRO.get(metro, METRO_TO_AIRPORTS[metro][0]), METRO_TO_AIRPORTS[metro]
        return alts[0], alts

    # No match
    return "", []