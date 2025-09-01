"""
Utility functions for processing Travelport CatalogProductOfferings API responses.
Self-contained: cheapest selection + itinerary enrichment (duration, airlines, stops, layovers, baggage).
Matches the shapes expected by FlightSearchStateMachine without changing other files.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import re
import ast
import json


# ------------------------------
# Airline name mapping (old impl)
# ------------------------------
try:
    # when imported as part of the package (recommended)
    from .airline_codes import get_airline_name
except Exception:
    # fallback if someone runs this module directly
    from airline_codes import get_airline_name


# ------------------------------
# Time / duration helpers (old impl behavior)
# ------------------------------
def _parse_iso_duration_minutes(duration_str: Optional[str]) -> int:
    """Parse ISO 8601 duration like 'PT3H40M' to minutes."""
    if not duration_str or not isinstance(duration_str, str):
        return 0
    m = re.match(r'^PT(?:(\d+)H)?(?:(\d+)M)?', duration_str)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mm = int(m.group(2) or 0)
    return h * 60 + mm

def _human_minutes(mins: int) -> str:
    h, m = divmod(int(mins), 60)
    return f"{h}h {m}m" if h else f"{m}m"

def _parse_dt(date_str: str, time_str: str):
    """
    Accepts 'YYYY-MM-DD' + 'HH:MM' or 'HH:MM:SS', and ISO forms like 'YYYY-MM-DDTHH:MM[:SS][Z]'.
    Returns naive datetime or None.
    """
    if not date_str and time_str:
        dt_text = time_str
    else:
        sep = "T" if "T" in (time_str or "") else " "
        dt_text = f"{date_str}{sep}{time_str}".strip()

    if not dt_text:
        return None

    # strip trailing Z or timezone offset if present (we treat times as local)
    dt_text = dt_text.replace("Z", "")
    if "+" in dt_text:
        dt_text = dt_text.split("+", 1)[0]
    if "-" in dt_text and "T" in dt_text and dt_text.count("-") > 2:
        # e.g. 2025-11-07T08:05:00-02:00
        dt_text = dt_text.rsplit("-", 1)[0]

    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(dt_text, fmt)
        except Exception:
            continue
    return None

def _fmt_dt(date_str: str, time_str: str, location: str = "", terminal: str = "") -> str:
    dt = _parse_dt(date_str, time_str)
    if not dt:
        base = f"{date_str} {time_str}".strip()
        return f"{base} — {location}".strip()
    pretty = dt.strftime("%a %d %b %H:%M")
    return f"{pretty} — {location} T{terminal}" if terminal else f"{pretty} — {location}"


# ------------------------------
# Indexers (support both TP schemas)
# ------------------------------
def _build_indexes(resp: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Returns (flights_by_id, terms_by_id).
    Handles:
      - CatalogProductOfferingsResponse.ReferenceList[...] (array of typed blocks)
      - CatalogProductOfferingsResponse.ReferenceListFlight / ReferenceListTermsAndConditions (objects)
    """
    root = resp.get("CatalogProductOfferingsResponse", {}) or {}

    flights_by_id: Dict[str, Dict[str, Any]] = {}
    terms_by_id: Dict[str, Dict[str, Any]] = {}

    # A) Array-of-ReferenceList blocks (common in many payloads)
    for rl in root.get("ReferenceList", []) or []:
        t = rl.get("@type")
        if t == "ReferenceListFlight":
            for f in rl.get("Flight", []) or []:
                fid = f.get("id")
                if fid:
                    flights_by_id[fid] = f
        elif t == "ReferenceListTermsAndConditions":
            for tc in rl.get("TermsAndConditions", []) or []:
                tid = tc.get("id")
                if tid:
                    terms_by_id[tid] = tc

    # B) Object-style blocks (some tenants)
    for list_name, item_name, key_name in [
        ("ReferenceListFlight", "Flight", "id"),
        ("ReferenceListSegment", "Segment", "id"),
        ("ReferenceListAirSegment", "AirSegment", "id"),
    ]:
        block = root.get(list_name) or {}
        for it in block.get(item_name, []) or []:
            rid = it.get(key_name) or it.get("flightRef") or it.get("segmentRef")
            if rid and rid not in flights_by_id:
                flights_by_id[rid] = it

    tco_block = root.get("ReferenceListTermsAndConditions") or {}
    for tc in tco_block.get("TermsAndConditions", []) or []:
        tid = tc.get("id")
        if tid and tid not in terms_by_id:
            terms_by_id[tid] = tc

    return flights_by_id, terms_by_id


