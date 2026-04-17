"""
Google Flights URL Reference - How to get and use URLs for the scraper

The key to using the Playwright flight scraper is getting a proper Google Flights URL.
This guide shows how to construct, obtain, and test URLs.
"""

# ==============================================================================
# GETTING GOOGLE FLIGHTS URLS - 3 METHODS
# ==============================================================================

# METHOD 1: Manual - Copy from browser address bar
# =================================================
# Steps:
# 1. Go to https://www.google.com/travel/flights
# 2. Enter search parameters:
#    - From: [Airport] (e.g., "Pune" or "DEL")
#    - To: [Airport] (e.g., "San Francisco" or "SFO")
#    - Departure: Select date
#    - Cabin class: Select if needed
# 3. Click "Search"
# 4. Copy the URL from address bar
#
# Example URL structure:
# https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD
#
# Key parameters:
# - tfs: Base64-encoded search parameters (departure, arrival, date, cabin class)
# - curr: Currency code (USD, EUR, INR, etc.)
# - hl: Language code (en, fr, de, etc.)
# - gl: Country code (us, gb, in, etc.)


# METHOD 2: URL Builder - Construct programmatically
# ====================================================

def build_google_flights_url(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: str | None = None,
    cabin_class: str = "economy",
    currency: str = "USD",
    country_code: str = "US",
    language_code: str = "en",
) -> str:
    """
    Build a Google Flights search URL from parameters.
    
    IMPORTANT: This creates a basic URL. For complex searches, it's better
    to manually create one URL and modify the parameters.
    
    Args:
        origin_code: 3-letter IATA code (DEL, BOM, SFO, etc.)
        destination_code: 3-letter IATA code
        departure_date: YYYY-MM-DD format
        return_date: For round-trip, YYYY-MM-DD format (optional)
        cabin_class: economy, premium_economy, business, first
        currency: Currency code (USD, EUR, INR, GBP, etc.)
        country_code: 2-letter country code (US, GB, IN, FR, etc.)
        language_code: 2-letter language code (en, fr, de, es, etc.)
        
    Returns:
        Google Flights search URL
        
    Example:
        url = build_google_flights_url(
            origin_code="DEL",
            destination_code="SFO",
            departure_date="2025-04-15",
            currency="USD",
            country_code="US",
            language_code="en"
        )
    """
    # Note: The 'tfs' parameter uses a complex encoding that's hard to
    # construct manually. This function builds a simpler URL that Google
    # may redirect to the proper format.
    
    base_url = "https://www.google.com/travel/flights/search"
    
    # Build query string
    params = [
        f"qs={origin_code}+to+{destination_code}+{departure_date}",
    ]
    
    if return_date:
        params.append(f"dates={departure_date},{return_date}")
    
    params.append(f"curr={currency}")
    params.append(f"gl={country_code}")
    params.append(f"hl={language_code}")
    
    # Cabin class mapping
    cabin_class_map = {
        "economy": "0",
        "premium_economy": "1", 
        "business": "2",
        "first": "3",
    }
    
    if cabin_class in cabin_class_map:
        params.append(f"mc={cabin_class_map[cabin_class]}")
    
    query_string = "&".join(params)
    return f"{base_url}?{query_string}"


# METHOD 3: Template - Use pre-built template URLs
# ==================================================

# Store a master URL with all parameters, then modify just what you need

GOOGLE_FLIGHTS_TEMPLATE = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD&gl=US&hl=en"

# Replace parameters in template:
def url_with_dates(template: str, departure_date: str, return_date: str | None = None) -> str:
    """Replace dates in a template URL."""
    # This is tricky because dates are encoded in 'tfs' parameter
    # Easier approach: Use METHOD 1 (manual copy)
    import re
    
    # Try to replace date in tfs (limited success)
    # Better: Just build new URL with build_google_flights_url()
    pass


# ==============================================================================
# COMMON GOOGLE FLIGHTS URLS FOR TESTING
# ==============================================================================

# India to USA (DEL -> SFO)
URL_DELHI_TO_SANFRANCISCO = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD"

