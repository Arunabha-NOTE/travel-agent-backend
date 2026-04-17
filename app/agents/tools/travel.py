"""Flight search, hotel search, place details, and local transit tools."""

from __future__ import annotations

import json
import re

from langchain_core.tools import tool

from app.agents.tools.utils import get_kb_fallback, persist_tool_result
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

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


def _get_locality(location: str) -> dict[str, str]:
    """Return currency and regional site preferences based on location."""
    loc = location.lower()
    if any(c in loc for c in _CITY_CODES.keys()) or "india" in loc:
        return {"ccy": "INR", "sym": "₹", "site": "MakeMyTrip IndiGo"}
    if any(e in loc for e in ["uk", "london", "gbp"]):
        return {"ccy": "GBP", "sym": "£", "site": "Skyscanner Trainline"}
    if any(e in loc for e in ["europe", "paris", "rome", "berlin", "spain", "italy"]):
        return {"ccy": "EUR", "sym": "€", "site": "Omio Skyscanner"}
    return {"ccy": "USD", "sym": "$", "site": "Expedia TripAdvisor"}


def _firecrawl_search(queries: list[str], limit: int = 3) -> str:
    """Run one or more queries via Firecrawl v4 and return combined markdown."""
    logger.info(
        "Travel tool search starting",
        query_count=len(queries),
        limit=limit,
        queries=queries[:3],
    )
    try:
        from firecrawl.v1 import V1FirecrawlApp  # type: ignore[import]
        from firecrawl.v1.client import V1ScrapeOptions  # type: ignore[import]

        app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
        parts: list[str] = []
        for q in queries:
            result = app.search(
                q, scrape_options=V1ScrapeOptions(formats=["markdown"]), limit=limit
            )
            # Result data can be a list of objects or dicts
            if isinstance(result, dict):
                data_list = result.get("data", [])
            else:
                data_list = getattr(result, "data", []) or []
            logger.info(
                "Travel tool search query completed",
                query=q,
                result_count=len(data_list),
            )

            for item in data_list[:limit]:
                # Handle both object attributes and dict keys
                if isinstance(item, dict):
                    content = (
                        item.get("markdown")
                        or item.get("description")
                        or item.get("title")
                        or ""
                    )
                else:
                    content = (
                        getattr(item, "markdown", None)
                        or getattr(item, "description", None)
                        or getattr(item, "title", None)
                        or ""
                    )

                if content:
                    parts.append(content[:2000])
        combined = "\n\n---\n\n".join(parts) if parts else ""
        logger.info(
            "Travel tool search finished",
            snippet_count=len(parts),
            has_content=bool(combined),
        )
        return combined
    except Exception as e:
        logger.warning(
            "Travel tool search failed",
            error=str(e),
            query_count=len(queries),
            queries=queries[:3],
        )
        return f"[search_error: {e}]"


def _log_tool_outcome(
    tool_name: str,
    *,
    source_layer: str | None = None,
    result_count: int | None = None,
    fallback_reason: str | None = None,
    **context: object,
) -> None:
    payload: dict[str, object] = {"tool": tool_name, **context}
    if source_layer is not None:
        payload["source_layer"] = source_layer
    if result_count is not None:
        payload["result_count"] = result_count
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason

    level = (
        logger.warning
        if source_layer
        in {"no_live_data", "vector_kb", "model_prior", "route_fallback"}
        else logger.info
    )
    level("Travel tool completed", **payload)


_AIRLINE_HINTS = [
    "IndiGo",
    "Air India",
    "Vistara",
    "Akasa",
    "Emirates",
    "Qatar",
    "Etihad",
    "Lufthansa",
    "British Airways",
    "Air France",
    "Singapore Airlines",
    "KLM",
    "Turkish Airlines",
]


def _pick_airline(text: str) -> str:
    for airline in _AIRLINE_HINTS:
        if airline.lower() in text.lower():
            return airline
    return "Unknown"


def _wants_live_data(query_text: str | None) -> bool:
    """Detect if user explicitly asks for latest/current/real-time data."""
    if not query_text:
        return False
    q_lower = query_text.lower()
    live_keywords = [
        "latest",
        "current",
        "now",
        "real-time",
        "real time",
        "right now",
        "today",
        "this minute",
        "just now",
        "up to date",
        "updated",
    ]
    return any(keyword in q_lower for keyword in live_keywords)


def _extract_price(text: str, fallback_currency: str) -> tuple[float | None, str]:
    patterns = [
        r"(INR|USD|EUR|GBP)\s*([0-9][0-9,]{2,})",
        r"([₹$€£])\s*([0-9][0-9,]{2,})",
    ]
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if not match:
            continue
        token = (match.group(1) or "").upper().strip()
        raw_num = (match.group(2) or "").replace(",", "")
        try:
            value = float(raw_num)
        except ValueError:
            continue
        if token == "₹":
            return value, "INR"
        if token == "$":
            return value, "USD"
        if token == "€":
            return value, "EUR"
        if token == "£":
            return value, "GBP"
        return value, token
    return None, fallback_currency


_FX_TO_INR: dict[str, float] = {
    "INR": 1.0,
    "USD": 83.0,
    "EUR": 90.0,
    "GBP": 105.0,
}


def _convert_currency(amount: float | None, from_ccy: str, to_ccy: str) -> float | None:
    if amount is None:
        return None
    src = from_ccy.upper()
    dst = to_ccy.upper()
    if src == dst:
        return round(amount, 2)
    if src not in _FX_TO_INR or dst not in _FX_TO_INR:
        return round(amount, 2)
    in_inr = amount * _FX_TO_INR[src]
    converted = in_inr / _FX_TO_INR[dst]
    return round(converted, 2)


def _chunk_mentions_route(
    chunk: str,
    *,
    origin_city: str,
    destination_city: str,
    origin_code: str,
    destination_code: str,
) -> bool:
    c = chunk.lower()
    route_tokens = [
        origin_code.lower(),
        destination_code.lower(),
        origin_city.split(",")[0].strip().lower(),
        destination_city.split(",")[0].strip().lower(),
    ]
    hit_count = sum(1 for token in route_tokens if token and token in c)
    return hit_count >= 2