# ------------------------------
# Baggage summary (dict, matches StateMachine formatter expectations)
# ------------------------------
def _baggage_from_terms_ref(terms_ref: Optional[str], terms_idx: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "checked_bag_included": False,
        "checked_bag_allowance_kg": None,
        "carry_on_included": False,
        "carry_on_piece_count": None,
        "carry_on_text": None,
        "validating_airline": None,
        "penalties_change": None,
        "penalties_cancel": None,
        "payment_time_limit": None,
    }
    if not terms_ref or terms_ref not in terms_idx:
        return out

    t = terms_idx[terms_ref] or {}
    out["validating_airline"] = t.get("validatingAirlineCode")
    out["payment_time_limit"] = t.get("PaymentTimeLimit")

    # penalties
    pen = (t.get("Penalties") or [{}])[0]
    chg = (pen.get("Change") or [{}])[0]
    can = (pen.get("Cancel") or [{}])[0]
    if chg:
        p = (chg.get("Penalty") or [{}])[0]
        if "Percent" in p:
            out["penalties_change"] = f"{p.get('Percent')}%"
        elif "Amount" in p:
            a = p.get("Amount") or {}
            out["penalties_change"] = f"{a.get('value')} {a.get('code')}" if a.get('value') else None
    if can:
        p = (can.get("Penalty") or [{}])[0]
        if "Percent" in p:
            out["penalties_cancel"] = f"{p.get('Percent')}%"
        elif "Amount" in p:
            a = p.get("Amount") or {}
            out["penalties_cancel"] = f"{a.get('value')} {a.get('code')}" if a.get('value') else None

    # baggage allowance
    for b in t.get("BaggageAllowance", []) or []:
        btype = b.get("baggageType")
        items = b.get("BaggageItem") or []
        if btype == "FirstCheckedBag":
            out["checked_bag_included"] = any(i.get("includedInOfferPrice") == "Yes" for i in items)
            kg = None
            for i in items:
                for m in i.get("Measurement", []) or []:
                    if (m.get("measurementType") == "Weight") and str(m.get("unit", "")).lower().startswith("kg"):
                        try:
                            kg = float(m.get("value"))
                        except Exception:
                            pass
            out["checked_bag_allowance_kg"] = kg
        elif btype == "CarryOn":
            out["carry_on_included"] = any(i.get("includedInOfferPrice") == "Yes" for i in items)
            qty = None
            text = None
            for i in items:
                if "quantity" in i and i["quantity"] is not None:
                    try:
                        qty = int(i["quantity"])
                    except Exception:
                        pass
                if "Text" in i:
                    tval = i["Text"]
                    if isinstance(tval, list) and tval:
                        tval = tval[0]
                    text = text or tval
            if not text and isinstance(b.get("Text"), list) and b["Text"]:
                text = b["Text"][0]
            out["carry_on_piece_count"] = qty
            out["carry_on_text"] = text
    return out


