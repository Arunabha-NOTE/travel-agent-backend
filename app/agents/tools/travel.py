"""Flight search, hotel search, place details, and local transit tools."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langchain_core.tools import tool

from app.agents.tools.utils import (
    get_kb_fallback,
    persist_tool_result,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        if not cleaned or cleaned in {"-", ".", "-."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


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
        "exact price",
        "exact prices",
        "confirmed price",
        "confirmed prices",
        "live price",
        "live prices",
        "exact fare",
        "exact fares",
    ]
    return any(keyword in q_lower for keyword in live_keywords)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_recent_cache_entry(
    metadata: dict[str, object], *, max_age_days: int = 14
) -> bool:
    timestamp = _parse_iso_datetime(str(metadata.get("timestamp") or ""))
    if not timestamp:
        return False
    age = datetime.now(timezone.utc) - timestamp
    return age.days <= max_age_days


def _matches_requested_date(
    metadata: dict[str, object],
    *,
    requested_departure_date: str | None = None,
    requested_check_in: str | None = None,
    requested_check_out: str | None = None,
) -> bool:
    if requested_departure_date:
        cached_departure = str(metadata.get("departure_date") or "")
        if cached_departure and cached_departure != requested_departure_date:
            return False
    if requested_check_in:
        cached_check_in = str(metadata.get("check_in") or "")
        if cached_check_in and cached_check_in != requested_check_in:
            return False
    if requested_check_out:
        cached_check_out = str(metadata.get("check_out") or "")
        if cached_check_out and cached_check_out != requested_check_out:
            return False
    return True


def _date_filter_message(
    *,
    requested_departure_date: str | None = None,
    requested_check_in: str | None = None,
    requested_check_out: str | None = None,
) -> str:
    if requested_departure_date:
        return requested_departure_date
    if requested_check_in or requested_check_out:
        return (
            f"{requested_check_in or 'unknown'} to {requested_check_out or 'unknown'}"
        )
    return "unknown"


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


def _extract_serp_hotel_class(item: dict[str, object]) -> float | None:
    for key in ("extracted_hotel_class", "hotel_class"):
        value = item.get(key)
        numeric = _safe_float(value)
        if numeric is not None:
            return numeric
        if isinstance(value, str):
            match = re.search(r"\b([1-5](?:\.\d)?)", value)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
    return None


def _extract_serp_hotel_price(
    item: dict[str, object], fallback_currency: str
) -> tuple[float | None, str]:
    rate_per_night = item.get("rate_per_night")
    if isinstance(rate_per_night, dict):
        for key in (
            "extracted_lowest",
            "extracted_before_taxes_fees",
            "lowest",
            "before_taxes_fees",
        ):
            value = rate_per_night.get(key)
            if isinstance(value, (int, float)):
                return float(value), fallback_currency
            if isinstance(value, str):
                price, currency = _extract_price(value, fallback_currency)
                if price is not None:
                    return price, currency

    for key in ("extracted_price", "price"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value), fallback_currency
        if isinstance(value, str):
            price, currency = _extract_price(value, fallback_currency)
            if price is not None:
                return price, currency

    return None, fallback_currency


def _extract_serp_hotel_booking_link(
    item: dict[str, object], default_booking: str
) -> str:
    for key in ("link", "serpapi_property_details_link"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return default_booking


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


def _hotel_row_needs_gapfill(hotel: dict[str, object]) -> bool:
    return any(
        hotel.get(field) in (None, "")
        for field in ("price_per_night", "booking_link", "stars")
    )


def _flight_row_needs_gapfill(flight: dict[str, object]) -> bool:
    return any(
        flight.get(field) in (None, "")
        for field in ("price", "booking_link", "departure_time", "arrival_time")
    )


def _gapfill_hotel_row_with_firecrawl(
    hotel: dict[str, object],
    *,
    destination: str,
    check_in: str,
    check_out: str,
    target_ccy: str,
) -> dict[str, object]:
    if not hotel.get("name"):
        return hotel

    queries = [
        f'"{hotel["name"]}" {destination} {check_in} {check_out} nightly price',
        f'site:google.com/travel/hotels "{hotel["name"]}" {destination}',
    ]
    raw = _firecrawl_search(queries, limit=2)
    if not raw or "[search_error:" in raw:
        return hotel

    filled = dict(hotel)
    price, ccy = _extract_price(raw, target_ccy)
    if filled.get("price_per_night") is None and price is not None:
        filled["price_per_night"] = _convert_currency(price, ccy, target_ccy)
        filled["currency"] = target_ccy

    if filled.get("booking_link") in (None, ""):
        booking_link = _extract_url(raw)
        if booking_link:
            filled["booking_link"] = booking_link

    if filled.get("stars") in (None, ""):
        rating = _extract_stars(raw)
        if rating is not None:
            filled["stars"] = rating

    if filled.get("rating") in (None, ""):
        rating = _extract_stars(raw)
        if rating is not None:
            filled["rating"] = rating

    if filled.get("area") in (None, ""):
        filled["area"] = destination

    return filled


def _gapfill_flight_row_with_firecrawl(
    flight: dict[str, object],
    *,
    origin_city: str,
    destination_city: str,
    departure_date: str,
    return_date: str | None,
    target_ccy: str,
) -> dict[str, object]:
    if not flight.get("airline"):
        return flight

    route = f"{origin_city} to {destination_city}"
    date_clause = (
        departure_date if not return_date else f"{departure_date} return {return_date}"
    )
    queries = [
        f'"{flight["airline"]}" {route} {date_clause} flight price',
        f"site:google.com/travel/flights {route} {date_clause}",
    ]
    raw = _firecrawl_search(queries, limit=2)
    if not raw or "[search_error:" in raw:
        return flight

    filled = dict(flight)
    price, ccy = _extract_price(raw, target_ccy)
    if filled.get("price") is None and price is not None:
        filled["price"] = _convert_currency(price, ccy, target_ccy)
        filled["currency"] = target_ccy

    if filled.get("booking_link") in (None, ""):
        booking_link = _extract_url(raw)
        if booking_link:
            filled["booking_link"] = booking_link

    if filled.get("departure_time") in (None, "") or filled.get("arrival_time") in (
        None,
        "",
    ):
        dep_time, arr_time = _extract_times(raw)
        if filled.get("departure_time") in (None, "") and dep_time:
            filled["departure_time"] = dep_time
        if filled.get("arrival_time") in (None, "") and arr_time:
            filled["arrival_time"] = arr_time

    if filled.get("duration") in (None, ""):
        duration = _extract_duration(raw)
        if duration:
            filled["duration"] = duration

    if filled.get("stops") in (None, ""):
        stops = _extract_stops(raw)
        if stops is not None:
            filled["stops"] = stops

    return filled


# ---------------------------------------------------------------------------
# Flight search
# ---------------------------------------------------------------------------
# SERP API integration for real flight data
# ---------------------------------------------------------------------------


def _search_serp_flights(params_dict: dict) -> dict:
    """Search flights via SERP API and return the raw JSON dict."""
    try:
        import requests
        from app.core.config import settings
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        api_key = getattr(settings, "SERP_API_KEY", None)
        if not api_key:
            logger.debug("SERP API key not configured")
            return {}

        params = {
            "api_key": api_key,
            "engine": "google_flights",
            "gl": getattr(settings, "SERP_GL", "us"),
            "hl": getattr(settings, "SERP_HL", "en"),
        }
        params.update(params_dict)

        api_url = getattr(settings, "SERP_FLIGHTS_URL", "https://serpapi.com/search")
        response = requests.get(api_url, params=params, timeout=20)

        if response.status_code != 200:
            logger.warning(f"SERP API error: {response.status_code}")
            return {}

        return response.json()
    except Exception as e:
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        logger.warning(f"SERP flight search failed: {str(e)}")
        return {}


def _search_serp_hotels(params_dict: dict) -> dict:
    """Search hotels via SERP API and return the raw JSON dict."""
    try:
        import requests
        from app.core.config import settings
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        api_key = getattr(settings, "SERP_API_KEY", None)
        if not api_key:
            logger.debug("SERP API key not configured")
            return {}

        params = {
            "api_key": api_key,
            "engine": "google_hotels",
            "gl": getattr(settings, "SERP_GL", "us"),
            "hl": getattr(settings, "SERP_HL", "en"),
        }
        params.update(params_dict)

        api_url = getattr(settings, "SERP_HOTELS_URL", "https://serpapi.com/search")
        response = requests.get(api_url, params=params, timeout=20)

        if response.status_code != 200:
            logger.warning(f"SERP API error: {response.status_code}")
            return {}

        return response.json()
    except Exception as e:
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        logger.warning(f"SERP hotel search failed: {str(e)}")
        return {}


@tool
async def search_flights(
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    return_date: str | None = None,
    type: str = "1",
    travel_class: str = "1",
    multi_city_json: str | None = None,
    show_hidden: str = "true",
    exclude_basic: str | None = None,
    deep_search: str = "true",
    adults: str = "1",
    children: str | None = None,
    infants_in_seat: str | None = None,
    infants_on_lap: str | None = None,
    sort_by: str = "1",
    stops: str | None = "0",
    exclude_airlines: str | None = None,
    include_airlines: str | None = None,
    bags: str | None = None,
    max_price: str | None = None,
    outbound_times: str | None = None,
    return_times: str | None = None,
    emissions: str | None = None,
    layover_duration: str | None = None,
    exclude_conns: str | None = None,
    max_duration: str | None = None,
    currency: str = "USD",
    force_live_data: bool = False,
) -> str:
    """Search for flights via Google Flights (SERP API).
    Returns exact LIVE pricing and schedules as JSON. Pass the response JSON as is to the user.

    Args:
        departure_id: Departure airport IATA code MUST be capitalized (e.g., "BOM" for Mumbai).
        arrival_id: Arrival airport IATA code MUST be capitalized (e.g., "MLE" for Male).
        outbound_date: Departure date in YYYY-MM-DD.
        return_date: Return date in YYYY-MM-DD.
        type: "1" for Round trip, "2" for One-way, "3" for Multi-city.
        travel_class: "1" (Economy), "2" (Premium Economy), "3" (Business), "4" (First).
        multi_city_json: Used if type is 3. Format: '[{"departure_id":"CDG","arrival_id":"NRT","date":"2026-04-25"}]'.
        show_hidden: "true" to include hidden itineraries.
        exclude_basic: "true" to exclude basic economy.
        deep_search: "true" to do a full search.
        adults: Number of adults ("1").
        children: Number of children ("1").
        infants_in_seat: Number of infants in seat ("1").
        infants_on_lap: Number of infants on lap ("1").
        sort_by: "1" (Top flights), "2" (Price), "3" (Departure Obj.), "4" (Arrival Obj.), "5" (Duration).
        stops: "0" (Nonstop), "1" (max 1 stop), "2" (max 2 stops).
        exclude_airlines: Exclude specific airline code/alliance (e.g., "STAR_ALLIANCE").
        include_airlines: Include specific airline code (e.g., "AI").
        bags: Number of carry-on bags ("1").
        max_price: Max price (e.g., "109000").
        outbound_times: Departure times bounds, format "4,18".
        return_times: Return times bounds, format "4,18".
        emissions: "1" to show less emissions flights.
        layover_duration: "2" for max layover.
        exclude_conns: IATA code for connections to exclude "BOM,PNQ".
        max_duration: Max duration in hours (e.g., "124").
        currency: Currency code (e.g., "INR", "USD").
        force_live_data: Bypass internal caching if True.
    """
    from app.core.logging import get_logger
    from app.agents.tools.utils import persist_tool_result

    logger = get_logger(__name__)
    logger.info(f"Flight search {departure_id} -> {arrival_id} on {outbound_date}")

    params = {
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "currency": currency,
        "type": type,
        "travel_class": travel_class,
        "show_hidden": show_hidden,
        "deep_search": deep_search,
        "adults": adults,
        "sort_by": sort_by,
    }

    if return_date:
        params["return_date"] = return_date
    if multi_city_json:
        params["multi_city_json"] = multi_city_json
    if exclude_basic:
        params["exclude_basic"] = exclude_basic
    if children:
        params["children"] = children
    if infants_in_seat:
        params["infants_in_seat"] = infants_in_seat
    if infants_on_lap:
        params["infants_on_lap"] = infants_on_lap
    if stops is not None:
        params["stops"] = stops
    if exclude_airlines:
        params["exclude_airlines"] = exclude_airlines
    if include_airlines:
        params["include_airlines"] = include_airlines
    if bags:
        params["bags"] = bags
    if max_price:
        params["max_price"] = max_price
    if outbound_times:
        params["outbound_times"] = outbound_times
    if return_times:
        params["return_times"] = return_times
    if emissions:
        params["emissions"] = emissions
    if layover_duration:
        params["layover_duration"] = layover_duration
    if exclude_conns:
        params["exclude_conns"] = exclude_conns
    if max_duration:
        params["max_duration"] = max_duration

    result = _search_serp_flights(params)

    # Truncate response slightly to save LLM context
    if isinstance(result, dict):
        if "best_flights" in result:
            result["best_flights"] = result.get("best_flights", [])[:3]
        if "other_flights" in result:
            result["other_flights"] = result.get("other_flights", [])[:5]
        if "search_metadata" in result:
            for k in ["raw_html_file", "prettify_html_file"]:
                result["search_metadata"].pop(k, None)

    response_str = json.dumps(result, indent=2)

    persist_tool_result(
        "search_flights",
        response_str,
        metadata={
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "departure_date": outbound_date,
        },
        status="ok" if result else "missing",
    )

    return response_str


@tool
async def search_hotels(
    q: str,
    check_in_date: str,
    check_out_date: str,
    adults: str = "2",
    children: str | None = None,
    sort_by: str = "8",
    hotel_classes: str | None = None,
    rating: str | None = None,
    amenities: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    brands: str | None = None,
    free_cancellation: str | None = None,
    currency: str = "USD",
    force_live_data: bool = False,
) -> str:
    """Search for hotels via Google Hotels (SERP API).
    Returns raw JSON dict with exact properties. Pass the JSON response as is to the user.

    Args:
        q: The search query, usually destination (e.g., "Paris hotels", "Bali near beach").
        check_in_date: Check-in date in YYYY-MM-DD.
        check_out_date: Check-out date in YYYY-MM-DD.
        adults: Number of adults ("2").
        children: Ages of children separated by comma ("4,6") or simply number if ages unknown.
        sort_by: "3" (Lowest Price), "8" (Highest Rating), "1" (Relevance).
        hotel_classes: Comma separated list of star ratings (e.g. "3,4,5" or "4").
        rating: Minimum guest rating ("8", "8.5", "9").
        amenities: Comma separated Google Hotel amenity IDs. E.g., "7" (free wifi), "2" (pool), "3" (free parking), "9" (free breakfast).
        min_price: Floor price in specified currency ("100").
        max_price: Ceiling price ("500").
        brands: Brand identifiers (e.g. "100" or explicit names depends on Google).
        free_cancellation: "true" to filter for free cancellation.
        currency: Pricing currency ("USD", "INR").
        force_live_data: Force fresh SERP API lookup bypassing internal caching.
    """
    from app.core.logging import get_logger
    from app.agents.tools.utils import persist_tool_result

    logger = get_logger(__name__)
    logger.info(f"Hotel search requested for {q} on {check_in_date}")

    params = {
        "q": q,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "currency": currency,
        "adults": adults,
        "sort_by": sort_by,
    }

    if children:
        params["children"] = children
    if hotel_classes:
        params["hotel_classes"] = hotel_classes
    if rating:
        params["rating"] = rating
    if amenities:
        params["amenities"] = amenities
    if min_price:
        params["min_price"] = min_price
    if max_price:
        params["max_price"] = max_price
    if brands:
        params["brands"] = brands
    if free_cancellation:
        params["free_cancellation"] = free_cancellation

    result = _search_serp_hotels(params)

    if isinstance(result, dict):
        if "properties" in result:
            result["properties"] = result["properties"][:6]  # Return top 6
        if "search_metadata" in result:
            for k in ["raw_html_file", "prettify_html_file"]:
                result["search_metadata"].pop(k, None)

    response_str = json.dumps(result, indent=2)

    persist_tool_result(
        "search_hotels",
        response_str,
        metadata={
            "destination": q,
            "check_in": check_in_date,
            "check_out": check_out_date,
        },
        status="ok" if result else "missing",
    )

    return response_str


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
        from app.agents.rag.retriever import get_kb_fallback

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
# Airport transit
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
