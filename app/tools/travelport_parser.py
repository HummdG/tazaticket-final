"""
Travelport Parser Utility
Resolves Product, Brand, Flight, and TermsAndConditions references
from CatalogProductOfferingsResponse.ReferenceList into a unified, human-readable structure.
"""

from typing import Dict, Any, List, Optional

def resolve_references(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a simplified, enriched response with all references resolved.
    Useful for generating conversational outputs or storing in Redis.
    """
    try:
        # Handle the actual structure from the real Travelport response
        ref_lists = response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", [])
        index = {"Product": {}, "Brand": {}, "TermsAndConditions": {}, "Flight": {}}

        # Build lookup tables - handle the actual structure in the real response
        for ref in ref_lists:
            # Check for different reference list types
            if ref.get("@type") == "ReferenceListProduct":
                for p in ref.get("Product", []):
                    index["Product"][p["id"]] = p
            elif ref.get("@type") == "ReferenceListBrand":
                for b in ref.get("Brand", []):
                    index["Brand"][b["id"]] = b
            elif ref.get("@type") == "ReferenceListTermsAndConditions":
                for t in ref.get("TermsAndConditions", []):
                    index["TermsAndConditions"][t["id"]] = t
            elif ref.get("@type") == "ReferenceListFlight":
                for f in ref.get("Flight", []):
                    index["Flight"][f["id"]] = f

        # Expand offerings
        offerings = response.get("CatalogProductOfferingsResponse", {}) \
                            .get("CatalogProductOfferings", {}) \
                            .get("CatalogProductOffering", [])
        enriched_offerings = []

        for offer in offerings:
            offer_data = {
                "id": offer.get("id"),
                "sequence": offer.get("sequence"),
                "ProductBrandOptions": [],
            }

            for option in offer.get("ProductBrandOptions", []):
                for pbo in option.get("ProductBrandOffering", []):
                    # Get references with the correct structure
                    product_id = None
                    brand_id = None
                    terms_id = None
                    
                    # Product reference
                    product_ref_obj = pbo.get("Product", [])
                    if product_ref_obj and len(product_ref_obj) > 0:
                        product_id = product_ref_obj[0].get("productRef")
                    
                    # Brand reference
                    brand_ref_obj = pbo.get("Brand", {})
                    if brand_ref_obj:
                        brand_id = brand_ref_obj.get("BrandRef")
                    
                    # TermsAndConditions reference
                    terms_ref_obj = pbo.get("TermsAndConditions", {})
                    if terms_ref_obj:
                        terms_id = terms_ref_obj.get("termsAndConditionsRef")

                    product = index["Product"].get(product_id, {})
                    brand = index["Brand"].get(brand_id, {})
                    terms = index["TermsAndConditions"].get(terms_id, {})

                    # Extract additional product information from nested structure
                    cabin_class = None
                    fare_basis_code = None
                    product_description = None
                    
                    # Look for cabin class and fare basis in PassengerFlight -> FlightProduct
                    passenger_flights = product.get("PassengerFlight", [])
                    if passenger_flights and len(passenger_flights) > 0:
                        flight_products = passenger_flights[0].get("FlightProduct", [])
                        if flight_products and len(flight_products) > 0:
                            fp = flight_products[0]
                            cabin_class = fp.get("cabin")
                            fare_basis_code = fp.get("fareBasisCode")
                            
                    # Use product description or ID as fallback
                    product_description = product.get("id")

                    # Get price information
                    price_info = pbo.get("BestCombinablePrice", {})
                    total_price = price_info.get("TotalPrice") if price_info else None
                    currency_info = price_info.get("CurrencyCode", {}) if price_info else {}
                    currency_value = currency_info.get("value") if currency_info else None

                    pbo_resolved = {
                        "brand_name": brand.get("name") if brand else None,
                        "product_name": product_description,
                        "fare_basis": fare_basis_code,
                        "cabin_class": cabin_class,
                        "terms": terms.get("id") if terms else None,  # Using ID as fallback
                        "price": total_price,
                        "currency": currency_value,
                        "flightRefs": option.get("flightRefs", []),
                        "flight_details": [index["Flight"].get(fid, {}) for fid in option.get("flightRefs", [])],
                    }

                    offer_data["ProductBrandOptions"].append(pbo_resolved)
            enriched_offerings.append(offer_data)

        response["ResolvedOfferings"] = enriched_offerings
        return response

    except Exception as e:
        print(f"[TravelportParser] Error resolving references: {e}")
        return response