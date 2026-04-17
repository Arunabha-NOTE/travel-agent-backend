"""
Example: Integrating Playwright flight scraper with existing travel.py tool

This file shows how to enhance the existing search_flights() function 
with Playwright-based extraction while maintaining backward compatibility.
"""

# OPTION 1: Add as an alternative extraction method in search_flights()
# =====================================================================

from app.agents.tools.flight_integration import (
    search_flights_with_playwright,
    format_flight_results
)


# In travel.py, enhance the search_flights() function like this:

async def search_flights_enhanced(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    return_date: str | None = None,
    cabin_class: str = "economy",
    passengers: int = 1,
    currency: str | None = None,
    flight_number: str | None = None,
    use_playwright: bool = False,  # NEW PARAMETER
) -> str:
    """Enhanced flight search with optional Playwright scraping.
    
    Strategy:
    1) If use_playwright=True, try Playwright-based extraction first
    2) Fall back to existing Firecrawl approach if Playwright fails
    3) Provide helpful links if no live data is found
    """
    origin_code = _city_to_code(origin_city)
    dest_code = _city_to_code(destination_city)
    loc = _get_locality(destination_city)
    target_ccy = (currency or loc["ccy"]).upper()
    
    flights = []
    source_layer = "web_scrape"
    
    # TRY 1: Playwright extraction (if enabled)
    if use_playwright:
        logger.info("Attempting Playwright-based flight extraction")
        try:
            result = await search_flights_with_playwright(
                origin_code=origin_code,
                destination_code=dest_code,
                departure_date=departure_date,
                use_headless=True,
                fallback_to_firecrawl=False,  # Handle errors explicitly
            )
            
            if result["success"]:
                flights = result["flights"]
                logger.info(f"Playwright found {len(flights)} flights")
                source_layer = "playwright"
            else:
                logger.info(f"Playwright failed: {result.get('error')}")
                # Fall through to Firecrawl approach below
        except Exception as e:
            logger.warning(f"Playwright exception: {e}")
            # Fall through to Firecrawl approach below
    
    # TRY 2: Existing Firecrawl approach if Playwright didn't work
    if not flights:
        logger.info("Using Firecrawl-based flight extraction")
        
        fn_q = f" {flight_number}" if flight_number else ""
        targeted_queries = [
            f"site:google.com/travel/flights {origin_code} {dest_code} {departure_date}{fn_q}",
            f"site:skyscanner.com flights {origin_code} {dest_code} {departure_date}",
            f"site:kayak.com flights {origin_code} {dest_code} {departure_date}",
        ]
        if "INR" == target_ccy:
            targeted_queries.append(
                f"site:makemytrip.com flights {origin_city} to {destination_city} {departure_date}"
            )
        
        source_layer = "web_scrape"
        raw = _firecrawl_search(targeted_queries, limit=4)
        flights = (
            _normalize_flights(
                raw,
                fallback_currency=target_ccy,
                default_booking="https://www.google.com/travel/flights",
                origin_city=origin_city,
                destination_city=destination_city,
                origin_code=origin_code,
                destination_code=dest_code,
            )
            if raw and "[search_error:" not in raw
            else []
        )
        
        if flights:
            flights = _sanitize_flight_rows(flights, target_ccy)
        else:
            source_layer = "no_live_data"
            flights = []
    
    trip_type = "round_trip" if return_date else "one_way"
    
    # Format response (same as before)
    payload = {
        "query": {
            "origin_city": origin_city,
            "destination_city": destination_city,
            "origin_iata": origin_code,
            "destination_iata": dest_code,
            "departure_date": departure_date,
            "return_date": return_date,
            "trip_type": trip_type,
            "cabin_class": cabin_class,
            "passengers": passengers,
        },
        "flights": flights,
        "source_layer": source_layer,
        "extraction_method": "playwright" if source_layer == "playwright" else "firecrawl_web_search",
        # ... rest of existing payload ...
    }
    
    return json.dumps(payload, indent=2)


# OPTION 2: Standalone utility function for advanced scenarios
# =============================================================

async def extract_flight_data_with_fallback(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    google_flights_url: str | None = None,
) -> dict:
    """
    Extract flight data with automatic fallback strategy.
    
    Use this when you have a direct Google Flights URL and want
    maximum data extraction capability.
    
    Args:
        origin_code: IATA code (e.g., "DEL")
        destination_code: IATA code (e.g., "SFO")
        departure_date: YYYY-MM-DD format
        google_flights_url: Direct Google Flights URL (optional)
        
    Returns:
        Dictionary with extracted flights and metadata
    """
    from app.agents.tools.flight_scraper import GoogleFlightsScraper
    
    if google_flights_url:
        # Use provided URL directly
        scraper = GoogleFlightsScraper(headless=True)
        try:
            flights = await scraper.search_flights(google_flights_url)
            return {
                "success": True,
                "method": "playwright_direct_url",
                "flights": [asdict(f) for f in flights],
                "count": len(flights),
            }
        except Exception as e:
            logger.warning(f"Direct URL scraping failed: {e}")
            return {
                "success": False,
                "method": "playwright_direct_url",
                "error": str(e),
            }
    else:
        # Fall back to web search approach
        return await search_flights_with_playwright(
            origin_code=origin_code,
            destination_code=destination_code,
            departure_date=departure_date,
            use_headless=True,
            fallback_to_firecrawl=True,
        )