# ------------------------------
# Itinerary construction from flightRefs (old impl style output)
# ------------------------------
def _segments_from_refs(refs: List[str], flights_idx: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    segs = []
    for r in refs or []:
        f = flights_idx.get(r)
        if f:
            segs.append(f)
    segs.sort(key=lambda s: (s.get("Departure", {}).get("date", ""), s.get("Departure", {}).get("time", "")))
    return segs

# --- replace _layovers_and_stops to be more tolerant and carry airport code ---
def _layovers_and_stops(segments: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], int]:
    layovers: List[Dict[str, str]] = []
    total_minutes = 0

    def _airport_from(deparr: Dict[str, Any]) -> str:
        return (
            deparr.get("location")
            or deparr.get("airport")
            or deparr.get("Airport")
            or deparr.get("Iata")
            or deparr.get("iata")
            or ""
        )

    for i in range(len(segments) - 1):
        prev = segments[i].get("Arrival", {}) or {}
        nxt  = segments[i + 1].get("Departure", {}) or {}
        a_dt = _parse_dt(prev.get("date", ""), prev.get("time", "") or prev.get("Time", ""))
        d_dt = _parse_dt(nxt.get("date", ""),  nxt.get("time", "")  or nxt.get("Time", ""))
        if a_dt and d_dt and d_dt > a_dt:
            mins = int((d_dt - a_dt).total_seconds() // 60)
            total_minutes += mins
            airport = _airport_from(prev)
            layovers.append({
                "city": airport,             # legacy key
                "airport_code": airport,     # explicit code
                "duration": _human_minutes(mins),
                "minutes": mins,
            })
    return layovers, total_minutes


def _pick_carrier_and_number(seg: dict) -> tuple[str | None, str | None]:
    """
    Return (carrier_code, flight_number) from many possible TP shapes.
    """
    # simple shape
    code = seg.get("carrier")
    num  = seg.get("number")

    # nested shapes
    mc = seg.get("MarketingCarrier") or seg.get("marketingCarrier") or seg.get("Carrier") or {}
    oc = seg.get("OperatingCarrier") or seg.get("operatingCarrier") or {}

    def pick(obj):
        if not isinstance(obj, dict):
            return None, None
        c = obj.get("code") or obj.get("airlineCode") or obj.get("carrierCode")
        n = obj.get("number") or obj.get("flightNumber")
        return c, n

    if not code:
        c1, n1 = pick(mc)
        code = code or c1
        num  = num  or n1
    if not code:
        c2, n2 = pick(oc)
        code = code or c2
        num  = num  or n2

    # last resorts seen in some payloads
    code = code or seg.get("airlineCode") or seg.get("MarketingCarrierCode") or seg.get("OperatingCarrierCode")
    num  = num  or seg.get("flightNumber") or seg.get("MarketingFlightNumber") or seg.get("OperatingFlightNumber")

    return (str(code) if code else None, str(num) if num else None)


def _itinerary_from_segments(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "segments": segments,
        "departure_time_text": None,
        "arrival_time_text": None,
        "airlines": None,              # "British Airways, Aegean Airlines"
        "flight_numbers": None,        # "BA632, A3605"
        "carrier_codes": [],           # ["BA","A3"] (new, harmless)
        "stops": 0,
        "stops_text": None,
        "layovers": [],
        "duration_minutes": None,
        "duration_human": None,
    }
    if not segments:
        return out

    d0 = segments[0].get("Departure", {}) or {}
    aN = segments[-1].get("Arrival", {}) or {}

    out["departure_time_text"] = _fmt_dt(d0.get("date", ""), d0.get("time", ""), d0.get("location", ""), d0.get("terminal", "") or "")
    out["arrival_time_text"]   = _fmt_dt(aN.get("date", ""), aN.get("time", ""), aN.get("location", ""))

    names: list[str] = []
    numbers: list[str] = []
    seen_codes: set[str] = set()

    for s in segments:
        code, num = _pick_carrier_and_number(s)
        if code:
            out["carrier_codes"].append(code)
            if code not in seen_codes:
                seen_codes.add(code)
                try:
                    names.append(get_airline_name(code))
                except Exception:
                    names.append(code)
        if code and num:
            numbers.append(f"{code}{num}")

    out["airlines"] = ", ".join(names) if names else None
    out["flight_numbers"] = ", ".join(numbers) if numbers else None
    seg_sum = sum(_parse_iso_duration_minutes(s.get("duration") or "") for s in segments)
    layovers, lay_min = _layovers_and_stops(segments)
    out["layovers"] = layovers
    out["stops"] = max(0, len(segments) - 1)

    total_minutes = None
    if seg_sum:  # preferred path (avoids TZ errors)
        total_minutes = seg_sum + lay_min
    else:
        # fallback to wall-clock if segment durations missing
        d0 = segments[0].get("Departure", {}) or {}
        aN = segments[-1].get("Arrival", {}) or {}
        d_dt = _parse_dt(d0.get("date", ""), d0.get("time", "") or d0.get("Time", ""))
        a_dt = _parse_dt(aN.get("date", ""), aN.get("time", "") or aN.get("Time", ""))
        if d_dt and a_dt and a_dt >= d_dt:
            total_minutes = int((a_dt - d_dt).total_seconds() // 60)

    out["duration_minutes"] = total_minutes
    out["duration_human"] = _human_minutes(total_minutes or 0)

    if out["stops"] == 0:
        out["stops_text"] = "Direct"
    else:
        if out["layovers"]:
            via = ", ".join(f"{l.get('airport_code') or l.get('city')} ({l['duration']})" for l in out["layovers"])
            out["stops_text"] = f"{out['stops']} stop(s) via {via}"
        else:
            out["stops_text"] = f"{out['stops']} stop(s)"

    return out

    

# ------------------------------
# Cheapest selection (old-file behavior)
# ------------------------------
def _offering_min_price(off: Dict[str, Any]) -> Optional[float]:
    """Min BestCombinablePrice.TotalPrice found inside an offering."""
    best = None
    for pbo in off.get("ProductBrandOptions", []) or []:
        for p in pbo.get("ProductBrandOffering", []) or []:
            price = (p.get("BestCombinablePrice") or {}).get("TotalPrice")
            if price is None:
                continue
            try:
                val = float(price)
            except Exception:
                continue
            if best is None or val < best:
                best = val
    return best

def _select_cheapest_brand_offering(off: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the cheapest ProductBrandOffering dict from an offering."""
    cheapest = None
    cheapest_val = float("inf")
    for pbo in off.get("ProductBrandOptions", []) or []:
        # If flightRefs are at the PBO level, keep for later
        pbo_refs = pbo.get("flightRefs") or []
        for brand_off in pbo.get("ProductBrandOffering", []) or []:
            price_info = brand_off.get("BestCombinablePrice", {}) or {}
            total = price_info.get("TotalPrice")
            if total is None:
                continue
            try:
                total_val = float(total)
            except Exception:
                continue
            if total_val < cheapest_val:
                cheapest = dict(brand_off)  # shallow copy so we can stitch refs
                if pbo_refs and not cheapest.get("flightRefs"):
                    cheapest["flightRefs"] = list(pbo_refs)
                cheapest_val = total_val
    return cheapest


# ------------------------------
# Public: extract cheapest one-way (enriched)
# ------------------------------
def extract_cheapest_one_way_summary(resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    root = resp.get("CatalogProductOfferingsResponse", {}) or {}
    offerings = (root.get("CatalogProductOfferings") or {}).get("CatalogProductOffering") or []
    if not offerings:
        return None

    # Choose globally cheapest offering option
    cheapest_off = None
    cheapest_val = float("inf")
    cheapest_choice = None
    for off in offerings:
        ch = _select_cheapest_brand_offering(off)
        if not ch:
            continue
        total = (ch.get("BestCombinablePrice") or {}).get("TotalPrice")
        try:
            val = float(total)
        except Exception:
            continue
        if val < cheapest_val:
            cheapest_val = val
            cheapest_off = off
            cheapest_choice = ch

    if not cheapest_choice:
        return None

    flights_idx, terms_idx = _build_indexes(resp)

    # price block
    bp = cheapest_choice.get("BestCombinablePrice") or {}
    price = {
        "currency": ((bp.get("CurrencyCode") or {}).get("value")) if isinstance(bp.get("CurrencyCode"), dict) else bp.get("CurrencyCode"),
        "total": float(bp.get("TotalPrice")) if bp.get("TotalPrice") is not None else None,
        "base": float(bp.get("Base")) if bp.get("Base") is not None else None,
        "taxes": float(bp.get("TotalTaxes")) if bp.get("TotalTaxes") is not None else None,
    }

    # refs + terms
    refs = cheapest_choice.get("flightRefs") or []
    terms_ref = (cheapest_choice.get("TermsAndConditions") or {}).get("termsAndConditionsRef")

    segs = _segments_from_refs(refs, flights_idx)
    itin = _itinerary_from_segments(segs)
    baggage = _baggage_from_terms_ref(terms_ref, terms_idx)
    if not baggage.get("validating_airline") and itin.get("carrier_codes"):
        baggage["validating_airline"] = itin["carrier_codes"][0]

    # ONE-WAY summary shape expected by FlightSearchStateMachine (flat)
    return {
        "direction": "outbound",
        "price": price,
        "duration_minutes_total": itin["duration_minutes"],
        "stops_total": itin["stops"],
        "baggage": baggage,
        "flightRefs": refs,
        "itinerary": itin,  # rich block (airlines, numbers, layovers, human times)
    }


# ------------------------------
# Public: extract cheapest round-trip (paired cheapest outbound + return)
# ------------------------------
def extract_cheapest_round_trip_summary(resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    root = resp.get("CatalogProductOfferingsResponse", {}) or {}
    offerings: List[Dict[str, Any]] = (root.get("CatalogProductOfferings") or {}).get("CatalogProductOffering") or []
    if not offerings:
        return None

    # Many payloads mark direction with "sequence": 1 (outbound), 2 (inbound)
    seq_buckets: Dict[int, List[Dict[str, Any]]] = {}
    for off in offerings:
        try:
            seq = int(off.get("sequence", 0))
        except Exception:
            seq = 0
        seq_buckets.setdefault(seq, []).append(off)

    out_off = min(seq_buckets.get(1, []), key=lambda o: _offering_min_price(o) or float("inf")) if seq_buckets.get(1) else None
    in_off  = min(seq_buckets.get(2, []), key=lambda o: _offering_min_price(o) or float("inf")) if seq_buckets.get(2) else None

    # Fall back: if no clear sequence split, pick two cheapest distinct offerings
    if not out_off and offerings:
        offerings_sorted = sorted(offerings, key=lambda o: _offering_min_price(o) or float("inf"))
        out_off = offerings_sorted[0] if offerings_sorted else None
        in_off = offerings_sorted[1] if len(offerings_sorted) > 1 else None

    if not out_off:
        return None

    out_choice = _select_cheapest_brand_offering(out_off)
    in_choice  = _select_cheapest_brand_offering(in_off) if in_off else None

    flights_idx, terms_idx = _build_indexes(resp)

    def make_leg(choice: Dict[str, Any]) -> Dict[str, Any]:
        bp = choice.get("BestCombinablePrice") or {}
        price = {
            "currency": ((bp.get("CurrencyCode") or {}).get("value")) if isinstance(bp.get("CurrencyCode"), dict) else bp.get("CurrencyCode"),
            "total": float(bp.get("TotalPrice")) if bp.get("TotalPrice") is not None else None,
            "base": float(bp.get("Base")) if bp.get("Base") is not None else None,
            "taxes": float(bp.get("TotalTaxes")) if bp.get("TotalTaxes") is not None else None,
        }
        refs = choice.get("flightRefs") or []
        terms_ref = (choice.get("TermsAndConditions") or {}).get("termsAndConditionsRef")
        segs = _segments_from_refs(refs, flights_idx)
        itin = _itinerary_from_segments(segs)
        bag = _baggage_from_terms_ref(terms_ref, terms_idx)
        if not bag.get("validating_airline") and itin.get("carrier_codes"):
            bag["validating_airline"] = itin["carrier_codes"][0]
        return {
            "price": price,
            "duration_minutes_total": itin["duration_minutes"],
            "stops_total": itin["stops"],
            "baggage": bag,
            "flightRefs": refs,
            "itinerary": itin,
        }

    outbound = make_leg(out_choice) if out_choice else None
    inbound = make_leg(in_choice) if in_choice else None

    # Summary totals
    total_price = 0.0
    currency = None
    if outbound and outbound["price"]["total"] is not None:
        total_price += outbound["price"]["total"]
        currency = outbound["price"]["currency"]
    if inbound and inbound["price"]["total"] is not None:
        total_price += inbound["price"]["total"]
        if not currency:
            currency = inbound["price"]["currency"]

    total_duration = (outbound.get("duration_minutes_total") or 0) + (inbound.get("duration_minutes_total") or 0)
    total_stops = (outbound.get("stops_total") or 0) + (inbound.get("stops_total") or 0)

    return {
        "price_total": {"currency": currency, "total": total_price if total_price else None},
        "outbound": outbound,
        "inbound": inbound,
        "duration_minutes_total": total_duration or None,
        "duration_human_total": _human_minutes(total_duration) if total_duration else None,
        "stops_total": total_stops,
    }

   

# ------------------------------
# Bulk Search Helper Functions
# ------------------------------

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import calendar

def parse_date_range(user_input: str, departure_date: Optional[str] = None) -> Tuple[List[str], bool]:
    """
    Parse user input to detect bulk search patterns and return list of dates.
    Returns (list_of_dates, is_bulk_search)
    
    Examples:
    - "find me cheapest ticket in november" -> all days in current year November
    - "find me cheapest ticket next week" -> next 7 days  
    - "cheapest ticket between 2025-01-01 and 2025-01-31" -> date range
    - "cheapest ticket on 2025-01-15" -> single date (not bulk)
    """
    user_input_lower = user_input.lower()
    today = datetime.now().date()
    
    # Single date patterns - not bulk search
    single_date_patterns = [
        r'on \d{4}-\d{2}-\d{2}',
        r'for \d{4}-\d{2}-\d{2}',
        r'tomorrow',
        r'today'
    ]
    
    import re
    for pattern in single_date_patterns:
        if re.search(pattern, user_input_lower):
            if departure_date:
                return [departure_date], False
            return [], False
    
    # Bulk search patterns
    bulk_patterns = {
        'november': ('month', 11),
        'december': ('month', 12),
        'january': ('month', 1),
        'february': ('month', 2),
        'march': ('month', 3),
        'april': ('month', 4),
        'may': ('month', 5),
        'june': ('month', 6),
        'july': ('month', 7),
        'august': ('month', 8),
        'september': ('month', 9),
        'october': ('month', 10),
        'next week': ('next_week', None),
        'this week': ('this_week', None),
        'next month': ('next_month', None),
        'this month': ('this_month', None),
    }
    
    dates = []
    is_bulk = False
    
    # Check for month patterns
    for pattern, (period_type, month_num) in bulk_patterns.items():
        if pattern in user_input_lower:
            is_bulk = True
            if period_type == 'month' and month_num:
                # Generate all days in the specified month
                year = today.year
                if month_num < today.month:
                    year += 1  # Next year if month already passed
                
                # Get number of days in month
                days_in_month = calendar.monthrange(year, month_num)[1]
                
                for day in range(1, days_in_month + 1):
                    date_str = f"{year:04d}-{month_num:02d}-{day:02d}"
                    dates.append(date_str)
                    
            elif period_type == 'next_week':
                # Next 7 days starting from tomorrow
                start_date = today + timedelta(days=1)
                for i in range(7):
                    date_str = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
                    dates.append(date_str)
                    
            elif period_type == 'this_week':
                # Remaining days of current week
                days_until_sunday = (6 - today.weekday()) % 7
                for i in range(days_until_sunday + 1):
                    date_str = (today + timedelta(days=i)).strftime('%Y-%m-%d')
                    dates.append(date_str)
                    
            elif period_type == 'next_month':
                # All days in next month
                if today.month == 12:
                    next_month = 1
                    next_year = today.year + 1
                else:
                    next_month = today.month + 1
                    next_year = today.year
                
                days_in_month = calendar.monthrange(next_year, next_month)[1]
                for day in range(1, days_in_month + 1):
                    date_str = f"{next_year:04d}-{next_month:02d}-{day:02d}"
                    dates.append(date_str)
                    
            elif period_type == 'this_month':
                # Remaining days in current month
                days_in_month = calendar.monthrange(today.year, today.month)[1]
                for day in range(today.day, days_in_month + 1):
                    date_str = f"{today.year:04d}-{today.month:02d}-{day:02d}"
                    dates.append(date_str)
            break
    
    # Check for "between X and Y" pattern
    between_pattern = r'between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})'
    match = re.search(between_pattern, user_input_lower)
    if match:
        is_bulk = True
        start_date_str, end_date_str = match.groups()
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            current_date = start_date
            while current_date <= end_date:
                dates.append(current_date.strftime('%Y-%m-%d'))
                current_date += timedelta(days=1)
        except ValueError:
            pass  # Invalid date format
    
    return dates, is_bulk


async def search_single_date_async(payload_func, origin: str, destination: str, date: str, 
                                 number_of_passengers: int, carriers: List[str], trip_type: str = "one-way") -> Dict[str, Any]:
    """
    Perform a single date search asynchronously.
    Returns the search result with the date included for tracking.
    """
    try:
        # Import here to avoid circular imports
        from .TravelportSearch import TravelportSearch
        
        # Create payload for this specific date
        payload = payload_func(
            origin=origin,
            destination=destination,
            departure_date=date,
            number_of_passengers=number_of_passengers,
            carriers=carriers
        )
        
        # Perform the search (this is blocking, but we're calling it in an executor)
        result = TravelportSearch.invoke({"payload": payload, "trip_type": trip_type})
        
        # Add date information to result
        result["search_date"] = date
        return result
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Search failed for {date}: {str(e)}",
            "search_date": date,
            "summary": None
        }


async def bulk_search_cheapest_async(origin: str, destination: str, dates: List[str], 
                                   number_of_passengers: int, carriers: List[str], 
                                   trip_type: str = "one-way") -> Dict[str, Any]:
    """
    Perform bulk search across multiple dates to find the cheapest option.
    Returns the cheapest result with details about all searches performed.
    """
    if not dates:
        return {
            "ok": False,
            "error": "No dates provided for bulk search",
            "cheapest_result": None,
            "all_results": []
        }
    
    # Import payload functions
    if trip_type == "one-way":
        from ..payloads.OneWayFlightSearch import OneWayFlightSearch
        payload_func = OneWayFlightSearch
    else:
        from ..payloads.RoundTripFlightSearch import RoundTripFlightSearch
        payload_func = RoundTripFlightSearch
    
    # Create tasks for all date searches
    tasks = []
    for date in dates:
        task = asyncio.create_task(
            search_single_date_async(payload_func, origin, destination, date, 
                                   number_of_passengers, carriers, trip_type)
        )
        tasks.append(task)
    
    # Wait for all searches to complete
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        return {
            "ok": False,
            "error": f"Bulk search failed: {str(e)}",
            "cheapest_result": None,
            "all_results": []
        }
    
    # Process results
    valid_results = []
    cheapest_result = None
    cheapest_price = float('inf')
    
    for result in results:
        if isinstance(result, Exception):
            continue
            
        if result.get("ok") and result.get("summary"):
            valid_results.append(result)
            
            # Extract price based on trip type
            summary = result["summary"]
            if trip_type == "round-trip" and summary.get("price_total"):
                price = summary["price_total"].get("total")
            elif trip_type == "one-way" and summary.get("price"):
                price = summary["price"].get("total")
            else:
                continue
                
            if price and float(price) < cheapest_price:
                cheapest_price = float(price)
                cheapest_result = result
    
    return {
        "ok": len(valid_results) > 0,
        "cheapest_result": cheapest_result,
        "cheapest_price": cheapest_price if cheapest_price != float('inf') else None,
        "total_searches": len(dates),
        "successful_searches": len(valid_results),
        "all_results": valid_results,
        "search_summary": f"Searched {len(dates)} dates, found {len(valid_results)} valid options"
    }


def bulk_search_cheapest_sync(origin: str, destination: str, dates: List[str], 
                             number_of_passengers: int, carriers: List[str], 
                             trip_type: str = "one-way") -> Dict[str, Any]:
    """
    Perform bulk search across multiple dates to find the cheapest option (synchronous version).
    Returns the cheapest result with details about all searches performed.
    
    This version processes searches sequentially to avoid async complications in the LangChain tool context.
    For very large date ranges, this might be slower but more reliable.
    """
    if not dates:
        return {
            "ok": False,
            "error": "No dates provided for bulk search",
            "cheapest_result": None,
            "all_results": []
        }
    
    # Import payload functions and TravelportSearch
    try:
        from .TravelportSearch import TravelportSearch
        if trip_type == "one-way":
            from ..payloads.OneWayFlightSearch import OneWayFlightSearch
            payload_func = OneWayFlightSearch
        else:
            from ..payloads.RoundTripFlightSearch import RoundTripFlightSearch
            payload_func = RoundTripFlightSearch
    except ImportError as e:
        return {
            "ok": False,
            "error": f"Import error: {str(e)}",
            "cheapest_result": None,
            "all_results": []
        }
    
    # Process searches sequentially
    valid_results = []
    cheapest_result = None
    cheapest_price = float('inf')
    
    # For bulk search, process all dates (remove artificial limit)
    limited_dates = dates
    print(f"[BulkSearch] Processing all {len(limited_dates)} dates for bulk search")
    
    for i, date in enumerate(limited_dates):
        try:
            print(f"[BulkSearch] Searching date {i+1}/{len(limited_dates)}: {date}")
            
            # Create payload for this specific date
            payload = payload_func(
                origin=origin,
                destination=destination,
                departure_date=date,
                number_of_passengers=number_of_passengers,
                carriers=carriers
            )
            
            # Perform the search
            result = TravelportSearch.invoke({"payload": payload, "trip_type": trip_type})
            print(f"[BulkSearch] Completed search for {date}: {'OK' if result.get('ok') else 'FAILED'}")
            
            # Add date information to result
            result["search_date"] = date
            
            if result.get("ok") and result.get("summary"):
                valid_results.append(result)
                
                # Extract price based on trip type
                summary = result["summary"]
                if trip_type == "round-trip" and summary.get("price_total"):
                    price = summary["price_total"].get("total")
                elif trip_type == "one-way" and summary.get("price"):
                    price = summary["price"].get("total")
                else:
                    continue
                    
                if price and float(price) < cheapest_price:
                    cheapest_price = float(price)
                    cheapest_result = result
                    
        except Exception as e:
            # Log the error but continue with other dates
            print(f"[BulkSearch] Search failed for {date}: {str(e)}")
            continue
    
    return {
        "ok": len(valid_results) > 0,
        "cheapest_result": cheapest_result,
        "cheapest_price": cheapest_price if cheapest_price != float('inf') else None,
        "total_searches": len(limited_dates),
        "successful_searches": len(valid_results),
        "all_results": valid_results,
        "search_summary": f"Searched {len(limited_dates)} dates, found {len(valid_results)} valid options"
    }


def calculate_return_date(departure_date: str, days_offset: int) -> str:
    """
    Calculate return date by adding days to departure date.
    Used when user specifies return trip duration like "10 days later".
    """
    try:
        dep_date = datetime.strptime(departure_date, '%Y-%m-%d')
        return_date = dep_date + timedelta(days=days_offset)
        return return_date.strftime('%Y-%m-%d')
    except ValueError:
        return departure_date  # Fallback to original if parsing fails


def is_bulk_search_query(user_input: str) -> bool:
    """
    Quick check to determine if user input indicates a bulk search request.
    """
    bulk_indicators = [
        'cheapest in',
        'cheapest ticket in',
        'cheapest flight in', 
        'find cheapest',
        'best price in',
        'lowest fare in',
        'between',
        'next week',
        'this week',
        'next month',
        'this month',
        'november',
        'december',
        'january',
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october'
    ]
    
    user_lower = user_input.lower()
    return any(indicator in user_lower for indicator in bulk_indicators)


def extract_return_duration(user_input: str) -> Optional[int]:
    """
    Extract return duration from user input.
    Examples: "10 days", "2 weeks", "1 week"
    Returns number of days or None if not found.
    """
    import re
    
    # Pattern for "X days"
    days_match = re.search(r'(\d+)\s*days?', user_input.lower())
    if days_match:
        return int(days_match.group(1))
    
    # Pattern for "X weeks"  
    weeks_match = re.search(r'(\d+)\s*weeks?', user_input.lower())
    if weeks_match:
        return int(weeks_match.group(1)) * 7
        
    # Pattern for "a week" or "one week"
    if re.search(r'\b(a|one)\s*week\b', user_input.lower()):
        return 7
        
    return None

   

# ------------------------------
# Background Task Queue for Async Bulk Search
# ------------------------------

import threading
import time
from queue import Queue
from typing import Callable

# Global task queue for background processing
_task_queue = Queue()
_worker_running = False
_worker_thread = None
_active_searches = set()  # Track active searches to prevent duplicates
_pending_messages = {}  # Storage for pending messages

def _background_worker():
    """Background worker that processes bulk search tasks"""
    global _worker_running
    print("[BulkSearch] Background worker started")
    
    while _worker_running:
        try:
            # Get task from queue (blocks for up to 1 second)
            task = _task_queue.get(timeout=1.0)
            
            if task is None:  # Shutdown signal
                break
                
            # Execute the task
            task_func, args, kwargs = task
            try:
                task_func(*args, **kwargs)
            except Exception as e:
                print(f"[BulkSearch] Task execution error: {e}")
            finally:
                _task_queue.task_done()
                
        except:
            # Timeout or queue empty, continue
            continue
    
    print("[BulkSearch] Background worker stopped")

def start_background_worker():
    """Start the background worker thread"""
    global _worker_running, _worker_thread
    
    if not _worker_running:
        _worker_running = True
        _worker_thread = threading.Thread(target=_background_worker, daemon=True)
        _worker_thread.start()
        print("[BulkSearch] Background worker thread started")

def stop_background_worker():
    """Stop the background worker thread"""
    global _worker_running, _worker_thread
    
    if _worker_running:
        _worker_running = False
        _task_queue.put(None)  # Shutdown signal
        if _worker_thread:
            _worker_thread.join(timeout=2.0)
        print("[BulkSearch] Background worker stopped")

def queue_bulk_search_task(task_func: Callable, *args, **kwargs):
    """Add a bulk search task to the background queue"""
    if not _worker_running:
        start_background_worker()
    
    print(f"[BulkSearch] Queueing task with kwargs: {kwargs}")
    _task_queue.put((task_func, args, kwargs))
    print(f"[BulkSearch] Task queued for background processing")


def execute_bulk_search_background(origin: str, destination: str, dates: List[str], 
                                 number_of_passengers: int, carriers: List[str],
                                 trip_type: str, thread_id: str = "unknown", user_phone: str = None,
                                 original_user_input: str = "", detected_language: str = "en"):
    """
    Execute bulk search in background and send result via callback.
    This function runs in a separate thread.
    """
    search_key = f"{thread_id}:{origin}:{destination}:{len(dates)}"
    
    # Check if this search is already running
    global _active_searches
    if search_key in _active_searches:
        print(f"[BulkSearch] Search already running for {search_key}, skipping duplicate")
        return
    
    _active_searches.add(search_key)
    print(f"[BulkSearch] Starting background bulk search for {len(dates)} dates")
    print(f"[BulkSearch] Background search thread_id: {thread_id}")
    
    try:
        # Perform the bulk search
        bulk_result = bulk_search_cheapest_sync(
            origin=origin,
            destination=destination,
            dates=dates,
            number_of_passengers=number_of_passengers,
            carriers=carriers,
            trip_type=trip_type
        )
        
        # Format the response message
        if bulk_result.get("ok") and bulk_result.get("cheapest_result"):
            cheapest = bulk_result["cheapest_result"]
            summary = cheapest.get("summary")
            search_date = cheapest.get("search_date")
            
            price = summary.get("price", {})
            price_text = f"{price.get('total')} {price.get('currency')}" if price.get('total') else "Price not available"
            
            # Import here to avoid circular imports
            from ..tools.FlightSearchStateMachine import format_duration, format_stops, format_layovers, format_baggage_summary
            
            duration = format_duration(summary.get("duration_minutes_total"))
            stops = format_stops(summary.get("stops_total", 0))
            
            message = f"🎯 Cheapest option found!\n\n"
            message += f"✈️ {origin} → {destination} on {search_date}\n"
            message += f"💰 Price: {price_text}\n"
            message += f"⏱️ Duration: {duration}, {stops}\n"
            
            it = summary.get("itinerary", {})
            if it.get("airlines"):
                message += f"🏢 Airline: {it['airlines']}\n"
            if it.get("flight_numbers"):
                message += f"🔢 Flight: {it['flight_numbers']}\n"
            
            # Add layover information
            layovers = it.get("layovers", [])
            if layovers:
                layover_info = ", ".join([f"{l.get('airport_code', l.get('city', 'Unknown'))} ({l.get('duration', 'Unknown')})" for l in layovers])
                message += f"🔄 Layovers: {layover_info}\n"
            
            if summary.get("baggage"):
                message += f"🧳 Baggage: {format_baggage_summary(summary['baggage'])}\n"
            
            message += f"\n📊 Searched {bulk_result.get('total_searches')} dates, found {bulk_result.get('successful_searches')} options"
            
            # Check if this is a return trip request and search for return flights
            return_duration = extract_return_duration(original_user_input)
            if return_duration and cheapest:
                try:
                    from datetime import datetime, timedelta
                    
                    # Calculate return date
                    departure_date = datetime.strptime(search_date, '%Y-%m-%d')
                    return_date = departure_date + timedelta(days=return_duration)
                    return_date_str = return_date.strftime('%Y-%m-%d')
                    
                    # Search for return flight
                    if trip_type == "one-way":
                        from ..payloads.OneWayFlightSearch import OneWayFlightSearch
                        return_payload = OneWayFlightSearch(
                            origin=destination,  # Reversed
                            destination=origin,   # Reversed
                            departure_date=return_date_str,
                            number_of_passengers=number_of_passengers,
                            carriers=carriers
                        )
                        
                        from .TravelportSearch import TravelportSearch
                        return_result = TravelportSearch.invoke({"payload": return_payload, "trip_type": "one-way"})
                        
                        if return_result.get("ok") and return_result.get("summary"):
                            return_summary = return_result["summary"]
                            return_price = return_summary.get("price", {})
                            return_price_text = f"{return_price.get('total')} {return_price.get('currency')}" if return_price.get('total') else "Price not available"
                            return_duration_text = format_duration(return_summary.get("duration_minutes_total"))
                            return_stops = format_stops(return_summary.get("stops_total", 0))
                            
                            message += f"\n\n🔄 Return flight ({return_duration} days later):\n"
                            message += f"✈️ {destination} → {origin} on {return_date_str}\n"
                            message += f"💰 Price: {return_price_text}\n"
                            message += f"⏱️ Duration: {return_duration_text}, {return_stops}\n"
                            
                            # Add return layover info
                            return_it = return_summary.get("itinerary", {})
                            return_layovers = return_it.get("layovers", [])
                            if return_layovers:
                                return_layover_info = ", ".join([f"{l.get('airport_code', l.get('city', 'Unknown'))} ({l.get('duration', 'Unknown')})" for l in return_layovers])
                                message += f"🔄 Return layovers: {return_layover_info}\n"
                            
                            # Calculate total price
                            outbound_price = float(price.get('total', 0))
                            return_price_val = float(return_price.get('total', 0))
                            total_price = outbound_price + return_price_val
                            message += f"\n💰 Total round-trip price: {total_price:.2f} {price.get('currency', 'EUR')}"
                        else:
                            message += f"\n\n❌ No return flights found for {return_date_str}"
                            
                except Exception as e:
                    print(f"[BulkSearch] Error searching return flights: {e}")
                    message += f"\n\n❌ Error searching return flights"
            
        else:
            message = f"❌ Bulk search completed but no flights found across {bulk_result.get('total_searches', 0)} dates."
        
        # Translate message if user language is not English
        if detected_language != "en":
            try:
                from ..services.translation_service import translation_service
                translated_message = translation_service.translate_from_english(message, detected_language)
                if translated_message:
                    message = translated_message
                    print(f"[BulkSearch] Translated response to {detected_language}")
            except Exception as e:
                print(f"[BulkSearch] Translation failed: {e}")
        
        # Send the result back to the user
        print(f"[BulkSearch] About to send response to thread_id: {thread_id}")
        send_async_response(thread_id, message, user_phone)
        print(f"[BulkSearch] Completed bulk search for {thread_id}")
        
    except Exception as e:
        error_message = f"❌ Bulk search failed: {str(e)}"
        
        # Translate error message if needed
        if detected_language != "en":
            try:
                from ..services.translation_service import translation_service
                translated_error = translation_service.translate_from_english(error_message, detected_language)
                if translated_error:
                    error_message = translated_error
            except Exception as trans_e:
                print(f"[BulkSearch] Error translation failed: {trans_e}")
        
        send_async_response(thread_id, error_message, user_phone)
        print(f"[BulkSearch] Background execution error: {e}")
    finally:
        # Remove from active searches when done
        _active_searches.discard(search_key)


def send_async_response(thread_id: str, message: str, user_phone: str = None):
    """
    Send bulk search results back to user via Twilio WhatsApp.
    """
    print(f"[BulkSearch] Sending results to {thread_id}: {message[:100]}...")
    
    try:
        # Extract WhatsApp phone number from thread_id
        whatsapp_number = None
        
        # thread_id can be:
        # 1. Pure digits (phone number without country code): e.g. "447948623631"
        # 2. WhatsApp ID format: e.g. "whatsapp:+447948623631"  
        # 3. Phone number with + prefix: e.g. "+447948623631"
        
        if thread_id.startswith("whatsapp:"):
            # Already in WhatsApp format
            whatsapp_number = thread_id
            print(f"[BulkSearch] Thread ID is already WhatsApp format: {whatsapp_number}")
        elif thread_id.startswith("+"):
            # Phone number with + prefix
            whatsapp_number = f"whatsapp:{thread_id}"
            print(f"[BulkSearch] Converted phone number to WhatsApp format: {whatsapp_number}")
        elif thread_id.isdigit():
            # Pure digits - assume it's a phone number and add + prefix
            whatsapp_number = f"whatsapp:+{thread_id}"
            print(f"[BulkSearch] Converted digit string to WhatsApp format: {whatsapp_number}")
        else:
            print(f"[BulkSearch] Thread ID '{thread_id}' is not a valid phone number format, cannot send WhatsApp")
            return
        
        if whatsapp_number:
            send_whatsapp_message(whatsapp_number, message)
        else:
            print(f"[BulkSearch] Could not extract valid phone number from thread_id: {thread_id}")
            
    except Exception as e:
        print(f"[BulkSearch] Failed to send WhatsApp message: {e}")


def send_whatsapp_message(phone_number: str, message: str):
    """
    Send a WhatsApp message via Twilio REST API.
    """
    print(f"[BulkSearch] Sending WhatsApp to {phone_number}")
    
    try:
        import os
        from twilio.rest import Client
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Get Twilio credentials from environment
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        twilio_whatsapp_number = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
        
        if not account_sid or not auth_token:
            print("[BulkSearch] ERROR: Twilio credentials not found in environment variables")
            print("[BulkSearch] Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in your .env file")
            return
        
        # Create Twilio client
        client = Client(account_sid, auth_token)
        
        # Send the WhatsApp message
        message_obj = client.messages.create(
            from_=twilio_whatsapp_number,
            body=message,
            to=phone_number
        )
        
        print(f"[BulkSearch] ✅ WhatsApp message sent successfully! Message SID: {message_obj.sid}")
        
    except Exception as e:
        print(f"[BulkSearch] ❌ Failed to send WhatsApp message: {e}")


def store_pending_message(thread_id: str, message: str):
    """
    Store a pending message for the user to receive on their next interaction.
    """
    print(f"[BulkSearch] Storing pending message for {thread_id}")
    
    # Use a simple in-memory storage for pending messages
    # In production, you might want to use Redis or a database
    try:
        global _pending_messages
        if '_pending_messages' not in globals():
            _pending_messages = {}
        
        if thread_id not in _pending_messages:
            _pending_messages[thread_id] = []
        
        _pending_messages[thread_id].append({
            'message': message,
            'timestamp': time.time()
        })
        
        print(f"[BulkSearch] Stored pending message for {thread_id}")
        
    except Exception as e:
        print(f"[BulkSearch] Failed to store pending message: {e}")


# Initialize worker on module import
start_background_worker()

   
