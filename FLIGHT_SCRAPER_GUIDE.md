# Enhanced Flight Search Tool - Integration Guide

## Overview

This guide explains how to use the new Google Flights scraper based on the [luminati-io/google-flights-api](https://github.com/luminati-io/google-flights-api) example. The implementation provides two complementary approaches:

1. **Playwright-based Scraper** (`flight_scraper.py`) - Direct browser automation for real-time data
2. **Firecrawl Integration** (`flight_integration.py`) - Fallback web search and extraction

## Architecture

### Components

```
travel.py (main tool)
├── search_flights() [existing]
│   └── Uses Firecrawl for web search
│
flight_scraper.py (NEW)
├── GoogleFlightsScraper class
│   ├── search_flights() - Main async entry point
│   ├── _extract_flight_data() - CSS selector-based extraction
│   ├── _load_all_flights() - Pagination handling
│   └── _extract_text() - Safe text extraction
│
flight_integration.py (NEW)
├── search_flights_with_playwright() - Unified API
├── _build_google_flights_url() - URL construction
└── format_flight_results() - Human-readable output
```

## Key Improvements from GitHub Example

### 1. **Reliable CSS Selectors**
Based on tested selectors from luminati-io/google-flights-api:

```python
SELECTORS = {
    "airline": "div.sSHqwe.tPgKwe.ogfYpf",
    "departure_time": 'span[aria-label^="Departure time"]',
    "arrival_time": 'span[aria-label^="Arrival time"]',
    "duration": 'div[aria-label^="Total duration"]',
    "stops": "div.hF6lYb span.rGRiKd",
    "price": "div.FpEdX span",
    "co2_emissions": "div.O7CXue",
    "emissions_variation": "div.N6PNV",
}
```

### 2. **Structured Data with Dataclass**
```python
@dataclass
class FlightData:
    airline: str
    departure_time: str
    arrival_time: str
    duration: str
    stops: str
    price: str
    co2_emissions: str | None = None
    emissions_variation: str | None = None
    booking_url: str | None = None
```

### 3. **Retry Logic with Tenacity**
Automatic retry with exponential backoff:
```python
@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
async def search_flights(self, url: str) -> list[FlightData]:
```

### 4. **Smart Pagination**
Automatically loads all flights by clicking "Show more" button:
```python
async def _load_all_flights(self, page) -> None:
    """Click 'Show more flights' button until all flights are loaded"""
```

### 5. **Proper User-Agent Spoofing**
```python
user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
```

## Usage Examples

### Example 1: Basic Flight Search with Playwright

```python
import asyncio
from app.agents.tools.flight_scraper import GoogleFlightsScraper

async def search():
    scraper = GoogleFlightsScraper(headless=True)  # Set to False for development
    
    # Use a real Google Flights URL from the browser
    url = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD"
    
    try:
        flights = await scraper.search_flights(url)
        for flight in flights:
            print(f"{flight.airline}: {flight.departure_time} → {flight.arrival_time} ({flight.price})")
    except Exception as e:
        print(f"Search failed: {e}")

asyncio.run(search())
```

### Example 2: Using Integration API with Fallback

```python
from app.agents.tools.flight_integration import (
    search_flights_with_playwright,
    format_flight_results
)

# Search flights from DEL to SFO
result = await search_flights_with_playwright(
    origin_code="DEL",
    destination_code="SFO",
    departure_date="2025-04-15",
    use_headless=True,
    fallback_to_firecrawl=True
)

if result["success"]:
    flights = result["flights"]
    formatted = format_flight_results(
        flights, 
        origin_city="Delhi",
        destination_city="San Francisco",
        currency="USD"
    )
    print(formatted)
else:
    print("Scraping failed, but you can search manually:")
    print(result["recommended_url"])
```

### Example 3: Integration with Existing Tool

```python
# In travel.py, enhance the existing search_flights() function

from app.agents.tools.flight_integration import extract_flights_async

@tool
async def search_flights(...):
    # Try Playwright first for real-time data
    if use_playwright:
        result = await extract_flights_async(
            origin_code=origin_code,
            destination_code=dest_code,
            departure_date=departure_date,
            origin_city=origin_city,
            destination_city=destination_city,
        )
        if result["success"]:
            flights = result["flights"]
            # Process and return flights
    
    # Fall back to existing Firecrawl approach if needed
    # ... existing code ...
```

## Setup and Installation

### 1. Install Playwright

```bash
pip install playwright
playwright install chromium
```

### 2. Add Playwright to Your Dependencies

In `pyproject.toml`:
```toml
[project]
dependencies = [
    ...
    "playwright>=1.40.0",
    "tenacity>=8.2.3",
    ...
]
```

### 3. Environment Variables (Optional)

For advanced configurations:
```bash
# Use system proxy (if behind corporate proxy)
PLAYWRIGHT_PROXY=http://proxy.company.com:8080

# Debug logs
PLAYWRIGHT_DEBUG=1
```

## Performance Tips

### Headless vs Non-Headless
```python
# Production: faster, more stealthy
scraper = GoogleFlightsScraper(headless=True)

# Development/Debugging: see the browser, avoid detection
scraper = GoogleFlightsScraper(headless=False)
```

### Timeout Configuration
```python
# Default: 30 seconds
scraper = GoogleFlightsScraper(timeout_ms=30000)

# Slower networks
scraper = GoogleFlightsScraper(timeout_ms=60000)
```

### Batch Searches
```python
async def batch_search(routes: list[tuple[str, str, str]]):
    scraper = GoogleFlightsScraper()
    tasks = []
    
    for origin, destination, date in routes:
        url = _build_google_flights_url(origin, destination, date)
        tasks.append(scraper.search_flights(url))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

## Common Issues and Solutions

### Issue 1: Playwright Browser Not Found
```
Error: Executable doesn't exist at ~/.cache/ms-playwright/chromium-...
```

**Solution:**
```bash
playwright install chromium
```

### Issue 2: Timeout During Page Load
```
Error: Timeout 30000ms exceeded during navigationId
```

**Solution:**
```python
scraper = GoogleFlightsScraper(timeout_ms=60000)
```

### Issue 3: Element Not Found

**Debug Steps:**
1. Set `headless=False` to watch the browser
2. Check Google Flights UI hasn't changed
3. Update CSS selectors in `SELECTORS` dict
4. Add logging: `logger.debug(f"Looking for {selector}")`

### Issue 4: Detection/Blocking

**Solutions:**
```python
# 1. Use non-headless mode
scraper = GoogleFlightsScraper(headless=False)

# 2. Add random delays between requests
await page.wait_for_timeout(random.randint(1000, 3000))

# 3. Rotate user agents
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
]
```

## Data Structure

### Input: Google Flights URL

The URL should be copied directly from Google Flights interface:
```
https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD
```

### Output: FlightData

```python
FlightData(
    airline="Air India",
    departure_time="2:40 PM",
    arrival_time="4:55 AM +1",
    duration="15 hr 15 min",
    stops="1 stop in DXB",
    price="$875",
    co2_emissions="1,092 kg CO2e",
    emissions_variation="+6% emissions"
)
```

### JSON Output

```json
{
  "search_url": "https://www.google.com/travel/flights/search?...",
  "trip_info": {
    "origin": "DEL",
    "destination": "SFO",
    "date": "2025-04-15"
  },
  "flights": [
    {
      "airline": "Air India",
      "departure_time": "2:40 PM",
      "arrival_time": "4:55 AM +1",
      "duration": "15 hr 15 min",
      "stops": "1 stop in DXB",
      "price": "$875",
      "co2_emissions": "1,092 kg CO2e",
      "emissions_variation": "+6% emissions",
      "booking_url": null
    }
  ],
  "total_flights": 1
}
```

## Comparison: Playwright vs Firecrawl

| Feature | Playwright | Firecrawl | Best For |
|---------|-----------|----------|----------|
| Real-time extraction | ✅ Yes | ⚠️ Partial | Live data |
| Reliability | ✅ High | ✅ High | Production |
| Speed | ⚠️ Slower (10-30s) | ✅ Faster (2-5s) | Quick lookups |
| Browser automation | ✅ Full | ❌ None | Complex sites |
| Pagination | ✅ Auto | ⚠️ Manual | All flights |
| Anti-detection | ⚠️ Varies | ✅ Built-in proxies | Blocked sites |
| Cost | ✅ Free | 💰 Pay-per-request | Budget-limited |
| Setup | ⚠️ Complex | ✅ Simple | Quick start |

## Best Practices

### 1. Always Use Async/Await
```python
# ✅ Good
flights = await scraper.search_flights(url)

