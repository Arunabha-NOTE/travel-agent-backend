"""Shared agent tool suite used by both LangChain and LangGraph agents."""

from app.agents.tools.geocoding import geocode_place
from app.agents.tools.search import search_web, scrape_website
from app.agents.tools.time import get_current_time
from app.agents.tools.itinerary import update_itinerary_panel
from app.agents.tools.travel import (
    get_airport_transit,
    get_place_details,
    search_flights,
    search_ground_transport,
    search_hotels,
)
from app.agents.tools.weather import get_weather
from app.agents.rag.retriever import rag_travel_knowledge

# Single source of truth for tool availability across agent runtimes.
AGENT_TOOLS = [
    # Planning-stage tools
    search_flights,
    search_ground_transport,
    get_airport_transit,
    search_hotels,
    get_place_details,
    update_itinerary_panel,
    # General research
    rag_travel_knowledge,
    search_web,
    scrape_website,
    # Logistics
    geocode_place,
    get_weather,
    get_current_time,
]
