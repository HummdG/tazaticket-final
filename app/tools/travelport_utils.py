"""
Utility functions for processing Travelport CatalogProductOfferings API responses
"""

from typing import Any, Dict, List, Optional

def _index_terms_by_id(resp: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build a dict: TermsAndConditionsID -> TermsAndConditionsAir block."""
    ref_list = (
        resp.get("CatalogProductOfferingsResponse", {})
            .get("ReferenceListTermsAndConditions", {})
            .get("TermsAndConditions", [])
    )
    return {t.get("id"): t for t in ref_list if isinstance(t, dict) and t.get("@type", "").startswith("TermsAndConditions")}

def _first_number(v: Any, default=None):
    try:
        return float(v)
    except Exception:
        return default

def _extract_baggage(terms_block: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact baggage summary from a TermsAndConditionsAir block."""
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
    if not terms_block:
        return out

    # Try to get validating airline from multiple possible locations
    validating_airline_code = None
    
    # First try validatingAirlineCode (direct field)
    if "validatingAirlineCode" in terms_block:
        validating_airline_code = terms_block["validatingAirlineCode"]
    # Fallback to existing ValidatingAirline structure
    elif "ValidatingAirline" in terms_block:
        validating_airline_info = (
            (terms_block.get("ValidatingAirline") or [{}])[0] or {}
        )
        validating_airline_code = validating_airline_info.get("ValidatingAirline")
    
    out["validating_airline"] = validating_airline_code

    out["payment_time_limit"] = terms_block.get("PaymentTimeLimit")

    # Penalties (very compact; extend if you need detail per PAX/seg)
    pen = (terms_block.get("Penalties") or [{}])[0]
    change = (pen.get("Change") or [{}])[0]
    cancel = (pen.get("Cancel") or [{}])[0]
    if change:
        # prefer percent, else amount
        ch = (change.get("Penalty") or [{}])[0]
        out["penalties_change"] = (
            f"{ch.get('Percent')}%"
            if "Percent" in ch
            else (f"{ch.get('Amount', {}).get('value')} {ch.get('Amount', {}).get('code')}" if "Amount" in ch else None)
        )
    if cancel:
        ca = (cancel.get("Penalty") or [{}])[0]
        out["penalties_cancel"] = (
            f"{ca.get('Percent')}%"
            if "Percent" in ca
            else (f"{ca.get('Amount', {}).get('value')} {ca.get('Amount', {}).get('code')}" if "Amount" in ca else None)
        )

    # Baggage
    for b in terms_block.get("BaggageAllowance", []):
        btype = b.get("baggageType")
        items = b.get("BaggageItem") or []
        if btype == "FirstCheckedBag":
            out["checked_bag_included"] = any(i.get("includedInOfferPrice") == "Yes" for i in items)
            # try to find a weight measurement
            kg = None
            for i in items:
                for m in i.get("Measurement", []):
                    if m.get("measurementType") == "Weight" and m.get("unit") in {"Kilograms", "KG", "Kg"}:
                        kg = _first_number(m.get("value"))
                        break
            out["checked_bag_allowance_kg"] = kg
        elif btype == "CarryOn":
            out["carry_on_included"] = any(i.get("includedInOfferPrice") == "Yes" for i in items)
            # look for "quantity" or helpful text like "1P"
            qty = None
            text = None
            for i in items:
                if "quantity" in i and i["quantity"] is not None:
                    qty = int(i["quantity"])
                if "Text" in i:
                    text = i["Text"]
                    if isinstance(text, list) and text:
                        text = text[0]
            # some providers put piece count in top-level Text list: ["1P"]
            top_text = b.get("Text")
            if not text and isinstance(top_text, list) and top_text:
                text = top_text[0]
            out["carry_on_piece_count"] = qty
            out["carry_on_text"] = text
    return out

def _index_flights_by_ref(resp: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Optional: map flightRefs (e.g., 's1') to flight details if present in a
    'ReferenceListFlight' or similar block. Falls back gracefully if missing.
    """
    # Common locations (names differ across Travelport tenants); extend as needed.
    candidates = [
        ("ReferenceListFlight", "Flight"),
        ("ReferenceListSegment", "Segment"),
        ("ReferenceListAirSegment", "AirSegment"),
    ]
    idx = {}
    root = resp.get("CatalogProductOfferingsResponse", {})
    for list_name, item_name in candidates:
        block = root.get(list_name) or {}
        items = block.get(item_name) or []
        for f in items:
            ref_id = f.get("id") or f.get("flightRef") or f.get("segmentRef")
            if ref_id:
                idx[ref_id] = f
    return idx

def _duration_minutes(v: Optional[str]) -> Optional[int]:
    """
    Convert ISO 8601 duration 'PT1H45M' to minutes. Returns None if not parseable.
    """
    if not v or not isinstance(v, str) or not v.startswith("PT"):
        return None
    h, m = 0, 0
    # rough parse
    import re
    mh = re.search(r"(\d+)H", v)
    mm = re.search(r"(\d+)M", v)
    if mh: h = int(mh.group(1))
    if mm: m = int(mm.group(1))
    return h * 60 + m

def _summarize_product_option(option: Dict[str, Any],
                              terms_index: Dict[str, Dict[str, Any]],
                              flights_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize one ProductBrandOffering (price, baggage, duration, stops)."""
    best = option.get("BestCombinablePrice", {}) or {}
    price = {
        "currency": (best.get("CurrencyCode") or {}).get("value"),
        "total": _first_number(best.get("TotalPrice")),
        "base": _first_number(best.get("Base")),
        "taxes": _first_number(best.get("TotalTaxes")),
    }

    # baggage via TermsAndConditionsRef
    terms_ref = (option.get("TermsAndConditions") or {}).get("termsAndConditionsRef")
    baggage = _extract_baggage(terms_index.get(terms_ref, {}))

    # flight durations / stops using flightRefs
    flight_refs = (option.get("flightRefs") or [])  # sometimes attached at ProductBrandOptions level
    # Some schemas put flightRefs on the surrounding ProductBrandOptions; we'll stitch that at the caller.

    return {
        "price": price,
        "baggage": baggage,
        "flightRefs": flight_refs,  # will be populated by caller if empty
    }

def summarize_offering(offering: Dict[str, Any],
                       terms_index: Dict[str, Dict[str, Any]],
                       flights_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Flatten ProductBrandOptions → ProductBrandOffering with price, baggage,
    duration & stops when available. Returns a list of options with
    per-option flight summaries.
    """
    results = []
    for pbo in offering.get("ProductBrandOptions", []):
        refs_here = pbo.get("flightRefs") or []
        for pboff in pbo.get("ProductBrandOffering", []):
            row = _summarize_product_option(pboff, terms_index, flights_index)
            if not row["flightRefs"]:
                row["flightRefs"] = refs_here

            # derive duration & stops from referenced flights if available
            durations = []
            total_stops = 0
            for ref in row["flightRefs"]:
                f = flights_index.get(ref, {})
                # Common keys: "Journey", "TotalElapsedTime", "Stops", "duration", etc.
                # We normalize to minutes and integers when possible.
                iso = f.get("duration") or f.get("ElapsedTime") or f.get("TotalElapsedTime")
                dur_min = _duration_minutes(iso) if isinstance(iso, str) else (int(iso) if isinstance(iso, (int, float)) else None)
                if dur_min: durations.append(dur_min)
                stops = f.get("Stops") or f.get("stops")
                if isinstance(stops, (int, float)):
                    total_stops += int(stops)

            row["duration_minutes_total"] = sum(durations) if durations else None
            row["stops_total"] = total_stops if total_stops else 0
            results.append(row)
    return results

def extract_cheapest_one_way_summary(resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pick the cheapest option from a one-way response and return a compact summary.
    """
    root = resp.get("CatalogProductOfferingsResponse", {})
    cpo = root.get("CatalogProductOfferings", {}) or {}
    offerings = cpo.get("CatalogProductOffering") or []
    if not offerings:
        return None

    terms_idx = _index_terms_by_id(resp)
    flights_idx = _index_flights_by_ref(resp)

    # One-way usually has a single offering (sequence 1). If multiple, we scan all.
    all_options = []
    for off in offerings:
        all_options.extend(summarize_offering(off, terms_idx, flights_idx))

    if not all_options:
        return None
    cheapest = min(all_options, key=lambda o: (o["price"]["total"] if o["price"]["total"] is not None else 1e12))

    return {
        "direction": "outbound",
        "price": cheapest["price"],
        "duration_minutes_total": cheapest.get("duration_minutes_total"),
        "stops_total": cheapest.get("stops_total"),
        "baggage": cheapest.get("baggage"),
        "flightRefs": cheapest.get("flightRefs"),
    }

def extract_cheapest_round_trip_summary(resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Round-trip responses typically include two offerings (sequence 1 outbound, 2 inbound).
    We pick the cheapest option from each direction and return a combined view.
    """
    root = resp.get("CatalogProductOfferingsResponse", {})
    cpo = root.get("CatalogProductOfferings", {}) or {}
    offerings = cpo.get("CatalogProductOffering") or []
    if not offerings:
        return None

    terms_idx = _index_terms_by_id(resp)
    flights_idx = _index_flights_by_ref(resp)

    # Split by sequence
    by_seq: Dict[int, List[Dict[str, Any]]] = {}
    for off in offerings:
        seq = int(off.get("sequence", 0))
        by_seq.setdefault(seq, []).extend(summarize_offering(off, terms_idx, flights_idx))

    if not by_seq:
        return None

    def pick_cheapest(opts: List[Dict[str, Any]]):
        return min(opts, key=lambda o: (o["price"]["total"] if o["price"]["total"] is not None else 1e12))

    outbound = pick_cheapest(by_seq.get(1, [])) if by_seq.get(1) else None
    inbound = pick_cheapest(by_seq.get(2, [])) if by_seq.get(2) else None
    if not outbound:
        return None

    total_price = (outbound["price"]["total"] or 0) + ((inbound or {}).get("price", {}).get("total") or 0)

    return {
        "price_total": {"currency": outbound["price"]["currency"], "total": total_price},
        "outbound": {
            "price": outbound["price"],
            "duration_minutes_total": outbound.get("duration_minutes_total"),
            "stops_total": outbound.get("stops_total"),
            "baggage": outbound.get("baggage"),
            "flightRefs": outbound.get("flightRefs"),
        },
        "inbound": None if not inbound else {
            "price": inbound["price"],
            "duration_minutes_total": inbound.get("duration_minutes_total"),
            "stops_total": inbound.get("stops_total"),
            "baggage": inbound.get("baggage"),
            "flightRefs": inbound.get("flightRefs"),
        },
    } 