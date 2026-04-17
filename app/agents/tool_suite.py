"""Shared agent tool suite used by both LangChain and LangGraph agents."""

from app.agents.rag.retriever import rag_travel_knowledge
from app.agents.tools.geocoding import geocode_place
from app.agents.tools.search import firecrawl_search
from app.agents.tools.time import get_current_time
from app.agents.tools.travel import (
    get_airport_transit,
    get_place_details,
    search_flights,
    search_ground_transport,
    search_hotels,
)
from app.agents.tools.weather import get_weather

# Single source of truth for tool availability across agent runtimes.
AGENT_TOOLS = [
    # Planning-stage tools
    search_flights,
    search_ground_transport,
    get_airport_transit,
    search_hotels,
    get_place_details,
    # General research
    rag_travel_knowledge,
    firecrawl_search,
    # Logistics
    geocode_place,
    get_weather,
    get_current_time,
]
