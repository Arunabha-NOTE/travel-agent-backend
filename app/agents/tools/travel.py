"""Flight search, hotel search, place details, and local transit tools."""

from __future__ import annotations

from langchain_core.tools import tool

from app.core.config import settings

# ---------------------------------------------------------------------------
# IATA lookup helpers
# ---------------------------------------------------------------------------
_CITY_CODES: dict[str, str] = {
    "pune": "PNQ",
    "mumbai": "BOM",
    "delhi": "DEL",
    "new delhi": "DEL",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "kolkata": "CCU",
    "chennai": "MAA",
    "hyderabad": "HYD",
    "ahmedabad": "AMD",
    "goa": "GOI",
    "kochi": "COK",
    "paris": "CDG",
    "london": "LHR",
    "new york": "JFK",
    "dubai": "DXB",
    "abu dhabi": "AUH",
    "doha": "DOH",
    "singapore": "SIN",
    "bangkok": "BKK",
    "tokyo": "NRT",
    "osaka": "KIX",
    "sydney": "SYD",
    "rome": "FCO",
    "milan": "MXP",
    "barcelona": "BCN",
    "madrid": "MAD",
    "amsterdam": "AMS",
    "frankfurt": "FRA",
    "zurich": "ZRH",
    "vienna": "VIE",
    "prague": "PRG",
    "istanbul": "IST",
    "cairo": "CAI",
    "nairobi": "NBO",
    "johannesburg": "JNB",
    "toronto": "YYZ",
    "los angeles": "LAX",
    "san francisco": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "kuala lumpur": "KUL",
    "bali": "DPS",
    "hong kong": "HKG",
    "seoul": "ICN",
    "beijing": "PEK",
    "shanghai": "PVG",
}

_HUB_MAP: dict[str, str] = {
    "india": "Mumbai (BOM), Dubai (DXB), Doha (DOH), Singapore (SIN), Frankfurt (FRA)",
    "pune": "Mumbai (BOM), Dubai (DXB), Doha (DOH), Frankfurt (FRA)",
    "mumbai": "Dubai (DXB), Doha (DOH), Singapore (SIN), Frankfurt (FRA), London (LHR)",
    "delhi": "Dubai (DXB), Doha (DOH), London (LHR), Frankfurt (FRA), Singapore (SIN)",
    "default": "Dubai (DXB), Frankfurt (FRA), Amsterdam (AMS), Doha (DOH), London (LHR)",
}


def _city_to_code(city: str) -> str:
    city_lower = city.lower()
    for k, v in _CITY_CODES.items():
        if k in city_lower:
            return v
    return city.upper()[:3]


def _get_hubs(origin: str) -> str:
    origin_lower = origin.lower()
    for k, v in _HUB_MAP.items():
        if k in origin_lower:
            return v
    return _HUB_MAP["default"]


def _firecrawl_search(queries: list[str], limit: int = 3) -> str:
    """Run one or more queries via Firecrawl v4 and return combined markdown."""
    try:
        from firecrawl.v1 import V1FirecrawlApp  # type: ignore[import]

        app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
        parts: list[str] = []
        for q in queries:
            result = app.search(q, limit=limit)
            for item in (result.data or [])[:limit]:
                content = (
                    getattr(item, "markdown", None)
                    or getattr(item, "description", None)
                    or ""
                )
                if content:
                    parts.append(content[:2000])
        return "\n\n---\n\n".join(parts) if parts else ""
    except Exception as e:
        return f"[search_error: {e}]"


# ---------------------------------------------------------------------------
# Flight search
# ---------------------------------------------------------------------------


