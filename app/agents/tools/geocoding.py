"""OpenStreetMap Nominatim geocoding tool for the travel agent."""

from __future__ import annotations

import httpx
from langchain_core.tools import tool


@tool
async def geocode_place(place_name: str) -> str:
    """Geocode a place name to latitude/longitude using OpenStreetMap Nominatim.

    Args:
        place_name: The name of the place to geocode (e.g. "Kyoto, Japan").

    Returns:
        JSON-like string with lat, lon, display_name, and country.
        Returns an error string if the place cannot be found.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": place_name,
        "format": "json",
        "limit": 3,
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": "TravelAI-Chatbot/1.0 (travel planning assistant)",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()

        if not results:
            return f"Could not find location: '{place_name}'"

        top = results[0]
        lat = float(top["lat"])
        lon = float(top["lon"])
        display = top.get("display_name", place_name)
        address = top.get("address", {})
        country = address.get("country", "Unknown country")

        lines = [
            f"Location: {display}",
            f"  Latitude: {lat}",
            f"  Longitude: {lon}",
            f"  Country: {country}",
        ]

        if len(results) > 1:
            lines.append("Other matches:")
            for r in results[1:]:
                lines.append(
                    f"  - {r.get('display_name', '')} (lat={r['lat']}, lon={r['lon']})"
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Geocoding failed for '{place_name}': {e}"