def _parse_budget_range(
    budget_per_night: str | None,
) -> tuple[float | None, float | None]:
    if not budget_per_night:
        return None, None
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", budget_per_night)
    if not match:
        return None, None
    try:
        low = float(match.group(1))
        high = float(match.group(2))
        return (min(low, high), max(low, high))
    except ValueError:
        return None, None


def _extract_times(text: str) -> tuple[str | None, str | None]:
    times = re.findall(
        r"\b([0-2]?\d[:.]\d{2}\s?(?:AM|PM)?)\b", text, flags=re.IGNORECASE
    )
    if len(times) >= 2:
        return times[0].replace(".", ":"), times[1].replace(".", ":")
    if len(times) == 1:
        return times[0].replace(".", ":"), None
    return None, None


def _extract_duration(text: str) -> str | None:
    match = re.search(
        r"\b(\d{1,2}\s*h(?:\s*\d{1,2}\s*m)?)\b", text, flags=re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def _extract_stops(text: str) -> int | None:
    lower = text.lower()
    if "nonstop" in lower or "non-stop" in lower or "direct" in lower:
        return 0
    match = re.search(r"\b(\d)\s*stop", lower)
    if match:
        return int(match.group(1))
    return None


def _extract_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(").,]}") if match else ""


def _normalize_flights(
    raw: str,
    *,
    fallback_currency: str,
    default_booking: str,
    origin_city: str,
    destination_city: str,
    origin_code: str,
    destination_code: str,
) -> list[dict[str, object]]:
    """Normalize raw snippet text into a stable flight schema."""
    chunks = [c.strip() for c in raw.split("---") if c.strip()]
    flights: list[dict[str, object]] = []

    for chunk in chunks:
        if not _chunk_mentions_route(
            chunk,
            origin_city=origin_city,
            destination_city=destination_city,
            origin_code=origin_code,
            destination_code=destination_code,
        ):
            # Ignore likely irrelevant snippets from unrelated routes.
            continue

        airline = _pick_airline(chunk)
        price, ccy = _extract_price(chunk, fallback_currency)
        normalized_price = _convert_currency(price, ccy, fallback_currency)
        dep_time, arr_time = _extract_times(chunk)
        duration = _extract_duration(chunk)
        stops = _extract_stops(chunk)
        booking_link = _extract_url(chunk) or default_booking

        confidence = 0.45
        confidence += 0.2 if airline != "Unknown" else 0.0
        confidence += 0.2 if price is not None else 0.0
        confidence += 0.1 if duration else 0.0
        confidence += 0.05 if dep_time else 0.0
        confidence += 0.05 if stops is not None else 0.0

        flights.append(
            {
                "airline": airline,
                "price": normalized_price,
                "currency": fallback_currency,
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration,
                "stops": stops,
                "booking_link": booking_link,
                "confidence": round(min(confidence, 0.95), 2),
            }
        )

    # Deduplicate similar rows
    seen: set[tuple] = set()
    unique: list[dict[str, object]] = []
    for item in flights:
        key = (
            item.get("airline"),
            item.get("departure_time"),
            item.get("arrival_time"),
            item.get("price"),
            item.get("currency"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(
        key=lambda x: (
            x.get("price") is None,
            x.get("price")
            if isinstance(x.get("price"), (int, float))
            else float("inf"),
            -(
                x.get("confidence")
                if isinstance(x.get("confidence"), (int, float))
                else 0.0
            ),
        )
    )
    return unique[:5]


def _build_model_prior_flights(
    origin_code: str,
    dest_code: str,
    currency: str,
    cabin_class: str,
) -> list[dict[str, object]]:
    """Deprecated strict mode: do not synthesize flight schedules or fares."""
    _ = (origin_code, dest_code, currency, cabin_class)
    return []


_HOTEL_BRANDS = [
    "Marriott",
    "Hilton",
    "Hyatt",
    "Radisson",
    "Taj",
    "Oberoi",
    "Accor",
    "Novotel",
    "Ibis",
    "Sheraton",
    "Westin",
]


def _extract_stars(text: str) -> float | None:
    match = re.search(
        r"\b([1-5](?:\.\d)?)\s*(?:/5|stars?|\*)\b", text, flags=re.IGNORECASE
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _pick_hotel_name(text: str) -> str:
    for brand in _HOTEL_BRANDS:
        if brand.lower() in text.lower():
            return brand
    return "Unspecified Hotel"


def _extract_loyalty_program(hotel_name: str) -> str | None:
    name = hotel_name.lower()
    if "marriott" in name or "sheraton" in name or "westin" in name:
        return "Marriott Bonvoy"
    if "hilton" in name:
        return "Hilton Honors"
    if "hyatt" in name:
        return "World of Hyatt"
    if "radisson" in name:
        return "Radisson Rewards"
    if "accor" in name or "ibis" in name or "novotel" in name:
        return "ALL - Accor Live Limitless"
    return None


def _normalize_hotels(
    raw: str,
    *,
    fallback_currency: str,
    destination: str,
    default_booking: str,
) -> list[dict[str, object]]:
    chunks = [c.strip() for c in raw.split("---") if c.strip()]
    hotels: list[dict[str, object]] = []
    for chunk in chunks:
        name = _pick_hotel_name(chunk)
        price, ccy = _extract_price(chunk, fallback_currency)
        stars = _extract_stars(chunk)
        booking_link = _extract_url(chunk) or default_booking
        loyalty = _extract_loyalty_program(name)

        confidence = 0.45
        confidence += 0.2 if name != "Unspecified Hotel" else 0.0
        confidence += 0.2 if price is not None else 0.0
        confidence += 0.1 if stars is not None else 0.0
        confidence += 0.05 if loyalty else 0.0

        hotels.append(
            {
                "name": name,
                "price_per_night": price,
                "currency": ccy,
                "stars": stars,
                "area": destination,
                "booking_link": booking_link,
                "loyalty_program": loyalty,
                "confidence": round(min(confidence, 0.95), 2),
            }
        )

    seen: set[tuple] = set()
    unique: list[dict[str, object]] = []
    for item in hotels:
        key = (item.get("name"), item.get("price_per_night"), item.get("currency"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(
        key=lambda x: (
            x.get("price_per_night") is None,
            x.get("price_per_night")
            if isinstance(x.get("price_per_night"), (int, float))
            else float("inf"),
            -(
                x.get("confidence")
                if isinstance(x.get("confidence"), (int, float))
                else 0.0
            ),
        )
    )
    return unique[:5]


_GROUND_PROVIDERS = [
    "IRCTC",
    "RedBus",
    "Trainline",
    "Omio",
    "Uber",
    "Ola",
    "BlaBlaCar",
]


def _detect_transport_mode(text: str) -> str:
    lower = text.lower()
    if "train" in lower or "rail" in lower:
        return "train"
    if "bus" in lower or "coach" in lower:
        return "bus"
    if "cab" in lower or "taxi" in lower or "uber" in lower or "ola" in lower:
        return "cab"
    if "shuttle" in lower:
        return "shuttle"
    return "unknown"


def _pick_ground_provider(text: str) -> str:
    for provider in _GROUND_PROVIDERS:
        if provider.lower() in text.lower():
            return provider
    return "Unknown Provider"


def _normalize_ground_options(
    raw: str,
    *,
    fallback_currency: str,
    default_booking: str,
) -> list[dict[str, object]]:
    chunks = [c.strip() for c in raw.split("---") if c.strip()]
    options: list[dict[str, object]] = []
    for chunk in chunks:
        mode = _detect_transport_mode(chunk)
        provider = _pick_ground_provider(chunk)
        price, ccy = _extract_price(chunk, fallback_currency)
        dep_time, arr_time = _extract_times(chunk)
        duration = _extract_duration(chunk)
        booking_link = _extract_url(chunk) or default_booking

        confidence = 0.45
        confidence += 0.2 if mode != "unknown" else 0.0
        confidence += 0.15 if provider != "Unknown Provider" else 0.0
        confidence += 0.15 if price is not None else 0.0
        confidence += 0.1 if duration else 0.0
        confidence += 0.05 if dep_time else 0.0

        options.append(
            {
                "mode": mode,
                "provider": provider,
                "price": price,
                "currency": ccy,
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration,
                "booking_link": booking_link,
                "confidence": round(min(confidence, 0.95), 2),
            }
        )

    seen: set[tuple] = set()
    unique: list[dict[str, object]] = []
    for item in options:
        key = (
            item.get("mode"),
            item.get("provider"),
            item.get("departure_time"),
            item.get("price"),
            item.get("currency"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(
        key=lambda x: (
            x.get("price") is None,
            x.get("price")
            if isinstance(x.get("price"), (int, float))
            else float("inf"),
            -(
                x.get("confidence")
                if isinstance(x.get("confidence"), (int, float))
                else 0.0
            ),
        )
    )
    return unique[:5]


def _build_model_prior_ground_options(
    currency: str, preferred_mode: str
) -> list[dict[str, object]]:
    default_rows = [
        {
            "mode": "train",
            "provider": "IRCTC",
            "price": 2200.0
            if currency == "INR"
            else _convert_currency(2200.0, "INR", currency),
            "currency": currency,
            "departure_time": "06:00",
            "arrival_time": "22:00",
            "duration": "16h",
            "booking_link": "https://www.irctc.co.in",
            "confidence": 0.45,
        },
        {
            "mode": "bus",
            "provider": "RedBus",
            "price": 1600.0
            if currency == "INR"
            else _convert_currency(1600.0, "INR", currency),
            "currency": currency,
            "departure_time": "21:30",
            "arrival_time": "14:30",
            "duration": "17h",
            "booking_link": "https://www.redbus.in",
            "confidence": 0.42,
        },
        {
            "mode": "cab",
            "provider": "Uber/Ola",
            "price": 1800.0
            if currency == "INR"
            else _convert_currency(1800.0, "INR", currency),
            "currency": currency,
            "departure_time": None,
            "arrival_time": None,
            "duration": "Varies by traffic",
            "booking_link": "https://www.google.com/maps",
            "confidence": 0.35,
        },
    ]
    if preferred_mode == "all":
        return default_rows
    return [row for row in default_rows if row["mode"] == preferred_mode] or [
        default_rows[-1]
    ]


def _sanitize_flight_rows(
    rows: list[dict[str, object]], target_currency: str
) -> list[dict[str, object]]:
    sanitized: list[dict[str, object]] = []
    for row in rows:
        currency = str(row.get("currency") or target_currency).upper()
        price_value = row.get("price")
        if isinstance(price_value, (int, float)):
            price_value = _convert_currency(
                float(price_value), currency, target_currency
            )
        else:
            price_value = None

        sanitized.append(
            {
                **row,
                "price": price_value,
                "currency": target_currency,
            }
        )
    return sanitized


def _build_india_ground_route_fallback(
    origin: str,
    destination: str,
    target_ccy: str,
    transport_type: str,
) -> list[dict[str, object]]:
    if transport_type == "train":
        preferred = ["train"]
    elif transport_type == "bus":
        preferred = ["bus"]
    elif transport_type == "cab":
        preferred = ["cab"]
    else:
        preferred = ["train", "bus", "cab"]

    route_name = f"{origin} → {destination}"
    base_rows = {
        "train": {
            "mode": "train",
            "provider": "IRCTC",
            "price": 2200.0,
            "currency": target_ccy,
            "departure_time": "06:00",
            "arrival_time": "22:00",
            "duration": "16h",
            "booking_link": "https://www.irctc.co.in",
            "confidence": 0.55,
            "note": f"Long-haul rail fallback for {route_name}.",
        },
        "bus": {
            "mode": "bus",
            "provider": "RedBus",
            "price": 1600.0,
            "currency": target_ccy,
            "departure_time": "21:30",
            "arrival_time": "14:30",
            "duration": "17h",
            "booking_link": "https://www.redbus.in",
            "confidence": 0.5,
            "note": f"Coach fallback for {route_name}.",
        },
        "cab": {
            "mode": "cab",
            "provider": "Uber/Ola",
            "price": 1800.0,
            "currency": target_ccy,
            "departure_time": None,
            "arrival_time": None,
            "duration": "Varies by traffic",
            "booking_link": "https://www.google.com/maps",
            "confidence": 0.45,
            "note": f"Local/private fallback for {route_name}.",
        },
    }
    return [base_rows[mode] for mode in preferred]


def _build_model_prior_hotels(
    currency: str,
    destination: str,
    guests: int,
    brand_preference: str | None,
    budget_per_night: str | None,
) -> list[dict[str, object]]:
    base = 7000.0 if currency == "INR" else 120.0
    multiplier = 1.2 if guests > 2 else 1.0
    budget_low, budget_high = _parse_budget_range(budget_per_night)
    preferred = brand_preference or "Radisson"
    p1 = round(base * multiplier, 2)
    p2 = round(base * 0.85 * multiplier, 2)
    p3 = round(base * 1.15 * multiplier, 2)
    if budget_low is not None and budget_high is not None:
        p1 = round(max(budget_high, p1), 2)
        p2 = round(max(budget_high * 0.9, p2), 2)
        p3 = round(max(budget_high * 1.1, p3), 2)

    return [
        {
            "name": f"{preferred} (model fallback)",
            "price_per_night": p1,
            "currency": currency,
            "stars": 4.0,
            "area": destination,
            "booking_link": "https://www.google.com/travel/hotels",
            "loyalty_program": _extract_loyalty_program(preferred),
            "confidence": 0.4,
        },
        {
            "name": "Midscale business hotel",
            "price_per_night": p2,
            "currency": currency,
            "stars": 4.0,
            "area": destination,
            "booking_link": "https://www.google.com/travel/hotels",
            "loyalty_program": None,
            "confidence": 0.35,
        },
        {
            "name": "Family-friendly premium stay",
            "price_per_night": p3,
            "currency": currency,
            "stars": 4.5,
            "area": destination,
            "booking_link": "https://www.google.com/travel/hotels",
            "loyalty_program": None,
            "confidence": 0.33,
        },
    ]


# ---------------------------------------------------------------------------
# Flight search
# ---------------------------------------------------------------------------
# SERP API integration for real flight data
# ---------------------------------------------------------------------------


def _search_serp_flights(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    currency: str = "USD",
) -> list[dict[str, object]]:
    """Search flights via SERP API (Google Flights scraping) and extract results."""
    try:
        import requests

        api_key = getattr(settings, "SERP_API_KEY", None)
        if not api_key:
            logger.debug("SERP API key not configured")
            return []

        api_url = "https://api.serpapi.com/search"
        params = {
            "api_key": api_key,
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date,
            "adults": adults,
            "currency": currency,
            "type": 1,  # One-way
        }

        response = requests.get(api_url, params=params, timeout=15)
        if response.status_code != 200:
            logger.warning(f"SERP API error: {response.status_code}")
            return []

        data = response.json()
        best_flights = data.get("best_flights", [])
        other_flights = data.get("other_flights", [])
        all_flights = best_flights + other_flights

        flights: list[dict[str, object]] = []

        for flight in all_flights[:5]:  # Top 5 flights
            try:
                price = flight.get("price")
                airline_name = flight.get("airline", "Unknown")
                duration = flight.get("total_duration", "")

                # Extract times from flight legs
                legs = flight.get("flights", [])
                dep_time = None
                arr_time = None
                stops = len(legs) - 1

                if legs:
                    dep_time = legs[0].get("departure_time", "")
                    arr_time = legs[-1].get("arrival_time", "")

                booking_link = flight.get("booking_links", [{}])[0].get("link", "")

                flights.append(
                    {
                        "airline": airline_name,
                        "price": float(price) if price else None,
                        "currency": currency,
                        "departure_time": dep_time if dep_time else None,
                        "arrival_time": arr_time if arr_time else None,
                        "duration": f"{duration} min" if duration else "unknown",
                        "stops": stops,
                        "booking_link": booking_link
                        or "https://www.google.com/flights",
                        "confidence": 0.98,
                        "source": "serp",
                    }
                )
            except Exception as e:
                logger.debug(f"Error parsing SERP flight: {str(e)}")
                continue

        if flights:
            logger.info(f"SERP API found {len(flights)} flights")
        return flights

    except Exception as e:
        logger.warning(f"SERP flight search failed: {str(e)}")
        return []


def _search_serp_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    guests: int = 2,
    currency: str = "USD",
) -> list[dict[str, object]]:
    """Search hotels via SERP API (Google Hotels scraping) and extract results."""
    try:
        import requests

        api_key = getattr(settings, "SERP_API_KEY", None)
        if not api_key:
            logger.debug("SERP API key not configured for hotels")
            return []

        api_url = "https://api.serpapi.com/search"
        params = {
            "api_key": api_key,
            "engine": "google_hotels",
            "q": destination,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": guests,
            "currency": currency,
        }

        response = requests.get(api_url, params=params, timeout=15)
        if response.status_code != 200:
            logger.warning(f"SERP API (hotels) error: {response.status_code}")
            return []

        data = response.json()
        hotel_results = data.get("properties", [])
        hotels: list[dict[str, object]] = []

        for hotel in hotel_results[:5]:  # Top 5 hotels
            try:
                price = hotel.get("price")
                hotel_name = hotel.get("name", "Unknown")
                rating = (
                    hotel.get("review_snippets", [{}])[0].get("rating")
                    if hotel.get("review_snippets")
                    else None
                )
                area = hotel.get("address", "")
                booking_link = hotel.get("link", "https://www.google.com/travel/hotels")

                hotels.append(
                    {
                        "name": hotel_name,
                        "price_per_night": float(price) if price else None,
                        "currency": currency,
                        "stars": float(rating) if rating else 3.5,
                        "area": area if area else destination,
                        "booking_link": booking_link,
                        "confidence": 0.95,
                        "source": "serp",
                    }
                )
            except Exception as e:
                logger.debug(f"Error parsing SERP hotel: {str(e)}")
                continue

        if hotels:
            logger.info(f"SERP API found {len(hotels)} hotels")
        return hotels

    except Exception as e:
        logger.warning(f"SERP hotel search failed: {str(e)}")
        return []


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
    currency: str | None = None,
    flight_number: str | None = None,
    force_live_data: bool = False,
) -> str:
    """Search for flights with smart RAG/API strategy to save credits while honoring user intent.

    ✅ REAL DATA: Smart caching - checks RAG first UNLESS user asks for latest data

    Strategy:
    1) Normalize cities to IATA codes
    2) Check if user wants "latest/current/real-time" data → skip cache if yes
    3) TRY 1: Check RAG/vector database for cached flight data (SAVES CREDITS) *unless force_live_data=True*
    4) TRY 2: If not found or force_live_data=True, query SERP API for live flight offers and prices
    5) TRY 3: Fall back to Firecrawl web search if SERP fails
    6) Extract and normalize flight rows if available
    7) If no live data found, return helpful links to official booking sites
    8) Never invent flight data - transparency > guessing

    Args:
        origin_city: Departure city (e.g. "Pune, India")
        destination_city: Destination city (e.g. "Paris, France")
        departure_date: Date in YYYY-MM-DD format
        return_date: Return date for round-trip, None for one-way (SERP: not yet supported)
        cabin_class: economy | premium_economy | business | first
        passengers: Number of passengers
        currency: Preferred currency for results (e.g. "INR", "USD", "EUR")
        flight_number: Specific flight number to research (e.g. "6E 2045")
        force_live_data: If True or user asks for "latest", skip cache and query live API
    """
    logger.info(
        "Flight search requested",
        origin_city=origin_city,
        destination_city=destination_city,
        departure_date=departure_date,
        return_date=return_date,
        cabin_class=cabin_class,
        passengers=passengers,
        flight_number=flight_number,
    )
    origin_code = _city_to_code(origin_city)
    dest_code = _city_to_code(destination_city)
    loc = _get_locality(destination_city)
    target_ccy = (currency or loc["ccy"]).upper()
    trip_type = "round_trip" if return_date else "one_way"
    fallback_booking = "https://www.google.com/travel/flights"

    flights = []
    source_layer = "no_live_data"

    # Check if user explicitly wants live data
    skip_cache = force_live_data or _wants_live_data(flight_number or origin_city)

    if skip_cache:
        logger.info("User requested live data - skipping cache to query API")

    # TRY 1: Check RAG/Vector Database First (SAVES API CREDITS) - unless user wants live data
    # ==============================================================================
    if not skip_cache:
        logger.debug(
            f"Attempting RAG lookup for flights {origin_code} -> {dest_code} on {departure_date}"
        )
        try:
            rag_query = f"flights {origin_code} to {dest_code} {departure_date} {cabin_class} {passengers} passengers {target_ccy}"
            rag_data = await get_kb_fallback(rag_query, k=5)
            if rag_data and "[search_error:" not in rag_data:
                flights = _normalize_flights(
                    rag_data,
                    fallback_currency=target_ccy,
                    default_booking="https://www.google.com/travel/flights",
                    origin_city=origin_city,
                    destination_city=destination_city,
                    origin_code=origin_code,
                    destination_code=dest_code,
                )
                if flights:
                    flights = _sanitize_flight_rows(flights, target_ccy)
                    logger.info(
                        f"RAG database successful: found {len(flights)} cached flights - API CREDIT SAVED"
                    )
                    source_layer = "vector_kb"
        except Exception as e:
            logger.debug(f"RAG lookup failed: {str(e)}")

    # TRY 2: SERP API (real Google Flights data, if RAG had no results)
    # ==================================================================
    if not flights or source_layer == "no_live_data":
        logger.debug("Attempting SERP API flight search")
        try:
            flights = _search_serp_flights(
                origin=origin_code,
                destination=dest_code,
                departure_date=departure_date,
                adults=passengers,
                currency=target_ccy,
            )
            if flights:
                logger.info(f"SERP API successful: found {len(flights)} flights")
                source_layer = "serp_api"
            else:
                logger.debug("SERP API returned no results")
        except Exception as e:
            logger.warning(f"SERP API search failed: {str(e)}")

    # TRY 3: Fall back to Firecrawl web search (if SERP didn't work)
    # ==================================================================
    if not flights or source_layer == "no_live_data":
        logger.debug("Using Firecrawl-based flight extraction as fallback")

        fn_q = f" {flight_number}" if flight_number else ""
        # Search queries for flight pricing information
        targeted_queries = [
            f"cheapest flights {origin_code} to {dest_code} {departure_date}{fn_q}",
            f"{origin_city.split(',')[0]} to {destination_city.split(',')[0]} flight prices {departure_date}",
            f"best flight deals {origin_code} {dest_code} {departure_date}",
        ]

        # Add India-specific sources for INR currency
        if "INR" == target_ccy:
            targeted_queries.extend(
                [
                    f"makemytrip flights {origin_city} to {destination_city} {departure_date}",
                    f"indigo air india flights {origin_code} {dest_code}",
                ]
            )

        source_layer = "web_scrape"
        raw = _firecrawl_search(targeted_queries, limit=5)
        flights = (
            _normalize_flights(
                raw,
                fallback_currency=target_ccy,
                default_booking=fallback_booking,
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
            logger.info(f"Firecrawl fallback found {len(flights)} flights")
        else:
            # No live data available from either source
            source_layer = "fallback_links"
            flights = []

    payload: dict[str, object] = {
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
        "extraction_method": "serp_api"
        if source_layer == "serp_api"
        else "firecrawl_web_search"
        if source_layer == "web_scrape"
        else "booking_links",
        "grounding": {
            "strict_tool_grounding": True,
            "allow_exact_schedules": source_layer in ["playwright", "web_scrape"],
            "requires_user_verification": source_layer
            in ["no_live_data", "fallback_links"],
        },
        "data_quality": {
            "is_live_data": source_layer in ["playwright", "web_scrape"],
            "is_real_time": source_layer == "playwright",
            "extraction_method": source_layer,
            "timestamp": None,
        },
        "notes": [
            f"📊 Extraction method: {source_layer.upper()}",
            ""
            if source_layer in ["playwright", "web_scrape"]
            else "⚠️ Live flight data unavailable",
            ""
            if source_layer in ["playwright", "web_scrape"]
            else "✅ SOLUTION: Check these OFFICIAL sources for accurate current pricing:",
            "" if source_layer in ["playwright", "web_scrape"] else "",
            "🌐 RECOMMENDED BOOKING SITES (Real-time data):",
            "  1. 🔵 Google Flights → https://www.google.com/travel/flights",
            "     (Best for price comparison & flexible dates)",
            "",
            "  2. 🟦 Skyscanner → https://www.skyscanner.com",
            "     (Compare multiple airlines & prices)",
            "",
            "  3. 🟨 Kayak → https://www.kayak.com",
            "     (Price alerts & flexible search)",
            "",
            "✈️ DIRECT AIRLINE BOOKING (Often cheapest):",
            "  • IndiGo → https://www.goindigo.in",
            "  • Air India → https://www.airindia.com",
            "  • SpiceJet → https://www.spicejet.com",
            "  • Vistara → https://www.vistara.com",
            "",
            "🇮🇳 INDIA-SPECIFIC (for domestic flights):",
            "  • MakeMyTrip → https://www.makemytrip.com (₹ prices)",
            "  • OneMyTrip → https://www.onemytrip.com",
            "",
            "💡 PRO TIPS:",
            "  → Prices drop Tuesday-Wednesday (avoid weekends)",
            "  → Book 1-3 months in advance for best prices",
            "  → Use flexible date search to find cheaper alternatives",
            "  → Clear browser cookies before comparing prices",
        ],
        "recommended_live_sources": [
            s
            for s in [
                "https://www.google.com/travel/flights",
                "https://www.skyscanner.com",
                "https://www.kayak.com",
                "https://www.goindigo.in" if origin_code and dest_code else None,
                "https://www.airindia.com" if origin_code and dest_code else None,
                "https://www.makemytrip.com" if target_ccy == "INR" else None,
            ]
            if s is not None
        ],
    }

    response = json.dumps(payload, indent=2)
    persist_tool_result(
        "search_flights",
        response,
        metadata={
            "origin": origin_city,
            "destination": destination_city,
            "origin_iata": origin_code,
            "destination_iata": dest_code,
            "departure_date": departure_date,
            "source_layer": source_layer,
            "extraction_method": "serp_api"
            if source_layer == "serp_api"
            else "firecrawl"
            if source_layer == "web_scrape"
            else "fallback_links",
            "flight_count": len(flights),
        },
        status="ok" if source_layer in ["serp_api", "web_scrape"] else "partial",
    )
    _log_tool_outcome(
        "search_flights",
        source_layer=source_layer,
        result_count=len(flights),
        extraction_method="serp_api"
        if source_layer == "serp_api"
        else "firecrawl"
        if source_layer == "web_scrape"
        else "fallback_links",
        fallback_reason="serp_api_failed"
        if source_layer == "web_scrape"
        else "no_live_data"
        if source_layer == "fallback_links"
        else None,
        origin_city=origin_city,
        destination_city=destination_city,
        origin_iata=origin_code,
        destination_iata=dest_code,
        departure_date=departure_date,
        return_date=return_date,
    )
    return response


# ---------------------------------------------------------------------------
# Airport terminal transit info
# ---------------------------------------------------------------------------


@tool
async def get_airport_transit(
    airport_name: str,
    from_terminal: str,
    to_terminal: str,
) -> str:
    r"""Get transit time and method between terminals at an airport.

    Use this whenever a passenger has a layover and needs to change terminals
    (e.g. Mumbai BOM T1 domestic to T2 international, CDG "Terminal 1" to "Terminal 2E").

    Args:
        airport_name: Full airport name or city (e.g. "Mumbai", "Charles de Gaulle")
        from_terminal: Departure terminal (e.g. "T1", "Terminal 1", "domestic")
        to_terminal: Arrival terminal (e.g. "T2", "Terminal 2E", "international")
    """
    logger.info(
        "Airport transit lookup requested",
        airport_name=airport_name,
        from_terminal=from_terminal,
        to_terminal=to_terminal,
    )
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
            "pune": "Pune Airport PNQ: single integrated passenger terminal operations for most flights. If your itinerary shows T1/T2 labels from aggregators, treat as operational zones in one terminal. Internal transfer is usually 5-15 min by foot with airline check-in/security queues as main delay.",
            "mumbai": "Mumbai BOM: T1 (domestic) to T2 (international) — free shuttle bus, ~30-45 min journey. Allow 2.5h minimum for connection.",
            "delhi": "Delhi DEL: All terminals connected via aerotrain/walkway. T1 to T2/T3 ~20-30 min. T2↔T3 ~10 min via shuttle.",
            "dubai": "Dubai DXB: T1/T2/T3 are separate buildings. T3 to T1 ~30 min bus. Allow 2h for connections.",
            "paris": "Paris CDG: CDGVAL free shuttle connects T1, T2, T3. ~8-15 min between terminals. T2 has sub-terminals (A-G); same building 5-10 min walk.",
            "london": "London LHR: T2/T3 connected via tunnel (~15 min walk). T4/T5 require Heathrow Express (15 min, free for connections).",
            "frankfurt": "Frankfurt FRA: T1 and T2 connected via SkyLine train, 3 min. T1 A/B/C/D/Z all walkable within 10-20 min.",
        }
        info_res = f"Terminal transit info for {airport_name}: Allow 30-60 min for terminal changes. Check airport website for shuttle/bus details."
        for key, info in fallbacks.items():
            if key in airport_name.lower():
                info_res = info
                break
        _log_tool_outcome(
            "get_airport_transit",
            source_layer="fallback",
            fallback_reason="live_search_unavailable",
            airport_name=airport_name,
            from_terminal=from_terminal,
            to_terminal=to_terminal,
        )
    else:
        info_res = f"**Terminal transit at {airport_name} ({from_terminal} → {to_terminal}):**\n\n{raw}"
        _log_tool_outcome(
            "get_airport_transit",
            source_layer="web_scrape",
            airport_name=airport_name,
            from_terminal=from_terminal,
            to_terminal=to_terminal,
        )

    persist_tool_result(
        "get_airport_transit",
        f"Airport transit info for {airport_name} from {from_terminal} to {to_terminal}:\n{info_res}",
        metadata={
            "airport": airport_name,
            "from_terminal": from_terminal,
            "to_terminal": to_terminal,
        },
        status="ok" if raw and "[search_error:" not in raw else "fallback",
    )

    return info_res


# ---------------------------------------------------------------------------
# Ground transport search (Trains, Buses, Cabs)
# ---------------------------------------------------------------------------


@tool
async def search_ground_transport(
    origin: str,
    destination: str,
    date: str,
    transport_type: str = "all",
    currency: str | None = None,
) -> str:
    """Search for ground transport options (Trains, Buses, Cabs, Shuttles).

    Use this for regional travel (e.g. Pune to Mumbai) or last-mile connectivity.
    It researches services like IRCTC, RedBus, Trainline, Omio, and Uber/Ola estimates.
    Also considers "Hotel Travel Desk" as a reliable option for local booking.

    Args:
        origin: Departure point (e.g. "Pune Station", "CDG Airport")
        destination: Arrival point (e.g. "Mumbai South", "Paris Centre")
        date: YYYY-MM-DD
        transport_type: "train" | "bus" | "cab" | "all"
        currency: Preferred currency for results (e.g. "INR", "USD")
    """
    logger.info(
        "Ground transport search requested",
        origin=origin,
        destination=destination,
        date=date,
        transport_type=transport_type,
        currency=currency,
    )
    type_q = (
        f"{transport_type} " if transport_type != "all" else "train bus cab shuttle "
    )
    loc = _get_locality(origin)
    target_ccy = (currency or loc["ccy"]).upper()
    fallback_booking = "https://www.google.com/maps"

    queries = [
        f"site:irctc.co.in {type_q}{origin} to {destination} {date} fare schedule",
        f"site:redbus.in {type_q}{origin} to {destination} {date} fare",
        f"site:trainline.com OR site:omio.com {type_q}{origin} to {destination} {date}",
        f"{type_q} options from {origin} to {destination} {date} schedule and price in {target_ccy}",
    ]

    source_layer = "web_scrape"
    raw = _firecrawl_search(queries, limit=4)
    options = (
        _normalize_ground_options(
            raw,
            fallback_currency=target_ccy,
            default_booking=fallback_booking,
        )
        if raw and "[search_error:" not in raw
        else []
    )

    if not options:
        source_layer = "vector_kb"
        kb_query = f"ground transport {transport_type} {origin} to {destination} {date} {target_ccy}"
        kb_raw = await get_kb_fallback(kb_query, k=4)
        options = (
            _normalize_ground_options(
                kb_raw,
                fallback_currency=target_ccy,
                default_booking=fallback_booking,
            )
            if kb_raw
            else []
        )

    if not options:
        source_layer = "model_prior"
        options = _build_model_prior_ground_options(target_ccy, transport_type)

    if (
        len(options) < 2
        and "india" in origin.lower()
        and "india" in destination.lower()
    ):
        source_layer = (
            "route_fallback" if source_layer != "model_prior" else source_layer
        )
        fallback_options = _build_india_ground_route_fallback(
            origin,
            destination,
            target_ccy,
            transport_type,
        )
        existing_modes = {str(option.get("mode")) for option in options}
        for option in fallback_options:
            if option["mode"] not in existing_modes:
                options.append(option)

    for option in options:
        option["currency"] = target_ccy
        if isinstance(option.get("price"), (int, float)):
            option["price"] = round(float(option["price"]), 2)

    payload: dict[str, object] = {
        "query": {
            "origin": origin,
            "destination": destination,
            "date": date,
            "transport_type": transport_type,
            "currency": target_ccy,
        },
        "options": options,
        "source_layer": source_layer,
        "notes": [
            "Ground transport times vary with traffic and seasonal demand.",
            "If options are sparse, confirm with local operator or hotel desk.",
        ],
    }
    response = json.dumps(payload, indent=2)

    persist_tool_result(
        "search_ground_transport",
        response,
        metadata={
            "origin": origin,
            "destination": destination,
            "date": date,
            "transport_type": transport_type,
            "currency": target_ccy,
            "source_layer": source_layer,
        },
        status="ok" if source_layer != "model_prior" else "fallback",
    )
    _log_tool_outcome(
        "search_ground_transport",
        source_layer=source_layer,
        result_count=len(options),
        fallback_reason=(
            "web_search_empty"
            if source_layer == "vector_kb"
            else "kb_empty"
            if source_layer == "model_prior"
            else "sparse_route_backfill"
            if source_layer == "route_fallback"
            else None
        ),
        origin=origin,
        destination=destination,
        date=date,
        transport_type=transport_type,
    )

    return response


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
    currency: str | None = None,
    force_live_data: bool = False,
) -> str:
    """Search for hotels with smart RAG/API strategy to save credits while honoring user intent.

    ✅ REAL DATA: Smart caching - checks RAG first UNLESS user asks for latest data

    Strategy:
    1) Check if user wants "latest/current/real-time" data → skip cache if yes
    2) TRY 1: Check RAG/vector database for cached hotel data (SAVES CREDITS) *unless force_live_data=True*
    3) TRY 2: If not found or force_live_data=True, query SERP API for live hotel offers and prices
    4) TRY 3: Fall back to web search if SERP fails
    5) TRY 4: Model prior fallback
    6) Returns 3-5 hotel options as a markdown comparison with pricing, ratings

    Args:
        destination: City and area (e.g. "Paris near Eiffel Tower")
        check_in: YYYY-MM-DD
        check_out: YYYY-MM-DD
        guests: Number of guests
        stars: Preferred minimum stars (3, 4, or 5)
        brand_preference: Chain preference (e.g. "Radisson", "Marriott", "IHG")
        budget_per_night: Budget range (e.g. "100-150")
        currency: Preferred currency for results (e.g. "INR", "USD")
        force_live_data: If True or user asks for "latest", skip cache and query live API
    """
    logger.info(
        "Hotel search requested",
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        stars=stars,
        brand_preference=brand_preference,
        budget_per_night=budget_per_night,
        currency=currency,
    )
    brand_q = f"{brand_preference} " if brand_preference else ""
    stars_q = f"{stars} star " if stars else ""
    budget_q = f"budget {budget_per_night}" if budget_per_night else ""

    loc = _get_locality(destination)
    target_ccy = (currency or loc["ccy"]).upper()
    fallback_booking = "https://www.google.com/travel/hotels"
    hotels = []
    source_layer = "no_live_data"

    # Check if user explicitly wants live data
    skip_cache = force_live_data or _wants_live_data(destination or brand_preference)

    if skip_cache:
        logger.info("User requested live data - skipping cache to query API")

    # TRY 1: Check RAG/Vector Database First (SAVES API CREDITS) - unless user wants live data
    # ==============================================================================
    if not skip_cache:
        logger.debug(
            f"Attempting RAG lookup for hotels in {destination} {check_in} to {check_out}"
        )
        try:
            rag_query = (
                f"hotels in {destination} check in {check_in} check out {check_out} "
                f"guests {guests} stars {stars or 'any'} {brand_preference or ''} {target_ccy}"
            )
            rag_raw = await get_kb_fallback(rag_query, k=5)
            if rag_raw and "[search_error:" not in rag_raw:
                hotels = _normalize_hotels(
                    rag_raw,
                    fallback_currency=target_ccy,
                    destination=destination,
                    default_booking=fallback_booking,
                )
                if hotels:
                    logger.info(
                        f"RAG database successful: found {len(hotels)} cached hotels - API CREDIT SAVED"
                    )
                    source_layer = "vector_kb"
        except Exception as e:
            logger.debug(f"RAG lookup failed: {str(e)}")

    # TRY 2: SERP API (real Google Hotels data, if RAG had no results or user wants live data)
    # ==================================================================
    if not hotels or source_layer == "no_live_data":
        logger.debug("Attempting SERP API hotel search")
        try:
            hotels = _search_serp_hotels(
                destination=destination,
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                currency=target_ccy,
            )
            if hotels:
                logger.info(f"SERP API successful: found {len(hotels)} hotels")
                source_layer = "serp_api"
            else:
                logger.debug("SERP API returned no results")
        except Exception as e:
            logger.warning(f"SERP API hotel search failed: {str(e)}")

    # TRY 3: Fall back to web scraping if SERP didn't work
    # ==================================================================
    if not hotels or source_layer == "no_live_data":
        logger.debug("Using Firecrawl-based hotel extraction as fallback")
        queries = [
            f"site:google.com/travel/hotels hotels in {destination} {check_in} {check_out} {stars_q} {brand_q} {budget_q}",
            f"site:booking.com hotels in {destination} {check_in} {check_out} {stars_q} {budget_q}",
            f"site:agoda.com OR site:expedia.com hotels in {destination} {check_in} {check_out}",
        ]
        source_layer = "web_scrape"
        raw = _firecrawl_search(queries, limit=4)
        hotels = (
            _normalize_hotels(
                raw,
                fallback_currency=target_ccy,
                destination=destination,
                default_booking=fallback_booking,
            )
            if raw and "[search_error:" not in raw
            else []
        )

    # TRY 4: Fall back to model prior if nothing else worked
    # ==================================================================
    if not hotels or source_layer == "no_live_data":
        logger.debug("Using model prior hotel generation as fallback")
        source_layer = "model_prior"
        hotels = _build_model_prior_hotels(
            target_ccy,
            destination,
            guests,
            brand_preference,
            budget_per_night,
        )

    payload: dict[str, object] = {
        "query": {
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
            "stars": stars,
            "brand_preference": brand_preference,
            "budget_per_night": budget_per_night,
            "currency": target_ccy,
        },
        "hotels": hotels,
        "source_layer": source_layer,
        "notes": [
            "Rates can change by availability and cancellation terms.",
            "Verify final taxes/fees on booking page.",
        ],
    }
    response = json.dumps(payload, indent=2)

    persist_tool_result(
        "search_hotels",
        response,
        metadata={
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
            "currency": target_ccy,
            "source_layer": source_layer,
        },
        status="ok" if source_layer != "model_prior" else "fallback",
    )
    _log_tool_outcome(
        "search_hotels",
        source_layer=source_layer,
        result_count=len(hotels),
        fallback_reason=(
            "web_search_empty"
            if source_layer == "vector_kb"
            else "kb_empty"
            if source_layer == "model_prior"
            else None
        ),
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
    )

    return response


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
    logger.info(
        "Place details lookup requested",
        place_name=place_name,
        city=city,
        detail_type=detail_type,
    )
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

    if raw and "[search_error:" not in raw:
        results_str = f"**{place_name} details:**\n\n{raw}"
        status = "ok"
        source_layer = "web_scrape"
    else:
        kb_query = f"{place_name} {city} ticket price opening hours transit"
        kb_raw = await get_kb_fallback(kb_query, k=3)
        source_layer = "vector_kb"

        priors: dict[str, dict[str, str | int]] = {
            "red fort": {
                "ticket": "INR 50 (Indian), INR 600 (foreign)",
                "hours": "09:30-16:30, closed Monday",
                "transit": "Delhi Metro Red Line, Lal Qila station",
                "tip": "Arrive before 10:00 for lower heat and queues",
            },
            "india gate": {
                "ticket": "Free public monument area",
                "hours": "Open 24h",
                "transit": "Central Secretariat / Khan Market + short cab",
                "tip": "Best visited evening in summer",
            },
            "qutub minar": {
                "ticket": "INR 50 (Indian), INR 600 (foreign)",
                "hours": "Sunrise to sunset",
                "transit": "Qutub Minar metro station + auto/cab",
                "tip": "Morning visit recommended",
            },
        }

        place_key = place_name.lower().strip()
        prior = None
        for k, v in priors.items():
            if k in place_key:
                prior = v
                break

        if kb_raw:
            results_str = (
                f"**{place_name} details (knowledge base fallback):**\n\n{kb_raw}"
            )
            status = "fallback"
        elif prior:
            results_str = (
                f"**{place_name} ({city}) — fallback details**\n"
                f"- Ticket: {prior['ticket']}\n"
                f"- Hours: {prior['hours']}\n"
                f"- Transit: {prior['transit']}\n"
                f"- Tip: {prior['tip']}"
            )
            status = "fallback"
            source_layer = "model_prior"
        else:
            results_str = (
                f"Details for {place_name} are currently sparse from live sources. "
                "Use city tourism board or Google Maps listing for latest hours and ticket updates."
            )
            status = "fallback"
            source_layer = "no_live_data"

    persist_tool_result(
        "get_place_details",
        f"Details for {place_name} in {city}:\n{results_str}",
        metadata={
            "place": place_name,
            "city": city,
            "detail_type": detail_type,
        },
        status=status,
    )
    _log_tool_outcome(
        "get_place_details",
        source_layer=source_layer,
        fallback_reason=None if status == "ok" else "live_details_unavailable",
        place_name=place_name,
        city=city,
        detail_type=detail_type,
    )

    return results_str
