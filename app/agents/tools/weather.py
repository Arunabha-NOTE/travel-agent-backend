"""Open-Meteo weather tool for the travel agent."""

from __future__ import annotations

import httpx
from langchain_core.tools import tool

from app.agents.tools.utils import persist_tool_result


@tool
async def get_weather(
    lat: float, lon: float, days: int = 7, is_public: bool = False
) -> str:
    """Fetch current and forecast weather for a location.

    Args:
        lat: Latitude of the location.
        lon: Longitude of the location.
        days: Number of forecast days (1-16, default 7).
        is_public: Set to True if this weather data is for a general city and useful for everyone today.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weathercode,windspeed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
        "forecast_days": min(days, 16),
        "timezone": "auto",
    }

    wmo_descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Icy fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Slight showers",
        81: "Moderate showers",
        82: "Violent showers",
        95: "Thunderstorm",
        99: "Thunderstorm with hail",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})
        tz = data.get("timezone", "UTC")

        current_code = current.get("weathercode", 0)
        current_desc = wmo_descriptions.get(current_code, "Unknown")
        temp = current.get("temperature_2m", "N/A")
        wind = current.get("windspeed_10m", "N/A")

        lines = [
            f"Current weather (timezone: {tz}):",
            f"  • Condition: {current_desc}",
            f"  • Temperature: {temp}°C",
            f"  • Wind speed: {wind} km/h",
            "",
            "7-day forecast:",
        ]

        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        codes = daily.get("weathercode", [])

        for i, date in enumerate(dates[:7]):
            code = codes[i] if i < len(codes) else 0
            desc = wmo_descriptions.get(code, "Unknown")
            hi = max_temps[i] if i < len(max_temps) else "N/A"
            lo = min_temps[i] if i < len(min_temps) else "N/A"
            rain = precip[i] if i < len(precip) else 0
            lines.append(f"  {date}: {desc}, High {hi}°C / Low {lo}°C, Precip {rain}mm")

        output = "\n".join(lines)
        persist_tool_result(
            "get_weather",
            output,
            metadata={"lat": lat, "lon": lon, "days": min(days, 16)},
            status="ok",
            is_public=is_public,
        )
        return output

    except Exception as e:
        output = (
            f"Weather data currently unavailable due to a technical issue ({e}). "
            "Please use your general knowledge of the region's climate for the requested month, "
            "or perform a web search for a general city-level forecast."
        )
        persist_tool_result(
            "get_weather",
            output,
            metadata={"lat": lat, "lon": lon, "days": min(days, 16), "error": str(e)},
            status="error",
            is_public=is_public,
        )
        return output