# ❌ Wrong - blocks event loop
flights = asyncio.run(scraper.search_flights(url))
```

### 2. Implement Error Handling
```python
try:
    flights = await scraper.search_flights(url)
except Exception as e:
    logger.error(f"Scraping failed: {e}")
    # Fallback to Firecrawl or manual links
```

### 3. Cache Results
```python
# Avoid re-scraping same search
cache = {}
cache_key = f"{origin}_{destination}_{date}"

if cache_key not in cache:
    cache[cache_key] = await scraper.search_flights(url)

flights = cache[cache_key]
```

### 4. Monitor Performance
```python
import time

start = time.time()
flights = await scraper.search_flights(url)
duration = time.time() - start

logger.info(f"Scraping completed in {duration:.2f}s, found {len(flights)} flights")
```

## Future Enhancements

1. **URL Parameter Mapping** - Automatically build `tfs` parameter from city codes
2. **Multi-currency Support** - Extract prices in different currencies
3. **Airline Filtering** - Filter results by specific airlines
4. **Price Alerts** - Store baseline prices and detect decreases
5. **Proxy Rotation** - Use Bright Data or similar for large-scale scraping
6. **ML-based Parsing** - Use computer vision for complex layouts

## References

- [GitHub: luminati-io/google-flights-api](https://github.com/luminati-io/google-flights-api)
- [Playwright Documentation](https://playwright.dev/python/)
- [Tenacity Retry Library](https://tenacity.readthedocs.io/)
- [Google Flights Search URL Structure](https://github.com/luminati-io/google-flights-api/blob/main/README.md)

## Testing

Run the included test/example:

```bash
# Test the scraper directly
cd chatbot-backend
python -m app.agents.tools.flight_scraper

# Test with integration layer
python -c "
import asyncio
from app.agents.tools.flight_integration import search_flights_with_playwright

result = asyncio.run(search_flights_with_playwright(
    origin_code='DEL',
    destination_code='SFO',
    departure_date='2025-04-15'
))
print(result)
"
```
