# SERP AI Flight Search Setup

## Overview
Flight search now uses **SERP AI** for real-time Google Flights data with Firecrawl fallback.

## What Changed
- ❌ Removed: Playwright browser automation (unreliable)
- ❌ Removed: Amadeus API (enterprise-only, complex auth)
- ✅ Added: SERP AI API (easy to use, real Google Flights data)
- ✅ Kept: Firecrawl fallback (web search when SERP fails)

## Setup Steps

### 1. Get SERP AI API Key
1. Visit https://serpapi.com
2. Sign up for free account
3. Copy your API key from dashboard
4. Free tier: 100 requests/month

### 2. Add to `.env`
```bash
SERP_API_KEY=your_api_key_here
```

### 3. Update `pyproject.toml` (already done)
```toml
[project]
dependencies = [
    # ... existing deps ...
    "google-search-results",  # SERP SDK
]
```

### 4. Test the Integration
```bash
python -c "from app.agents.tools.travel import search_flights; print('✅ Flight search ready')"
```

## How It Works

**Flow:**
```
User asks for flights
    ↓
TRY 1: SERP API (Google Flights data)
    ↓
    If fails → TRY 2: Firecrawl fallback (web search)
    ↓
    If fails → TRY 3: Booking links (Google Flights, Skyscanner, etc)
```

**Example Request:**
```python
await search_flights(
    origin_city="Pune, India",
    destination_city="Paris, France",
    departure_date="2026-06-15",
    passengers=1,
    currency="INR"
)
```

**Response includes:**
- Flight prices (₹ / $ / € / £)
- Airlines
- Departure/arrival times
- Number of stops
- Booking links
- Data source (SERP / Firecrawl / fallback)

## SERP AI Pricing
- **Free Tier**: 100 requests/month
- **Paid Tiers**: $5-50/month
- **No credit card required** for free trial

## Troubleshooting

### "SERP API key not configured"
- Add `SERP_API_KEY` to `.env`
- Restart the application

### "SERP API returned no results"
- Firecrawl fallback kicks in automatically
- No user action needed

### "Both SERP and Firecrawl failed"
- Response includes helpful booking links
- User can search manually on Google Flights

## Architecture

**Files Modified:**
- `app/agents/tools/travel.py` - Main implementation
  - `_search_serp_flights()` - SERP API wrapper
  - `search_flights()` - Updated tool

**Key Functions:**
```python
_search_serp_flights()      # Query SERP API for real Google Flights data
_firecrawl_search()         # Fallback web search
_normalize_flights()        # Parse results into standard format
_city_to_code()            # Convert city names to IATA codes
```

## Real-Time Data Guarantee
✅ Uses Google Flights data (same as user sees on google.com/flights)
✅ Returns actual current prices
✅ No invented data - transparency first
✅ Automatic fallback if any method fails

## Next Steps
1. Get free SERP API key
2. Add to `.env`
3. Test with: `python -m pytest tests/test_flight_search.py`
4. Deploy!

---

**Need help?** SERP AI docs: https://serpapi.com/docs/google-flights-api
