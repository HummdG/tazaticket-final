"""
Travelport Data Adapter - Normalization and validation layer for Travelport API data
"""
import json
from typing import Dict, Any
from app.tools.travelport_parser import resolve_references


class TravelportDataAdapter:
    @staticmethod
    def normalize_search_response(raw_response: Dict[str, Any]) -> Dict[str, Any]:
        # validate essential keys for raw response
        catalog_response = raw_response.get("CatalogProductOfferingsResponse", {})
        if not catalog_response:
            raise ValueError("Invalid search response: missing CatalogProductOfferingsResponse")
        
        catalog_offerings = catalog_response.get("CatalogProductOfferings", {})
        if not catalog_offerings:
            raise ValueError("Invalid search response: missing CatalogProductOfferings")
        
        offerings = catalog_offerings.get("CatalogProductOffering", [])
        if not offerings:
            raise ValueError("Invalid search response: missing CatalogProductOffering")
        
        # apply parser to create ResolvedOfferings
        parsed = resolve_references(raw_response)
        return parsed

    @staticmethod
    def validate_payload(payload: Dict[str, Any]) -> bool:
        # simple schema checks
        if payload.get("@type") != "OfferQueryBuildFromProducts":
            return False
        if "BuildFromProductsRequest" not in payload:
            return False
        # further validate each ProductCriteriaAir entry
        for pc in payload["BuildFromProductsRequest"]["ProductCriteriaAir"]:
            if "SpecificFlightCriteria" not in pc:
                return False
        return True