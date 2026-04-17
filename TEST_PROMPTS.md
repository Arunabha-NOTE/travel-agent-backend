# Agent Testing Prompts - Manual Verification Suite

## How to Use This Guide
1. Copy a prompt and send it to the chatbot agent
2. Note the tools used and results returned
3. Verify results match expected behavior
4. Mark PASS/FAIL and note any issues found

---

## CATEGORY 1: Flight Search Tests

### Test 1.1: Basic Domestic Flight Search
**Prompt:**
```
I need to book flights from Pune to Delhi. I'm traveling on May 15, 2026 for 5 days. 
What are the available flight options and prices?
```

**Expected Behavior:**
- Tool Used: `search_flights`
- Should return: Flight options with airlines, prices, departure/arrival times
- Verifiable: Check real flight prices for Pune→Delhi on May 15, 2026

**Manual Verification:**
- [ ] Search Google Flights for Pune to Delhi May 15
- [ ] Note 2-3 airlines and approximate price range
- [ ] Compare with agent response prices

---

### Test 1.2: International Flight Search
**Prompt:**
```
I want to travel from Mumbai to Singapore on June 1, 2026. 
Can you find flights in business class with prices in USD?
```

**Expected Behavior:**
- Tool Used: `search_flights`
- Should return: International flights with business class pricing in USD
- Verifiable: Check Google Flights for business class fares

**Manual Verification:**
- [ ] Search Google Flights Mumbai→Singapore June 1, business class
- [ ] Note approximate prices in USD
- [ ] Compare with agent response

---

### Test 1.3: Round-Trip Flight
**Prompt:**
```
I need round-trip flights from Bangalore to Bangkok. 
Outbound: April 20, 2026, Return: April 25, 2026. Show economy fares in INR.
```

**Expected Behavior:**
- Tool Used: `search_flights` with round-trip dates
- Should return: Both outbound and return flights
- Verifiable: Check Bangalore→Bangkok round-trip on those dates

**Manual Verification:**
- [ ] Search Google Flights Bangalore→Bangkok April 20-25 round-trip
- [ ] Note economy prices in INR
- [ ] Verify agent found similar options

---

## CATEGORY 2: Hotel Search Tests

### Test 2.1: Basic Hotel Search
**Prompt:**
```
I'm visiting Paris from May 10-15, 2026. What hotels are available? 
I'd prefer something around 100-150 EUR per night in a central location.
```

**Expected Behavior:**
- Tool Used: `search_hotels`
- Should return: Hotels with prices, ratings, location info
- Verifiable: Check Booking.com or Expedia for Paris hotels

**Manual Verification:**
- [ ] Search Booking.com for Paris hotels May 10-15
- [ ] Filter by 100-150 EUR price range
- [ ] Compare hotel names, prices, and ratings with agent response

---

### Test 2.2: Luxury Hotel Search
**Prompt:**
```
Looking for luxury hotels in Tokyo for April 22-25, 2026. 
Budget: $300+ per night. What are the top options?
```

**Expected Behavior:**
- Tool Used: `search_hotels`
- Should return: High-end hotels with premium pricing
- Verifiable: Check luxury hotel sites or Expedia premium filters

**Manual Verification:**
- [ ] Search Google Hotels Tokyo April 22-25, 4-5 star only
- [ ] Check prices in USD range
- [ ] Compare luxury hotel options

---

## CATEGORY 3: Ground Transport Tests

### Test 3.1: Intercity Bus/Train
**Prompt:**
```
I need to get from Delhi to Agra on April 28, 2026. 
What are the transport options (bus, train, taxi) and their costs in INR?
```

**Expected Behavior:**
- Tool Used: `search_ground_transport`
- Should return: Multiple transport options with pricing
- Verifiable: Check IRCTC for trains, RedBus for buses, Uber for taxi estimates

**Manual Verification:**
- [ ] Check IRCTC for train options Delhi→Agra April 28
- [ ] Check RedBus for bus options
- [ ] Note prices and travel times
- [ ] Compare with agent response

---

### Test 3.2: Airport Transfers
**Prompt:**
```
I'm landing in Bangkok and need to get from the airport to the city center.
What are my options? (metro, bus, taxi, ride-share)
```

**Expected Behavior:**
- Tool Used: `get_airport_transit`
- Should return: Multiple transit options with costs and times
- Verifiable: Check Bangkok airport website, Google Maps

