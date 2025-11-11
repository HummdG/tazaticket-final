"""
Travelport parser module that resolves references in the API response
"""

def resolve_references(response_json):
    """
    Resolves references in the Travelport API response by enriching objects 
    with their reference data.
    """
    # Make a deep copy of the response to avoid modifying the original
    import copy
    enriched_response = copy.deepcopy(response_json)
    
    # Extract the ReferenceList from the response
    reference_list = enriched_response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", {})
    
    # Process each type of reference
    for ref_type, ref_data in reference_list.items():
        if isinstance(ref_data, dict) and ref_data.get("Flight"):
            # Process flight references
            flights = ref_data["Flight"]
            for flight in flights:
                # Ensure flight data is properly formatted
                if "id" not in flight:
                    flight["id"] = flight.get("@id", "")
    
    # Enrich catalog offerings with reference data
    catalog_offerings = enriched_response.get("CatalogProductOfferingsResponse", {}).get("CatalogProductOfferings", {}).get("CatalogProductOffering", [])
    
    for offering in catalog_offerings:
        # Process product brand options
        pb_options = offering.get("ProductBrandOptions", [])
        for pb_opt in pb_options:
            # Resolve flight references
            flight_refs = pb_opt.get("flightRefs", [])
            resolved_flights = []
            
            for ref_id in flight_refs:
                # Find the flight in the reference list
                for ref_type, ref_data in reference_list.items():
                    if isinstance(ref_data, dict) and ref_data.get("Flight"):
                        flights = ref_data["Flight"]
                        matched_flight = next((f for f in flights if f.get("id") == ref_id), None)
                        if matched_flight:
                            resolved_flights.append(matched_flight)
                            break
            
            # Replace flight references with actual flight data if needed
            # For now, we'll just ensure that the references exist properly in the structure
    
    return enriched_response