@tool
async def search_flights(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    return_date: str | None = None,
    cabin_class: str = "economy",
    passengers: int = 1,
) -> str:
    """Search for available flights between two cities.

    Returns a markdown table of options including direct and connecting flights,
    codeshares, layover details, terminal info, and approximate prices.
    Always call this when discussing flights with the user.

    Args:
        origin_city: Departure city (e.g. "Pune, India")
        destination_city: Destination city (e.g. "Paris, France")
        departure_date: Date in YYYY-MM-DD format
        return_date: Return date for round-trip, None for one-way
        cabin_class: economy | premium_economy | business | first
        passengers: Number of passengers
    """
    origin_code = _city_to_code(origin_city)
    dest_code = _city_to_code(destination_city)
    hubs = _get_hubs(origin_city)
    trip_type = f"return {return_date}" if return_date else "one way"

    queries = [
        (
            f"{cabin_class} class flights {origin_city} to {destination_city} "
            f"{departure_date} {trip_type} {passengers} passenger price stops duration airline"
        ),
        (
            f"cheapest flights {origin_code} to {dest_code} {departure_date} "
            f"connecting via {hubs} codeshare layover terminal transfer time"
        ),
        (
            f"IndiGo Air India Emirates Qatar Lufthansa Air France flights "
            f"{origin_city} to {destination_city} {departure_date} {cabin_class}"
        ),
    ]

    raw = _firecrawl_search(queries, limit=3)

    if not raw or "[search_error:" in raw:
        return (
            f"Live flight search unavailable. Based on knowledge for {origin_city} → {destination_city}:\n\n"
            f"**Typical routes ({cabin_class.title()}):**\n"
            f"| Route | Airlines | Stops | Duration | Approx Price/pax |\n"
            f"|---|---|---|---|---|\n"
            f"| {origin_code} → {dest_code} via {hubs.split(',')[0]} | IndiGo + Emirates | 1 stop | ~11-14h | ₹55,000-₹85,000 |\n"
            f"| {origin_code} → {dest_code} via DOH | IndiGo + Qatar | 1 stop | ~12-15h | ₹60,000-₹90,000 |\n"
            f"| {origin_code} → {dest_code} direct | Air France/Lufthansa | Direct | ~9-11h | ₹80,000-₹1,20,000 |\n\n"
            f"*Note: Verify prices on Google Flights / MakeMyTrip for live fares.*"
        )

    return f"**Flight options for {origin_city} → {destination_city} on {departure_date}:**\n\n{raw}"


# ---------------------------------------------------------------------------
# Airport terminal transit info
# ---------------------------------------------------------------------------


@tool
async def get_airport_transit(
    airport_name: str,
    from_terminal: str,
    to_terminal: str,
) -> str:
    """Get transit time and method between terminals at an airport.

    Use this whenever a passenger has a layover and needs to change terminals
    (e.g. Mumbai BOM T1 domestic to T2 international, CDG Terminal 1 to 2E).

    Args:
        airport_name: Full airport name or city (e.g. "Mumbai", "Charles de Gaulle")
        from_terminal: Departure terminal (e.g. "T1", "Terminal 1", "domestic")
        to_terminal: Arrival terminal (e.g. "T2", "2E", "international")
    """
    queries = [
        (
            f"{airport_name} airport {from_terminal} to {to_terminal} transit time "
            f"bus shuttle walk transfer connection how long"
        ),
    ]
    raw = _firecrawl_search(queries, limit=2)

    if not raw or "[search_error:" in raw:
        # Fallback knowledge base
        fallbacks = {
            "mumbai": "Mumbai BOM: T1 (domestic) to T2 (international) — free shuttle bus, ~30-45 min journey. Allow 2.5h minimum for connection.",
            "delhi": "Delhi DEL: All terminals connected via aerotrain/walkway. T1 to T2/T3 ~20-30 min. T2↔T3 ~10 min via shuttle.",
            "dubai": "Dubai DXB: T1/T2/T3 are separate buildings. T3 to T1 ~30 min bus. Allow 2h for connections.",
            "paris": "Paris CDG: CDGVAL free shuttle connects T1, T2, T3. ~8-15 min between terminals. T2 has sub-terminals (A-G); same building 5-10 min walk.",
            "london": "London LHR: T2/T3 connected via tunnel (~15 min walk). T4/T5 require Heathrow Express (15 min, free for connections).",
            "frankfurt": "Frankfurt FRA: T1 and T2 connected via SkyLine train, 3 min. T1 A/B/C/D/Z all walkable within 10-20 min.",
        }
        for key, info in fallbacks.items():
            if key in airport_name.lower():
                return info
        return f"Terminal transit info for {airport_name}: Allow 30-60 min for terminal changes. Check airport website for shuttle/bus details."

    return f"**Terminal transit at {airport_name} ({from_terminal} → {to_terminal}):**\n\n{raw}"


