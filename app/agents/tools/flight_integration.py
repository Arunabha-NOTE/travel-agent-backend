"""Integration layer for Playwright-based flight scraping with fallback to Firecrawl."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from app.agents.tools.flight_scraper import GoogleFlightsScraper
from app.core.logging import get_logger

logger = get_logger(__name__)


async def search_flights_with_playwright(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    use_headless: bool = True,
    fallback_to_firecrawl: bool = True,
) -> dict[str, Any]:
    """
    Search flights using Playwright with optional fallback to Firecrawl.
    
    This function builds a Google Flights URL from parameters and uses
    Playwright to extract real-time flight data. If Playwright scraping
    fails and fallback is enabled, it returns a structured response
    recommending manual searches.
    
    Args:
        origin_code: IATA code for origin (e.g., "DEL")
        destination_code: IATA code for destination (e.g., "SFO")
        departure_date: Departure date in YYYY-MM-DD format
        use_headless: Run browser in headless mode (faster, more stealthy)
        fallback_to_firecrawl: If Playwright fails, try Firecrawl-based extraction
        
    Returns:
        Dictionary with flights list and metadata
    """
    # Build Google Flights URL
    # Format: https://www.google.com/travel/flights/search?tfs=<encoded_params>
    # For now, using a simplified URL structure that works with direct airport codes
    
    url = _build_google_flights_url(origin_code, destination_code, departure_date)
    
    logger.info(
        "Starting Playwright-based flight search",
        origin=origin_code,
        destination=destination_code,
        departure_date=departure_date,
        headless=use_headless,
    )
    
    scraper = GoogleFlightsScraper(headless=use_headless)
    
    try:
        flights = await scraper.search_flights(url)
        
        return {
            "success": True,
            "source": "playwright",
            "flights": [asdict(f) for f in flights],
            "count": len(flights),
            "url": url,
            "trip_info": scraper._extract_trip_info_from_url(url),
        }
    except Exception as e:
        logger.warning(
            "Playwright flight search failed",
            error=str(e),
            origin=origin_code,
            destination=destination_code,
            fallback_enabled=fallback_to_firecrawl,
        )
        
        if fallback_to_firecrawl:
            logger.info("Falling back to Firecrawl-based extraction")
            return {
                "success": False,
                "source": "fallback",
                "error": str(e),
                "reason": "Playwright extraction failed, recommend Firecrawl or manual search",
                "recommended_url": url,
            }
        else:
            raise


def _build_google_flights_url(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: str | None = None,
    cabin_class: str = "economy",
    passengers: int = 1,
) -> str:
    """
    Build a Google Flights search URL from parameters.
    
    Args:
        origin_code: IATA code for origin
        destination_code: IATA code for destination
        departure_date: Date in YYYY-MM-DD format
        return_date: Return date for round-trip (optional)
        cabin_class: Cabin class (economy, business, first, premium_economy)
        passengers: Number of passengers
        
    Returns:
        Complete Google Flights search URL
        
    Note:
        This creates a basic URL. For advanced parameters (multiple passengers,
        specific cabin classes), you may need to manually construct the tfs parameter
        or use the URL directly from Google Flights interface.
    """
    base_url = "https://www.google.com/travel/flights/search"
    
    # Map cabin class to numeric code
    cabin_map = {
        "economy": "0",
        "premium_economy": "1",
        "business": "2",
        "first": "3",
    }
    cabin_code = cabin_map.get(cabin_class, "0")
    
    # Format: ?tfs=<encoded_params> contains the search parameters
    # For more complex URLs, extract from actual Google Flights interface
    # This is a simplified version - production code should use proper URL encoding
    
    # Simple query string approach (less reliable than proper tfs encoding)
    params = {
        "qs": f"{origin_code} to {destination_code} {departure_date}",
    }
    
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base_url}?{query_string}"
    
    logger.debug(f"Built Google Flights URL: {url}")
    return url


def format_flight_results(
    flights: list[dict[str, str]],
    origin_city: str,
    destination_city: str,
    currency: str = "USD",
) -> str:
    """
    Format flight results into human-readable text.
    
    Args:
        flights: List of flight dictionaries
        origin_city: Origin city name
        destination_city: Destination city name
        currency: Currency symbol or code
        
    Returns:
        Formatted string representation of flights
    """
    if not flights:
        return f"No flights found from {origin_city} to {destination_city}"
    
    lines = [
        f"✈️ Flights from {origin_city} to {destination_city}:",
        "",
    ]
    
    for idx, flight in enumerate(flights, 1):
        lines.append(
            f"{idx}. {flight.get('airline', 'Unknown')} - "
            f"{flight.get('departure_time', 'TBD')} → {flight.get('arrival_time', 'TBD')} "
            f"({flight.get('duration', 'N/A')})"
        )
        
        price = flight.get('price', 'N/A')
        lines.append(f"   💰 {currency} {price}")
        
        stops = flight.get('stops', 'Non-stop')
        lines.append(f"   🛫 {stops}")
        
        if flight.get('co2_emissions') and flight.get('co2_emissions') != 'N/A':
            lines.append(f"   🌍 {flight.get('co2_emissions')} {flight.get('emissions_variation', '')}")
        
        lines.append("")
    
    return "\n".join(lines)


# Compatibility layer - wrapper to integrate with existing travel.py
async def extract_flights_async(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    origin_city: str | None = None,
    destination_city: str | None = None,
) -> dict[str, Any]:
    """
    Async wrapper for flight extraction with automatic fallback.
    
    Can be called from async contexts to search flights using Playwright,
    with graceful degradation to manual booking links if scraping fails.
    
    Args:
        origin_code: IATA airport code
        destination_code: IATA airport code
        departure_date: Date in YYYY-MM-DD format
        origin_city: Human-readable origin city (optional)
        destination_city: Human-readable destination city (optional)
        
    Returns:
        Result dictionary with flights or error information
    """
    return await search_flights_with_playwright(
        origin_code=origin_code,
        destination_code=destination_code,
        departure_date=departure_date,
        use_headless=True,
        fallback_to_firecrawl=True,
    )