# India to UK (BOM -> LHR)
URL_MUMBAI_TO_LONDON = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTA4agcIARIDQk9NcgcIARIDTEhSQAFIAXABggELCP___________wGYAQI&curr=GBP"

# India to Europe (BLR -> CDG)
URL_BANGALORE_TO_PARIS = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA1LTAxagcIARIDQkxScgcIARIDQ0RHQAFIAXABggELCP___________wGYAQI&curr=EUR"

# US to Europe (JFK -> FCO)
URL_NEWYORK_TO_ROME = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTE1agcIARIDSktGcgcIARIDRkNPQAFIAXABggELCP___________wGYAQI&curr=USD"


# ==============================================================================
# AIRPORT CODES REFERENCE
# ==============================================================================

MAJOR_AIRPORTS = {
    # India
    "DEL": "Delhi Indira Gandhi (Delhi)",
    "BOM": "Mumbai Bombay (Mumbai)",
    "BLR": "Bangalore Kempegowda (Bangalore)",
    "HYD": "Hyderabad Rajiv Gandhi (Hyderabad)",
    "CCU": "Kolkata Netaji Subhas Chandra (Kolkata)",
    "MAA": "Chennai International (Chennai)",
    "COK": "Kochi International (Kochi)",
    "PNQ": "Pune Lohegaon (Pune)",
    "AMD": "Ahmedabad Sardar Vallabhbhai Patel (Ahmedabad)",
    "GOI": "Goa Dabolim (Goa)",
    
    # USA
    "JFK": "New York John F. Kennedy (New York)",
    "LAX": "Los Angeles International (Los Angeles)",
    "SFO": "San Francisco International (San Francisco)",
    "ORD": "Chicago O'Hare (Chicago)",
    "DFW": "Dallas Fort Worth (Dallas)",
    "MIA": "Miami International (Miami)",
    "ATL": "Atlanta Hartsfield-Jackson (Atlanta)",
    "SEA": "Seattle Tacoma (Seattle)",
    "DEN": "Denver International (Denver)",
    "LAS": "Las Vegas McCarran (Las Vegas)",
    
    # Europe
    "LHR": "London Heathrow (London)",
    "CDG": "Paris Charles de Gaulle (Paris)",
    "FCO": "Rome Fiumicino (Rome)",
    "MXP": "Milan Malpensa (Milan)",
    "BCN": "Barcelona El Prat (Barcelona)",
    "MAD": "Madrid Adolfo Suárez (Madrid)",
    "AMS": "Amsterdam Schiphol (Amsterdam)",
    "FRA": "Frankfurt Main (Frankfurt)",
    "ZRH": "Zurich (Zurich)",
    "VIE": "Vienna International (Vienna)",
    
    # Middle East
    "DXB": "Dubai International (Dubai)",
    "AUH": "Abu Dhabi International (Abu Dhabi)",
    "DOH": "Doha Hamad (Doha)",
    "JED": "Jeddah King Abdulaziz (Jeddah)",
    
    # Asia
    "SIN": "Singapore Changi (Singapore)",
    "BKK": "Bangkok Suvarnabhumi (Bangkok)",
    "HKG": "Hong Kong International (Hong Kong)",
    "KUL": "Kuala Lumpur International (Kuala Lumpur)",
    "NRT": "Tokyo Narita (Tokyo)",
    "KIX": "Osaka Kansai (Osaka)",
    "ICN": "Seoul Incheon (Seoul)",
    "PEK": "Beijing Capital (Beijing)",
    "PVG": "Shanghai Pudong (Shanghai)",
    "DPS": "Bali Denpasar (Bali)",
    
    # Australia/Pacific
    "SYD": "Sydney Kingsford Smith (Sydney)",
    "MEL": "Melbourne Tullamarine (Melbourne)",
    "AKL": "Auckland International (Auckland)",
}

# ==============================================================================
# USING URLS WITH THE SCRAPER
# ==============================================================================