**Manual Verification:**
- [ ] Check Bangkok airport website for transport options
- [ ] Search Google Maps Bangkok airport→city center
- [ ] Note available options and typical costs
- [ ] Compare with agent response

---

## CATEGORY 4: Attraction & Place Details

### Test 4.1: Tourist Attraction Details
**Prompt:**
```
Tell me about visiting the Eiffel Tower in Paris. 
What are the current ticket prices, opening hours, and how do I get there by metro?
```

**Expected Behavior:**
- Tool Used: `get_place_details`
- Should return: Ticket prices, hours, transit directions
- Verifiable: Check Eiffel Tower official website, Google Maps

**Manual Verification:**
- [ ] Visit eiffel-tower-fr.com for ticket prices and hours
- [ ] Use Google Maps for metro directions
- [ ] Compare with agent information

---

### Test 4.2: Museum Information
**Prompt:**
```
I want to visit the Louvre Museum in Paris. Can you get me details about:
- Current ticket prices
- Opening hours and days
- How to get there using public transport from Gare de Lyon station
```

**Expected Behavior:**
- Tool Used: `get_place_details`
- Should return: Ticket info, hours, transit directions
- Verifiable: Check Louvre official website, RATP (Paris transit)

**Manual Verification:**
- [ ] Visit louvre.fr for ticket and hour info
- [ ] Use RATP website for Gare de Lyon→Louvre directions
- [ ] Verify agent information

---

## CATEGORY 5: Weather Tests

### Test 5.1: Destination Weather
**Prompt:**
```
What's the weather forecast for Tokyo for the next 7 days? 
I want to know what to pack for my trip April 20-25, 2026.
```

**Expected Behavior:**
- Tool Used: `get_weather` (with Tokyo coordinates)
- Should return: 7-day forecast with temperatures, conditions
- Verifiable: Check Weather.com or Japan Meteorological Agency

**Manual Verification:**
- [ ] Search "Tokyo weather forecast April 2026" 
- [ ] Check typical April temperatures in Tokyo
- [ ] Verify agent forecast seems reasonable for season

---

### Test 5.2: Multiple City Weather
**Prompt:**
```
I'm planning a European trip: Paris (May 10-12), Rome (May 13-15), Barcelona (May 16-18).
What's the weather forecast for each city? What should I pack?
```

**Expected Behavior:**
- Tool Used: `get_weather` (multiple calls for each city)
- Should return: Weather for all three cities
- Verifiable: Check weather.com for May forecasts

**Manual Verification:**
- [ ] Search May weather for Paris, Rome, Barcelona
- [ ] Note temperature ranges and conditions
- [ ] Compare with agent's weather information

---

## CATEGORY 6: Web Search Tests

### Test 6.1: Travel Information Search
**Prompt:**
```
I'm planning a trip to Japan. Can you search for:
- Best time to visit
- Visa requirements for Indian citizens
- Top attractions
- Budget travel tips
```

**Expected Behavior:**
- Tool Used: `firecrawl_search`
- Should return: Web search results about Japan travel
- Verifiable: Google search same queries

**Manual Verification:**
- [ ] Google "best time to visit Japan"
- [ ] Google "Japan visa requirements for Indians"
- [ ] Compare information quality with agent response

---

### Test 6.2: Destination-Specific Info
**Prompt:**
```
What are the best restaurants in Rome's historic center? 
Search for recent reviews and recommendations.
```

**Expected Behavior:**
- Tool Used: `firecrawl_search`
- Should return: Restaurant information from web
- Verifiable: Google "best restaurants Rome"

**Manual Verification:**
- [ ] Google "best restaurants Rome historic center"
- [ ] Check TripAdvisor or Google Reviews
- [ ] Compare restaurant suggestions

---

## CATEGORY 7: Complex Multi-Tool Tests

### Test 7.1: Complete Itinerary Planning
**Prompt:**
```
Help me plan a 5-day trip:
- Origin: Pune (April 20)
- Destination: Paris (April 20-25)
- Budget: €2000 total (flights, hotel, food, transport)

Please provide:
1. Flight options and prices
2. Hotel recommendations (€100-150/night)
3. Weather forecast
4. Top 3 attractions with details and entry prices
5. Best ways to get from airport to hotel
```

**Expected Behavior:**
- Tool Used: Multiple tools (flights, hotels, weather, place details, airport transit)
- Should return: Comprehensive itinerary
- Verifiable: Manual checks for each component

