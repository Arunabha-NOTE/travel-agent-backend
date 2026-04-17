"""Google Maps geocoding tool for the travel agent."""

from __future__ import annotations

import asyncio

import httpx
from langchain_core.tools import tool

from app.agents.tools.utils import persist_tool_result
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global lock to prevent rapid-fire API calls if needed, though Google is more lenient than Nominatim
_api_lock = asyncio.Lock()


@tool
async def geocode_place(place_name: str) -> str:
    """Geocode a place name to latitude/longitude using Google Maps.

    This tool also persists the found location data into the knowledge base.

    Args:
        place_name: The name of the place to geocode (e.g. "Kyoto, Japan").

    Returns:
        JSON-like string with lat, lon, display_name, and country.
    """
    # Check cache first (simplified in-memory cache handled by @lru_cache)
    # Note: We don't use lru_cache directly on the async tool, but we could implement a dict cache.

    logger.info("Geocode requested", place_name=place_name)
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": place_name,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    try:
        async with _api_lock:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. ATTEMPT GOOGLE MAPS
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("status") == "OK" and data.get("results"):
                        results = data.get("results")
                        top = results[0]
                        lat = top["geometry"]["location"]["lat"]
                        lon = top["geometry"]["location"]["lng"]
                        display = top.get("formatted_address", place_name)
                        country = "Unknown"
                        for comp in top.get("address_components", []):
                            if "country" in comp.get("types", []):
                                country = comp.get("long_name", "Unknown")
                                break
                        logger.info(
                            "Geocode resolved with Google Maps",
                            place_name=place_name,
                            provider="google_maps",
                            result_count=len(results),
                            country=country,
                        )
                        return _format_geocode_result(
                            place_name, display, lat, lon, country, "google_maps"
                        )
                    logger.warning(
                        "Google Maps geocode returned no usable result",
                        place_name=place_name,
                        status=data.get("status"),
                        result_count=len(data.get("results") or []),
                    )
                except Exception as g_err:
                    logger.warning(
                        "Google Maps primary geocode failed",
                        place_name=place_name,
                        error=str(g_err),
                    )

                # 2. FALLBACK TO NOMINATIM (OSM)
                logger.info("Attempting Nominatim fallback", place_name=place_name)
                osm_url = "https://nominatim.openstreetmap.org/search"
                osm_params = {"q": place_name, "format": "json", "limit": 1}
                headers = {"User-Agent": "TravelAI-Assistant/1.0"}

                resp = await client.get(osm_url, params=osm_params, headers=headers)
                resp.raise_for_status()
                osm_data = resp.json()

                if osm_data:
                    top = osm_data[0]
                    lat = float(top["lat"])
                    lon = float(top["lon"])
                    display = top.get("display_name", place_name)
                    # Extract country (crude check)
                    country = display.split(",")[-1].strip()
                    logger.info(
                        "Geocode resolved with Nominatim fallback",
                        place_name=place_name,
                        provider="nominatim",
                        country=country,
                    )
                    return _format_geocode_result(
                        place_name, display, lat, lon, country, "nominatim"
                    )

        output = f"Could not find location '{place_name}' after multiple attempts."
        logger.warning("Geocode returned no match", place_name=place_name)
        persist_tool_result(
            "geocode_place",
            output,
            metadata={"place_name": place_name},
            status="empty",
        )
        return output

    except Exception as e:
        logger.exception("Geocoding failed entirely", error=str(e), place=place_name)
        output = (
            f"Note: Could not geocode '{place_name}' due to a technical issue. "
            "Skipping map coordinates for this item."
        )
        persist_tool_result(
            "geocode_place",
            output,
            metadata={"place_name": place_name, "error": str(e)},
            status="error",
        )
        return output


def _format_geocode_result(
    original_name: str, display: str, lat: float, lon: float, country: str, source: str
) -> str:
    """Helper to format and persist geocode results."""
    logger.info(
        "Geocode result persisted",
        place_name=original_name,
        provider=source,
        lat=lat,
        lon=lon,
        country=country,
    )
    result_text = (
        f"Location: {display}\n"
        f"  Latitude: {lat}\n"
        f"  Longitude: {lon}\n"
        f"  Country: {country}\n"
        f"  Source: {source}"
    )

    persist_tool_result(
        "geocode_place",
        f"Geocoding result for '{original_name}': {display} at ({lat}, {lon}) in {country}.",
        metadata={
            "provider": source,
            "place_name": original_name,
            "lat": lat,
            "lon": lon,
            "country": country,
        },
        status="ok",
    )

    return result_text
