"""
Test the flight_flattener function with data from search_response_old.json
Output the results to a text file
"""
import json
import uuid
import sys
import os

def flatten_travelport_response(raw_response: dict):
    """
    Returns (string_summary, structured_summary)
    """
    # Updated to match actual data structure
    catalog_offers = raw_response.get("CatalogProductOfferingsResponse", {}).get("CatalogProductOfferings", {}).get("CatalogProductOffering", [])
    
    # In the actual data, ReferenceList is not a dict with nested lists, it's just empty or not present
    # So we'll use an empty dict as fallback
    reference_list = raw_response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", {})

    flattened_text = "✈️ *Available Flight Offers*\n\n"
    structured = []

    for i, offer in enumerate(catalog_offers, 1):
        offer_id = offer.get("id")
        departure = offer.get("Departure", "Unknown")
        arrival = offer.get("Arrival", "Unknown")
        pb_opts = offer.get("ProductBrandOptions", [])

        flattened_text += f"🧾 *Offer {i}* ({departure} → {arrival})\n"
        for p_idx, pbo in enumerate(pb_opts, 1):
            products = pbo.get("ProductBrandOffering", [])
            flights = pbo.get("flightRefs", [])
            
            # Extract prices from BestCombinablePrice
            prices = []
            for product in products:
                best_price = product.get("BestCombinablePrice", {})
                if best_price and "TotalPrice" in best_price:
                    prices.append(best_price["TotalPrice"])
            
            if prices:
                min_price = min(prices)
                max_price = max(prices)
                flattened_text += f"  • Option {p_idx}: {len(flights)} segment(s)\n"
                flattened_text += f"    Price Range: {min_price} – {max_price}\n"
            else:
                flattened_text += f"  • Option {p_idx}: {len(flights)} segment(s)\n"
                flattened_text += f"    Price Range: Not available\n"

        flattened_text += "---------------------------------------\n"

        # For structured output, we don't access reference_list as attributes since it may be a list or other format
        structured.append({
            "id": str(uuid.uuid4()),
            "offer_id": offer_id,
            "departure": departure,
            "arrival": arrival,
            "pbo_data": pb_opts,
        })

    return flattened_text, structured

def test_flight_flattener():
    """Test the flight_flattener function"""
    
    # Load the search response data
    with open('D:\\Projects\\personal\\tazaticket\\search_response_old.json', 'r', encoding='utf-8') as f:
        raw_response = json.load(f)
    
    print("Testing flight_flattener with search_response_old.json...")
    
    # Call the flattener function
    text_summary, structured_offers = flatten_travelport_response(raw_response)
    
    print("✅ Flight flattener executed successfully!\n")
    
    print("=== TEXT SUMMARY OUTPUT ===")
    print(text_summary)
    print("\n=== STRUCTURED OFFERS OUTPUT ===")
    print(json.dumps(structured_offers, indent=2))
    
    # Save output to a text file
    with open('flight_flattener_output.txt', 'w', encoding='utf-8') as f:
        f.write("=== FLIGHT FLATTENER OUTPUT ===\n\n")
        f.write("TEXT SUMMARY:\n")
        f.write(text_summary)
        f.write("\n\nSTRUCTURED OFFERS:\n")
        f.write(json.dumps(structured_offers, indent=2))
    
    print(f"\nOutput saved to: flight_flattener_output.txt")
    
    return text_summary, structured_offers

if __name__ == "__main__":
    test_flight_flattener()