**Manual Verification:**
- [ ] Verify flight Pune→Paris April 20 prices
- [ ] Check hotel prices in €150 range
- [ ] Confirm April weather in Paris
- [ ] Check Eiffel Tower, Louvre, Notre-Dame prices
- [ ] Verify Paris airport→city transport options

---

### Test 7.2: Road Trip Planning
**Prompt:**
```
Plan a 6-day road trip from Delhi to Jaipur to Agra:
- Dates: May 1-6, 2026
- Travel by car/bus between cities
- Budget: ₹15,000 total

Need:
1. Transport options between cities with costs
2. Hotel recommendations in Jaipur and Agra
3. Weather forecast
4. Top attractions with entrance fees and hours
5. Best restaurants to try
```

**Expected Behavior:**
- Tool Used: Multiple tools (ground transport, hotels, weather, place details, search)
- Should return: Complete road trip plan
- Verifiable: Each component independently

**Manual Verification:**
- [ ] Check RedBus/IRCTC Delhi→Jaipur→Agra costs
- [ ] Verify hotel prices in Jaipur/Agra
- [ ] Check May weather in North India
- [ ] Verify attraction prices (Taj Mahal, City Palace, etc.)
- [ ] Search reviews for recommended restaurants

---

## CATEGORY 8: Error Handling Tests

### Test 8.1: Invalid Date
**Prompt:**
```
Show me flights from New York to London on February 30, 2026.
```

**Expected Behavior:**
- Should catch invalid date and provide error message
- Should NOT crash or return empty results silently

**Verification:**
- [ ] Agent should explain date is invalid
- [ ] Should suggest valid alternative dates

---

### Test 8.2: Impossible Route
**Prompt:**
```
I need a flight from Los Angeles to London that leaves at 10 AM and arrives at 8 AM same day.
Is that possible?
```

**Expected Behavior:**
- Should explain time zone differences
- Should show actual possible flight times
- Should NOT pretend impossible flight exists

**Verification:**
- [ ] Agent acknowledges time zone physics
- [ ] Provides realistic departure/arrival times

---

### Test 8.3: Missing Information Handling
**Prompt:**
```
Can you find me a hotel?
```

**Expected Behavior:**
- Should ask for required information (destination, dates, budget)
- Should NOT guess or provide irrelevant results

**Verification:**
- [ ] Agent asks clarifying questions
- [ ] Continues conversation naturally

---

## TESTING CHECKLIST

### Before Each Test:
- [ ] Backend server is running (`python -m uvicorn app.main:app --reload`)
- [ ] Agent is loaded and ready
- [ ] Note the exact prompt being tested
- [ ] Open manual verification sources (Google Flights, Booking.com, etc.)

### During Each Test:
- [ ] Observe which tools are called
- [ ] Note if tools return data or errors
- [ ] Record any unusual behavior
- [ ] Take screenshots if needed

### After Each Test:
- [ ] Compare agent response with manual verification
- [ ] Record PASS or FAIL
- [ ] Note any discrepancies
- [ ] Record exact error messages if FAIL

### Issue Reporting Format:
```
TEST: [Test Number and Name]
RESULT: FAIL
TOOLS USED: [tool1, tool2]
EXPECTED: [What should happen]
ACTUAL: [What actually happened]
ERROR MESSAGE: [Exact error if applicable]
MANUAL VERIFICATION: [What you found manually]
ISSUE: [Description of problem]
```

---

## Quick Reference: Tool Status

| Tool | Status | Notes |
|------|--------|-------|
| search_flights | ✅ FIXED | Firecrawl response handling corrected |
| search_hotels | ⚠️ ASYNC | Needs async invocation testing |
| search_ground_transport | ⚠️ ASYNC | Needs async invocation testing |
| get_airport_transit | ⚠️ ASYNC | Needs async invocation testing |
| get_place_details | ⚠️ ASYNC | Parameter: place_name, city |
| get_weather | ⚠️ ASYNC | Parameter: lat, lon (needs geocoding) |
| geocode_place | ⚠️ ASYNC | Parameter: place_name |
| firecrawl_search | ⚠️ ASYNC | Needs async invocation testing |
| rag_travel_knowledge | ⚠️ ASYNC | Vector DB search, needs async |
| get_current_time | ✅ READY | Always works |

---

## Next Steps After Testing:
1. Document all PASS/FAIL results
2. Identify patterns in failures
3. Fix tool parameter mismatches
4. Implement async invocation fixes
5. Re-test complete suite
6. Deploy fixes to main branch

