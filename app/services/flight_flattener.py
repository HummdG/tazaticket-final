# app/services/flight_flattener.py
import uuid

def flatten_travelport_response(raw_response: dict):
    """
    Returns (string_summary, structured_summary)
    """
    catalog_offers = raw_response.get("CatalogProductOfferingsResponse", {}).get("CatalogProductOfferings", {}).get("CatalogProductOffering", [])
    reference_list = raw_response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", {})

    flattened_text = "✈️ *Available Flight Offers*\n\n"
    structured = []

    for i, offer in enumerate(catalog_offers, 1):
        offer_id = offer.get("id")
        pb_opts = offer.get("ProductBrandOptions", [])

        flattened_text += f"🧾 *Offer {i}* ({offer.get('Departure')} → {offer.get('Arrival')})\n"
        for p_idx, pbo in enumerate(pb_opts, 1):
            products = pbo.get("ProductBrandOffering", [])
            flights = pbo.get("flightRefs", [])
            prices = [p.get("BestCombinablePrice", {}).get("TotalPrice") for p in products if p.get("BestCombinablePrice")]
            min_price, max_price = (min(prices), max(prices)) if prices else (None, None)

            flattened_text += f"  • Option {p_idx}: {len(flights)} segment(s)\n"
            if min_price and max_price:
                flattened_text += f"    Price Range: {min_price} – {max_price}\n"
            elif min_price:
                flattened_text += f"    Price: {min_price}\n"

        flattened_text += "---------------------------------------\n"

        structured.append({
            "id": str(uuid.uuid4()),
            "offer_id": offer_id,
            "pbo_data": pb_opts,
            "brand_details": reference_list.get("ReferenceListBrand", []),
            "product_details": reference_list.get("ReferenceListProduct", []),
        })

    return flattened_text, structured