async def search_using_url(url: str):
    """Example: Use a Google Flights URL with the scraper."""
    from app.agents.tools.flight_scraper import GoogleFlightsScraper
    
    scraper = GoogleFlightsScraper(headless=True)  # False for debugging
    
    try:
        flights = await scraper.search_flights(url)
        
        print(f"✅ Found {len(flights)} flights")
        for flight in flights[:5]:
            print(f"  • {flight.airline}: {flight.departure_time} → {flight.arrival_time}")
            print(f"    Duration: {flight.duration}, Stops: {flight.stops}")
            print(f"    Price: {flight.price}")
            print()
            
        return flights
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


# ==============================================================================
# URL PARAMETER GUIDE
# ==============================================================================

"""
Google Flights URLs have several components:

1. BASE: https://www.google.com/travel/flights/search

2. MAIN PARAMETERS:
   ?tfs=<encoded_search_params>  - The main search parameters (base64-like encoding)
   &curr=<currency>               - Currency (USD, EUR, INR, GBP, etc.)
   
3. OPTIONAL PARAMETERS:
   &gl=<country>                  - Country code for localization (us, gb, in, fr, etc.)
   &hl=<language>                 - Language code (en, fr, de, es, etc.)
   &mc=<cabin_class>              - Cabin class (0=economy, 1=premium, 2=business, 3=first)

EXAMPLE BREAKDOWN:
https://www.google.com/travel/flights/search?
  tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI
  &curr=USD
  &gl=US
  &hl=en

The 'tfs' parameter is complex:
  - Starts with base64 encoding
  - Contains: departure date, origin airport, destination airport, cabin class
  - Not easily reversible (best to copy from Google Flights directly)

HOW TO GET A VALID TFS PARAMETER:
1. Go to https://www.google.com/travel/flights
2. Search for your route
3. Copy the URL from address bar
4. The entire 'tfs=...' value is what you need
5. Can reuse same URL for multiple scraping runs
"""


# ==============================================================================
# TESTING URLS
# ==============================================================================

def test_url_with_scraper(url: str, headless: bool = True):
    """Test a URL to see if it returns valid flights."""
    import asyncio
    
    async def _test():
        from app.agents.tools.flight_scraper import GoogleFlightsScraper
        
        print(f"Testing URL: {url[:80]}...")
        print(f"Headless mode: {headless}")
        print()
        
        scraper = GoogleFlightsScraper(headless=headless)
        
        try:
            flights = await scraper.search_flights(url)
            print(f"✅ SUCCESS: Found {len(flights)} flights\n")
            
            for i, flight in enumerate(flights[:3], 1):
                print(f"{i}. {flight.airline}")
                print(f"   Departure: {flight.departure_time}")
                print(f"   Arrival: {flight.arrival_time}")
                print(f"   Duration: {flight.duration}")
                print(f"   Stops: {flight.stops}")
                print(f"   Price: {flight.price}")
                print()
            
            return True
            
        except Exception as e:
            print(f"❌ FAILED: {e}")
            print(f"\nTroubleshooting:")
            print(f"1. Check URL is valid")
            print(f"2. Try with headless=False to watch browser")
            print(f"3. Check selectors haven't changed in Google Flights UI")
            print(f"4. Verify Playwright is installed: pip install playwright")
            return False
    
    asyncio.run(_test())


# ==============================================================================
# QUICK START
# ==============================================================================

"""
1. Get a Google Flights URL:
   - Go to https://www.google.com/travel/flights
   - Search for flights
   - Copy URL from address bar
   
2. Use with scraper:
   
   import asyncio
   from app.agents.tools.flight_scraper import GoogleFlightsScraper
   
   url = "https://www.google.com/travel/flights/search?tfs=..."
   
   async def search():
       scraper = GoogleFlightsScraper()
       flights = await scraper.search_flights(url)
       for f in flights:
           print(f"{f.airline} {f.departure_time} {f.price}")
   
   asyncio.run(search())

3. For debugging:
   - Set headless=False to watch the browser
   - Check console output for selector errors
   - Take screenshot if errors occur
"""