# ---------------------------------------------------------------------------
# Hotel search
# ---------------------------------------------------------------------------


@tool
async def search_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    guests: int = 2,
    stars: int | None = None,
    brand_preference: str | None = None,
    budget_per_night: str | None = None,
) -> str:
    """Search for hotel options at a destination.

    Returns 3-5 hotel options as a markdown comparison with pricing, ratings,
    loyalty programs, location, and booking tips.

    Args:
        destination: City and area (e.g. "Paris near Eiffel Tower")
        check_in: YYYY-MM-DD
        check_out: YYYY-MM-DD
        guests: Number of guests
        stars: Preferred minimum stars (3, 4, or 5)
        brand_preference: Chain preference (e.g. "Radisson", "Marriott", "IHG")
        budget_per_night: Budget range (e.g. "€100-€150")
    """
    brand_q = f"{brand_preference} " if brand_preference else ""
    stars_q = f"{stars} star " if stars else ""
    budget_q = f"budget {budget_per_night}" if budget_per_night else ""

    queries = [
        (
            f"best {brand_q}{stars_q}hotels in {destination} {check_in} {check_out} "
            f"{guests} guests price per night rating location {budget_q}"
        ),
        (
            f"{destination} hotel loyalty program Marriott Bonvoy Radisson Rewards "
            f"IHG Hilton Honors Hyatt points {stars_q}star price 2024 2025"
        ),
    ]

    raw = _firecrawl_search(queries, limit=3)

    if not raw or "[search_error:" in raw:
        return (
            f"Hotel search unavailable for {destination}. Typical rates:\n\n"
            f"| Category | Approx Price/night | Loyalty Programs |\n"
            f"|---|---|---|\n"
            f"| 3★ Budget | €60-€100 | ibis, Accor Live Limitless |\n"
            f"| 4★ Mid-range | €120-€220 | Radisson Rewards, IHG One, Marriott Bonvoy |\n"
            f"| 5★ Luxury | €280-€600+ | Hilton Honors, World of Hyatt, Four Seasons |\n\n"
            f"*Verify on Booking.com or Hotels.com for live pricing.*"
        )

    return f"**Hotel options in {destination} ({check_in} → {check_out}, {guests} guests):**\n\n{raw}"


# ---------------------------------------------------------------------------
# Place details — tickets, hours, local transit
# ---------------------------------------------------------------------------


@tool
async def get_place_details(
    place_name: str,
    city: str,
    detail_type: str = "all",
) -> str:
    """Get current details for a tourist attraction, transit route, or local info.

    Use this tool for every confirmed attraction to get up-to-date ticket prices,
    opening hours, advance booking requirements, and local transit options.
    Also use it to answer "how do I get from X to Y by metro/bus".

    Args:
        place_name: Attraction, landmark, or route (e.g. "Eiffel Tower",
                    "Louvre Museum", "Metro Line 1 Paris", "Versailles from Paris")
        city: City name (e.g. "Paris", "Rome", "Tokyo")
        detail_type: "tickets" | "transit" | "hours" | "all"
    """
    if detail_type == "tickets":
        q = f"{place_name} {city} ticket price entry fee adult 2024 2025 online booking skip line"
    elif detail_type == "transit":
        q = f"how to get to {place_name} from {city} centre metro bus RER train time cost route"
    elif detail_type == "hours":
        q = f"{place_name} {city} opening hours closing time days closed seasonal schedule"
    else:
        q = (
            f"{place_name} {city} ticket price entry fee opening hours how to get there "
            f"metro bus advance booking 2024 2025"
        )

    raw = _firecrawl_search([q], limit=3)

    if not raw or "[search_error:" in raw:
        return f"Details for {place_name} unavailable online. Use training knowledge for estimates — note prices may be outdated."

    return f"**{place_name} details:**\n\n{raw}"