# OPTION 3: Batch processing for multiple routes
# ===============================================

async def search_multiple_flight_routes(
    routes: list[dict],  # [{"origin": "DEL", "destination": "SFO", "date": "2025-04-15"}, ...]
    use_playwright: bool = True,
    max_concurrent: int = 3,
) -> list[dict]:
    """
    Search multiple flight routes concurrently with rate limiting.
    
    Args:
        routes: List of route dictionaries
        use_playwright: Use Playwright (True) or Firecrawl (False)
        max_concurrent: Max concurrent searches
        
    Returns:
        List of search results
    """
    import asyncio
    
    async def search_single(route):
        try:
            if use_playwright:
                return await search_flights_with_playwright(
                    origin_code=route["origin"],
                    destination_code=route["destination"],
                    departure_date=route["date"],
                )
            else:
                # Use existing Firecrawl approach
                # ... call existing function ...
                pass
        except Exception as e:
            logger.error(f"Failed to search {route}: {e}")
            return {"error": str(e), "route": route}
    
    # Use semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def search_with_semaphore(route):
        async with semaphore:
            return await search_single(route)
    
    results = await asyncio.gather(
        *[search_with_semaphore(route) for route in routes],
        return_exceptions=True,
    )
    
    return results


# OPTION 4: Response formatting helpers
# ======================================

def format_search_response(
    result: dict,
    include_metadata: bool = True,
) -> str:
    """Format search result for display or API response."""
    if result.get("success"):
        flights = result.get("flights", [])
        count = result.get("count", 0)
        
        lines = [
            f"✅ Found {count} flights using {result.get('method', 'unknown')} extraction",
            ""
        ]
        
        for flight in flights[:10]:  # Show top 10
            lines.append(
                f"• {flight['airline']} {flight['departure_time']} → {flight['arrival_time']} "
                f"({flight['duration']}) - {flight['price']}"
            )
        
        if include_metadata:
            lines.extend([
                "",
                f"Source: {result.get('source', 'unknown')}",
                f"Total flights: {count}",
            ])
        
        return "\n".join(lines)
    else:
        error = result.get("error", "Unknown error")
        method = result.get("method", "unknown")
        return f"❌ {method} extraction failed: {error}"


# OPTION 5: Configuration and monitoring
# =======================================

class FlightSearchConfig:
    """Configuration for flight search behavior."""
    
    # Extraction preferences
    PREFER_PLAYWRIGHT = False  # Start with Firecrawl, upgrade if needed
    PLAYWRIGHT_HEADLESS = True
    PLAYWRIGHT_TIMEOUT_MS = 30000
    
    # Retry behavior
    MAX_RETRIES = 3
    RETRY_BACKOFF_SECONDS = 5
    
    # Caching
    CACHE_RESULTS = True
    CACHE_TTL_MINUTES = 60
    
    # Logging
    LOG_LEVEL = "info"
    LOG_EXTRACTION_TIME = True
    
    @classmethod
    def get_scraper_config(cls):
        """Get Playwright scraper configuration."""
        from app.agents.tools.flight_scraper import GoogleFlightsScraper
        
        return GoogleFlightsScraper(
            headless=cls.PLAYWRIGHT_HEADLESS,
            timeout_ms=cls.PLAYWRIGHT_TIMEOUT_MS,
        )


# USAGE EXAMPLES
# ==============

"""
1. Simple query (use existing code):
   result = await search_flights(
       origin_city="Pune",
       destination_city="San Francisco",
       departure_date="2025-04-15"
   )

2. With Playwright enabled:
   result = await search_flights_enhanced(
       origin_city="Pune",
       destination_city="San Francisco",
       departure_date="2025-04-15",
       use_playwright=True  # NEW
   )

3. Advanced extraction with direct URL:
   flights = await extract_flight_data_with_fallback(
       origin_code="PNQ",
       destination_code="SFO",
       departure_date="2025-04-15",
       google_flights_url="https://www.google.com/travel/flights/search?..."
   )

4. Batch searching:
   routes = [
       {"origin": "DEL", "destination": "SFO", "date": "2025-04-15"},
       {"origin": "BOM", "destination": "LHR", "date": "2025-04-20"},
       {"origin": "BLR", "destination": "CDG", "date": "2025-05-01"},
   ]
   results = await search_multiple_flight_routes(routes)

5. With formatting:
   result = await search_flights_enhanced(...)
   formatted = format_search_response(json.loads(result))
   print(formatted)
"""
