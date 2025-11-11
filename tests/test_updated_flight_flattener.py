"""
Test the updated flight_flattener function with data from search_response_old.json
Output the results to a text file
"""
import json
import uuid
import sys
import os

def flatten_travelport_response(raw_response: dict):
    """
    Returns (string_summary, structured_summary)
    Builds flattened text after structuring brand/product/terms details
    so each option has its own accurate information.
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

    # Pre-index references for quick lookup
    ref_map = {"Product": {}, "Brand": {}, "Terms": {}}
    for ref in reference_list:
        if ref.get("@type") == "ReferenceListProduct":
            for p in ref.get("Product", []):
                ref_map["Product"][p.get("id")] = p
        elif ref.get("@type") == "ReferenceListBrand":
            for b in ref.get("Brand", []):
                ref_map["Brand"][b.get("id")] = b
        elif ref.get("@type") == "ReferenceListTermsAndConditions":
            for t in ref.get("TermsAndConditions", []):
                ref_map["Terms"][t.get("id")] = t

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

        # Build per-option structured details
        for opt_idx, pbo in enumerate(pb_opts, 1):
            product_offerings = pbo.get("ProductBrandOffering", [])
            flight_refs = pbo.get("flightRefs", [])
            option_structs = []

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

                brand_name = ref_map["Brand"].get(brand_ref, {}).get("name")
                product_info = ref_map["Product"].get(product_ref, {})
                terms_info = ref_map["Terms"].get(terms_ref, {})

                # Price info
                price_info = prod.get("BestCombinablePrice", {}) or {}
                price = price_info.get("TotalPrice")
                currency = (
                    price_info.get("CurrencyCode", {}).get("value")
                    if isinstance(price_info.get("CurrencyCode"), dict)
                    else price_info.get("CurrencyCode")
                )

                # Add to structured option
                option_struct = {
                    "brand": brand_name or brand_ref,
                    "product_ref": product_ref,
                    "terms_ref": terms_ref,
                    "price": price,
                    "currency": currency,
                    "flightRefs": flight_refs,
                    "fare_basis": product_info.get("fareBasisCode"),
                    "cabin": (
                        product_info.get("cabin")
                        or product_info.get("cabinClass")
                        or None
                    ),
                }
                option_structs.append(option_struct)

            offer_struct["options"].extend(option_structs)

        # Add structured offer now before text building
        structured.append(offer_struct)

        # Build text after structure so we can use full info
        flattened_text += f"🧾 *Offer {i}* ({offer.get('Departure')} → {offer.get('Arrival')})\n"
        for idx, opt in enumerate(offer_struct["options"], 1):
            flattened_text += (
                f"  • Option {idx}: {opt['brand'] or 'N/A'} | "
                f"{opt['cabin'] or 'Unknown Cabin'}\n"
                f"    💰 {opt['price']} {opt['currency'] or ''}\n"
                f"    Fare Basis: {opt['fare_basis'] or 'N/A'}\n"
            )
            flattened_text += f"    Flights: {', '.join(opt.get('flightRefs', []))}\n"
        flattened_text += "---------------------------------------\n"

    return flattened_text, structured

def test_flight_flattener():
    """Test the updated flight_flattener function"""
    
    # Load the search response data
    with open('D:\\Projects\\personal\\tazaticket\\search_response_old.json', 'r', encoding='utf-8') as f:
        raw_response = json.load(f)
    
    print("Testing updated flight_flattener with search_response_old.json...")
    
    # Call the flattener function
    text_summary, structured_offers = flatten_travelport_response(raw_response)
    
    print("✅ Updated flight flattener executed successfully!\n")
    
    print("=== TEXT SUMMARY OUTPUT ===")
    print(text_summary)
    print("\n=== STRUCTURED OFFERS OUTPUT ===")
    print(json.dumps(structured_offers, indent=2))
    
    # Save output to a text file
    with open('updated_flight_flattener_output.txt', 'w', encoding='utf-8') as f:
        f.write("=== UPDATED FLIGHT FLATTENER OUTPUT ===\n\n")
        f.write("TEXT SUMMARY:\n")
        f.write(text_summary)
        f.write("\n\nSTRUCTURED OFFERS:\n")
        f.write(json.dumps(structured_offers, indent=2))
    
    print(f"\nOutput saved to: updated_flight_flattener_output.txt")
    
    return text_summary, structured_offers

if __name__ == "__main__":
    test_flight_flattener()