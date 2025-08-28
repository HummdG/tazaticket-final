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

   
