"""
Test the latest flight_flattener function with data from search_response_old.json
Output the results to a text file
"""
import json
import uuid
from datetime import datetime
import sys
import os

def parse_iso_duration_minutes(duration_str):
    """Convert ISO duration (e.g. PT2H45M) to total minutes."""
    if not duration_str or not duration_str.startswith("PT"):
        return 0
    hours = 0
    minutes = 0
    duration_str = duration_str.replace("PT", "")
    if "H" in duration_str:
        parts = duration_str.split("H")
        hours = int(parts[0])
        duration_str = parts[1] if len(parts) > 1 else ""
    if "M" in duration_str:
        minutes = int(duration_str.replace("M", ""))
    return hours * 60 + minutes

def human_duration(mins):
    h, m = divmod(mins, 60)
    return f"{h}h {m}m" if h else f"{m}m"

def flatten_travelport_response(raw_response: dict):
    """
    Build structured + flattened text summary with fully dereferenced
    brand, product, terms, and flight details.
    """
    catalog_offers = (
        raw_response.get("CatalogProductOfferingsResponse", {})
        .get("CatalogProductOfferings", {})
        .get("CatalogProductOffering", [])
    )
    reference_list = (
        raw_response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", [])
    )

    flattened_text = "✈️ *Available Flight Offers*\n\n"
    structured = []

    # Build reference lookup maps
    ref_map = {"Product": {}, "Brand": {}, "Terms": {}, "Flight": {}}
    for ref in reference_list:
        t = ref.get("@type")
        if t == "ReferenceListProduct":
            for p in ref.get("Product", []):
                ref_map["Product"][p.get("id")] = p
        elif t == "ReferenceListBrand":
            for b in ref.get("Brand", []):
                ref_map["Brand"][b.get("id")] = b
        elif t == "ReferenceListTermsAndConditions":
            for t_item in ref.get("TermsAndConditions", []):
                ref_map["Terms"][t_item.get("id")] = t_item
        elif t == "ReferenceListFlight":
            for f in ref.get("Flight", []):
                ref_map["Flight"][f.get("id")] = f

    def calculate_layover(flights):
        """Calculate layover between two flights."""
        if len(flights) < 2:
            return None
        try:
            arr = flights[0].get("Arrival", {})
            dep = flights[1].get("Departure", {})
            arr_time = datetime.fromisoformat(f"{arr.get('date')}T{arr.get('time')}")
            dep_time = datetime.fromisoformat(f"{dep.get('date')}T{dep.get('time')}")
            diff = int((dep_time - arr_time).total_seconds() // 60)
            if diff < 0:
                diff += 24 * 60  # handle overnight
            return human_duration(diff), arr.get("location")
        except Exception:
            return None

    # Iterate over each offer
    for i, offer in enumerate(catalog_offers, 1):
        offer_id = offer.get("id")
        pb_opts = offer.get("ProductBrandOptions", [])

        offer_struct = {
            "id": str(uuid.uuid4()),
            "offer_id": offer_id,
            "departure": offer.get("Departure"),
            "arrival": offer.get("Arrival"),
            "options": [],
        }

        flattened_text += f"🧾 *Offer {i}* ({offer.get('Departure')} → {offer.get('Arrival')})\n"

        for opt_idx, pbo in enumerate(pb_opts, 1):
            product_offerings = pbo.get("ProductBrandOffering", [])
            flight_refs = pbo.get("flightRefs", [])
            flights = [ref_map["Flight"].get(r) for r in flight_refs if r in ref_map["Flight"]]

            stops = max(0, len(flights) - 1)
            layover_summary = ""
            if stops > 0:
                layover = calculate_layover(flights)
                if layover:
                    layover_summary = f"{stops} stop(s) via {layover[1]} ({layover[0]})"
                else:
                    layover_summary = f"{stops} stop(s)"

            # Each ProductBrandOffering
            for prod in product_offerings:
                brand_ref = prod.get("Brand", {}).get("BrandRef")
                product_ref = (
                    prod.get("Product", [{}])[0].get("productRef")
                    if prod.get("Product")
                    else None
                )
                terms_ref = (
                    prod.get("TermsAndConditions", {}).get("termsAndConditionsRef")
                )

                # Dereference all three
                brand_obj = ref_map["Brand"].get(brand_ref, {"id": brand_ref})
                product_obj = ref_map["Product"].get(product_ref, {"id": product_ref})
                terms_obj = ref_map["Terms"].get(terms_ref, {"id": terms_ref})

                # Price info
                price_info = prod.get("BestCombinablePrice", {}) or {}
                price = price_info.get("TotalPrice")
                currency = (
                    price_info.get("CurrencyCode", {}).get("value")
                    if isinstance(price_info.get("CurrencyCode"), dict)
                    else price_info.get("CurrencyCode")
                )

                # Build structured record
                option_struct = {
                    "brand": brand_obj,
                    "product": product_obj,
                    "terms": terms_obj,
                    "flights": flights,
                    "stops": stops,
                    "layover": layover_summary,
                    "price": price,
                    "currency": currency,
                }
                offer_struct["options"].append(option_struct)

                # Build text output
                flattened_text += f"  • {brand_obj.get('name') or brand_ref} | 💰 {price} {currency or ''}\n"
                for f in flights:
                    if not f:
                        continue
                    dep = f.get("Departure", {})
                    arr = f.get("Arrival", {})
                    flattened_text += (
                        f"    ✈️ {dep.get('location')} ({dep.get('time')}) → "
                        f"{arr.get('location')} ({arr.get('time')})\n"
                    )
                if layover_summary:
                    flattened_text += f"    ⏱️ {layover_summary}\n"
                flattened_text += "\n"

        flattened_text += "---------------------------------------\n"
        structured.append(offer_struct)

    return flattened_text, structured

def test_flight_flattener():
    """Test the latest flight_flattener function"""
    
    # Load the search response data
    with open('D:\\Projects\\personal\\tazaticket\\search_response_old.json', 'r', encoding='utf-8') as f:
        raw_response = json.load(f)
    
    print("Testing latest flight_flattener with search_response_old.json...")
    
    # Call the flattener function
    text_summary, structured_offers = flatten_travelport_response(raw_response)
    
    print("✅ Latest flight flattener executed successfully!\n")
    
    print("=== TEXT SUMMARY OUTPUT ===")
    print(text_summary)
    print("\n=== STRUCTURED OFFERS OUTPUT ===")
    print(json.dumps(structured_offers, indent=2))
    
    # Save output to a text file
    with open('latest_flight_flattener_output.txt', 'w', encoding='utf-8') as f:
        f.write("=== LATEST FLIGHT FLATTENER OUTPUT ===\n\n")
        f.write("TEXT SUMMARY:\n")
        f.write(text_summary)
        f.write("\n\nSTRUCTURED OFFERS:\n")
        f.write(json.dumps(structured_offers, indent=2))
    
    print(f"\nOutput saved to: latest_flight_flattener_output.txt")
    
    return text_summary, structured_offers

if __name__ == "__main__":
    test_flight_flattener()