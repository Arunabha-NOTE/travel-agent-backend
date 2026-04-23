"""LangChain-based travel itinerary agent — multi-step planning flow."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
import ast
import hashlib
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import MAIN_SYSTEM_PROMPT
from app.agents.tool_suite import AGENT_TOOLS
from app.core.config import settings
from app.core.logging import get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.chat_room import ChatRoom
from app.models.planning_session import DEFAULT_PREFERENCES, PlanningSession
from app.models.user import User

logger = get_logger(__name__)

_ITINERARY_WRITE_LOCKS: dict[uuid.UUID, asyncio.Lock] = {}

_DESTINATION_COORDS: dict[str, tuple[float, float]] = {
    "goa": (15.2993, 74.1240),
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "pune": (18.5204, 73.8567),
    "mumbai": (19.0760, 72.8777),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "kolkata": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707),
    "hyderabad": (17.3850, 78.4867),
    "kochi": (9.9312, 76.2673),
    "paris": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
    "rome": (41.9028, 12.4964),
    "tokyo": (35.6762, 139.6503),
    "dubai": (25.2048, 55.2708),
    "singapore": (1.3521, 103.8198),
}

_CITY_TO_IATA: dict[str, str] = {
    "pune": "PNQ",
    "mumbai": "BOM",
    "delhi": "DEL",
    "new delhi": "DEL",
    "goa": "GOI",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "hyderabad": "HYD",
    "chennai": "MAA",
    "kolkata": "CCU",
    "kochi": "COK",
    "paris": "CDG",
    "london": "LHR",
    "dubai": "DXB",
    "singapore": "SIN",
}

_AIRLINES = [
    "IndiGo",
    "Air India",
    "Vistara",
    "Akasa Air",
    "Emirates",
    "Qatar Airways",
    "Etihad",
    "Lufthansa",
]


def _message_content_to_text(content: Any) -> str:
    """Normalize provider message content into plain text."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text") or item.get("content")
                if isinstance(text_value, str):
                    parts.append(text_value)
                    continue
            parts.append(str(item))
        return "\n".join(p for p in parts if p).strip()

    if isinstance(content, dict):
        text_value = content.get("text") or content.get("content")
        if isinstance(text_value, str):
            return text_value

    return str(content or "")


def _is_finalize_request(user_message: str) -> bool:
    lowered = user_message.lower()
    patterns = [
        r"\bfinali[sz]e\b",
        r"\bfinal\s+itinerary\b",
        r"\bcomplete\s+itinerary\b",
        r"\bcomplete\s+plan\b",
        r"\bfull\s+itinerary\b",
        r"\block\s+(the\s+)?plan\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _looks_like_itinerary_payload(text: str) -> bool:
    lowered = text.lower()
    return (
        "<itinerary>" in lowered
        or "```json" in lowered
        or bool(re.search(r'"destination"\s*:', text))
        or bool(re.search(r'"days"\s*:', text))
    )


def _is_non_initial_stage(stage: str | None) -> bool:
    return stage in {"flights", "hotels", "attractions", "complete"}


def _should_attempt_itinerary_repair(
    text: str,
    *,
    parsed_stage: str | None,
    is_finalize_turn: bool,
) -> bool:
    if not text.strip():
        return False
    if is_finalize_turn:
        return True
    if _is_non_initial_stage(parsed_stage):
        return True
    return _looks_like_itinerary_payload(text)


def _pick_best_response_text(candidates: list[str]) -> str:
    best_text = ""
    best_score = -10_000

    for raw in candidates:
        text = (raw or "").strip()
        if not text:
            continue

        score = len(text) // 250
        if _extract_itinerary(text, log_on_failure=False):
            score += 10_000
        if _looks_like_itinerary_payload(text):
            score += 250
        if _extract_planning_stage(text):
            score += 120
        if "<think>" in text.lower():
            score -= 20
        if "[STEP:" in text:
            score -= 20

        if score > best_score:
            best_score = score
            best_text = text

    return best_text


def _infer_destination_hint(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = re.search(r"Destination:\s*([^\n]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" -*\t")

    for text in texts:
        if not text:
            continue
        match = re.search(r'"destination"\s*:\s*"([^"]+)"', text)
        if match:
            return match.group(1).strip()

    return "Your Destination"


def _infer_currency_hint(*texts: str) -> str:
    joined = "\n".join(t for t in texts if t)
    if re.search(r"\bINR\b|₹|\binr\b", joined, flags=re.IGNORECASE):
        return "INR"
    if re.search(r"\bEUR\b|€|\beur\b", joined, flags=re.IGNORECASE):
        return "EUR"
    if re.search(r"\bGBP\b|£|\bgbp\b", joined, flags=re.IGNORECASE):
        return "GBP"
    if re.search(r"\bUSD\b|\$|\busd\b", joined, flags=re.IGNORECASE):
        return "USD"
    lowered = joined.lower()
    if "india" in lowered or any(
        city in lowered for city in ["pune", "delhi", "goa", "mumbai"]
    ):
        return "INR"
    return "USD"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clean_stage_value(stage: Any) -> str | None:
    if stage is None:
        return None
    value = str(stage).strip().lower()
    return value or None


def _normalize_expected_total_days(value: Any) -> int | None:
    normalized = _safe_int(value, 0)
    return normalized if normalized > 0 else None


def _build_panel_state(
    *,
    itinerary_data: dict[str, Any],
    panel_state: dict[str, Any] | None = None,
    stage: str | None = None,
    expected_total_days: int | None = None,
    source: str = "unknown",
    status: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    incoming = panel_state if isinstance(panel_state, dict) else {}
    actual_days = _itinerary_day_count(itinerary_data)

    expected = _normalize_expected_total_days(expected_total_days)
    if expected is None:
        expected = _normalize_expected_total_days(incoming.get("expected_total_days"))
    if expected is None:
        expected = _normalize_expected_total_days(itinerary_data.get("total_days"))

    if expected is not None:
        is_partial = actual_days < expected
        completion_ratio = round(actual_days / expected, 3) if expected > 0 else 0.0
    else:
        is_partial = False
        completion_ratio = 1.0 if actual_days > 0 else 0.0

    raw_status = (
        str(
            incoming.get("status")
            or status
            or ("partial" if is_partial else "complete")
        )
        .strip()
        .lower()
    )
    if raw_status not in {"captured", "partial", "complete", "failed"}:
        raw_status = "partial" if is_partial else "complete"

    normalized_stage = _clean_stage_value(stage) or _clean_stage_value(
        incoming.get("stage")
    )

    note = (
        str(message).strip()
        if isinstance(message, str)
        else str(incoming.get("message") or "").strip()
    )

    payload: dict[str, Any] = {
        "status": raw_status,
        "stage": normalized_stage,
        "expected_total_days": expected,
        "actual_days": actual_days,
        "completion_ratio": completion_ratio,
        "is_partial": is_partial,
        "source": str(incoming.get("source") or source).strip() or source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if note:
        payload["message"] = note
    return payload


def _inject_panel_state(
    itinerary_data: dict[str, Any],
    *,
    stage: str | None,
    expected_total_days: int | None,
    source: str,
    status: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    snapshot = dict(itinerary_data)
    snapshot["panel_state"] = _build_panel_state(
        itinerary_data=snapshot,
        panel_state=snapshot.get("panel_state")
        if isinstance(snapshot.get("panel_state"), dict)
        else None,
        stage=stage,
        expected_total_days=expected_total_days,
        source=source,
        status=status,
        message=message,
    )
    return snapshot


def _destination_center(destination: str) -> tuple[float, float]:
    lowered = destination.lower()
    for key, coords in _DESTINATION_COORDS.items():
        if key in lowered:
            return coords
    return (20.5937, 78.9629)


def _infer_airline(*texts: str) -> str:
    joined = "\n".join(t for t in texts if t).lower()
    for airline in _AIRLINES:
        if airline.lower() in joined:
            return airline
    return "IndiGo"


def _infer_iata_from_city(city_or_text: str, fallback: str) -> str:
    lowered = city_or_text.lower()
    iata_match = re.search(r"\b([A-Z]{3})\b", city_or_text)
    if iata_match:
        return iata_match.group(1)
    for city, code in _CITY_TO_IATA.items():
        if city in lowered:
            return code
    return fallback


def _normalize_time(value: Any, fallback_hour: int) -> str:
    text = str(value or "").strip()
    match = re.search(r"\b([0-2]?\d:[0-5]\d)\b", text)
    if match:
        return match.group(1)
    safe_hour = min(max(fallback_hour, 0), 23)
    return f"{safe_hour:02d}:00"


def _normalize_activity(
    activity: dict[str, Any],
    *,
    destination: str,
    currency: str,
    base_lat: float,
    base_lon: float,
    day_index: int,
    activity_index: int,
) -> tuple[dict[str, Any], bool]:
    title = str(activity.get("title") or f"Experience {activity_index + 1}").strip()
    description = str(
        activity.get("description")
        or f"Enjoy {title.lower()} and keep buffer time for transfers."
    ).strip()
    location = str(activity.get("location") or destination).strip()
    lat = _safe_float(activity.get("lat"))
    lon = _safe_float(activity.get("lon"))

    approximate_pin = False
    if not lat or not lon:
        lat = base_lat + (day_index * 0.03) + (activity_index * 0.007)
        lon = base_lon + (day_index * 0.03) + (activity_index * 0.006)
        approximate_pin = True

    category = str(activity.get("category") or "").strip().lower()
    if category not in {
        "culture",
        "food",
        "nature",
        "transport",
        "accommodation",
        "shopping",
        "nightlife",
    }:
        title_lower = title.lower()
        if any(
            k in title_lower for k in ["flight", "airport", "train", "cab", "transfer"]
        ):
            category = "transport"
        elif any(k in title_lower for k in ["hotel", "check-in", "resort"]):
            category = "accommodation"
        elif any(
            k in title_lower
            for k in ["lunch", "dinner", "breakfast", "cafe", "restaurant"]
        ):
            category = "food"
        elif any(k in title_lower for k in ["beach", "park", "sunset", "trail"]):
            category = "nature"
        else:
            category = "culture"

    duration_mins = _safe_int(activity.get("duration_mins"), 0)
    if duration_mins <= 0:
        duration_hours = _safe_float(activity.get("duration_hours"))
        duration_mins = int(duration_hours * 60) if duration_hours else 90

    ticket = activity.get("ticket") if isinstance(activity.get("ticket"), dict) else {}
    transit = (
        activity.get("transit_from_prev")
        if isinstance(activity.get("transit_from_prev"), dict)
        else {}
    )

    normalized: dict[str, Any] = {
        "time": _normalize_time(activity.get("time"), 7 + (activity_index * 2)),
        "duration_mins": max(duration_mins, 30),
        "title": title,
        "description": description,
        "location": location,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "category": category,
        "ticket": {
            "cost": _safe_float(ticket.get("cost")),
            "currency": ticket.get("currency") or currency,
            "as_of": ticket.get("as_of") or str(datetime.now(timezone.utc).year),
            "booking_url": ticket.get("booking_url"),
            "advance_booking_required": bool(
                ticket.get("advance_booking_required", False)
            ),
            "booking_lead_time": ticket.get("booking_lead_time"),
        },
        "opening_hours": activity.get("opening_hours"),
        "transit_from_prev": {
            "mode": transit.get("mode"),
            "duration_mins": _safe_int(transit.get("duration_mins"), 0) or None,
            "cost": _safe_float(transit.get("cost")),
            "currency": transit.get("currency") or currency,
            "notes": transit.get("notes"),
        }
        if transit
        else None,
        "weather_tip": activity.get("weather_tip"),
        "buffer_after_mins": max(_safe_int(activity.get("buffer_after_mins"), 30), 20),
    }

    return normalized, approximate_pin


def _extract_hotel_name(days: list[dict[str, Any]]) -> str | None:
    hotel_pattern = re.compile(
        r"([A-Z][A-Za-z0-9&'\- ]{2,}(?:Hotel|Resort|Suites|Inn|Palace|Villa)[A-Za-z0-9&'\- ]*)"
    )
    for day in days:
        for act in day.get("activities", []):
            for candidate in [
                act.get("title"),
                act.get("description"),
                act.get("location"),
            ]:
                if not candidate:
                    continue
                match = hotel_pattern.search(str(candidate))
                if match:
                    return match.group(1).strip()
    return None


def _extract_route_codes(*texts: str) -> tuple[str | None, str | None]:
    for text in texts:
        if not text:
            continue
        match = re.search(r"\b([A-Z]{3})\s*(?:->|→|to)\s*([A-Z]{3})\b", text)
        if match:
            return match.group(1), match.group(2)
    return None, None


def _normalize_flight_leg(
    leg: Any,
    *,
    currency: str,
) -> dict[str, Any] | None:
    if not isinstance(leg, dict):
        return None

    raw_segments = leg.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None

    segments: list[dict[str, Any]] = []
    meaningful_segment_count = 0
    for seg in raw_segments:
        seg_dict = seg if isinstance(seg, dict) else {}
        normalized_segment = {
            "airline": seg_dict.get("airline") or _infer_airline(str(seg_dict)),
            "flight_number": seg_dict.get("flight_number"),
            "from_airport": seg_dict.get("from_airport") or "TBD",
            "from_terminal": seg_dict.get("from_terminal"),
            "to_airport": seg_dict.get("to_airport") or "TBD",
            "to_terminal": seg_dict.get("to_terminal"),
            "departure": seg_dict.get("departure"),
            "arrival": seg_dict.get("arrival"),
            "duration_mins": _safe_int(seg_dict.get("duration_mins"), 0) or None,
            "layover_transit_mins": _safe_int(seg_dict.get("layover_transit_mins"), 0)
            or None,
        }
        if (
            normalized_segment["from_airport"] != "TBD"
            and normalized_segment["to_airport"] != "TBD"
        ):
            meaningful_segment_count += 1
        segments.append(normalized_segment)

    price_per_person = _safe_float(leg.get("price_per_person"))
    if price_per_person is None:
        price_per_person = _safe_float(leg.get("price_per_person_inr"))
    if price_per_person is None:
        total_for_two = _safe_float(
            leg.get("total_for_two") or leg.get("total_for_two_inr")
        )
        if total_for_two is not None:
            price_per_person = round(total_for_two / 2, 2)

    leg_currency = str(leg.get("currency") or "").strip()
    if not leg_currency and (
        leg.get("price_per_person_inr") is not None
        or leg.get("total_for_two_inr") is not None
    ):
        leg_currency = "INR"

    if meaningful_segment_count == 0 and price_per_person is None:
        return None

    return {
        "segments": segments,
        "total_duration_mins": _safe_int(
            leg.get("total_duration_mins") or leg.get("total_duration"), 0
        )
        or None,
        "cabin_class": leg.get("cabin_class") or "economy",
        "price_per_person": price_per_person,
        "currency": leg_currency or currency,
    }


def _normalize_itinerary_for_ui(
    itinerary: dict[str, Any],
    *,
    destination_hint: str,
    context_text: str,
) -> dict[str, Any]:
    data = dict(itinerary) if isinstance(itinerary, dict) else {}
    destination = str(
        data.get("destination") or destination_hint or "Trip Destination"
    ).strip()
    currency = _infer_currency_hint(context_text, destination)
    base_lat, base_lon = _destination_center(destination)

    raw_days = data.get("days") if isinstance(data.get("days"), list) else []
    days: list[dict[str, Any]] = []
    approximate_pin_used = False

    for day_index, raw_day in enumerate(raw_days):
        day = raw_day if isinstance(raw_day, dict) else {}
        raw_activities = (
            day.get("activities") if isinstance(day.get("activities"), list) else []
        )
        activities: list[dict[str, Any]] = []
        for activity_index, raw_activity in enumerate(raw_activities):
            act = raw_activity if isinstance(raw_activity, dict) else {}
            normalized_act, approximate = _normalize_activity(
                act,
                destination=destination,
                currency=currency,
                base_lat=base_lat,
                base_lon=base_lon,
                day_index=day_index,
                activity_index=activity_index,
            )
            approximate_pin_used = approximate_pin_used or approximate
            activities.append(normalized_act)

        if not activities:
            fallback_activity, _ = _normalize_activity(
                {
                    "time": "10:00",
                    "title": f"Explore {destination}",
                    "description": "A curated city exploration block while final details are refreshed.",
                    "location": destination,
                    "category": "culture",
                    "duration_mins": 120,
                    "buffer_after_mins": 30,
                },
                destination=destination,
                currency=currency,
                base_lat=base_lat,
                base_lon=base_lon,
                day_index=day_index,
                activity_index=0,
            )
            activities = [fallback_activity]
            approximate_pin_used = True

        day_number = _safe_int(day.get("day"), day_index + 1)
        day_title = (
            str(day.get("title") or "").strip() or f"Day {day_number} Highlights"
        )
        day_notes = (
            str(day.get("day_notes") or "").strip()
            or "Keep hydration and transfer buffers in mind."
        )
        days.append(
            {
                "day": day_number,
                "date": day.get("date"),
                "title": day_title,
                "day_notes": day_notes,
                "activities": activities,
            }
        )

    if not days:
        day1_activity, _ = _normalize_activity(
            {
                "time": "09:30",
                "title": f"Arrival and orientation in {destination}",
                "description": "Transit, check-in, and a light orientation walk to settle in.",
                "location": destination,
                "category": "transport",
                "duration_mins": 150,
                "buffer_after_mins": 30,
            },
            destination=destination,
            currency=currency,
            base_lat=base_lat,
            base_lon=base_lon,
            day_index=0,
            activity_index=0,
        )
        days = [
            {
                "day": 1,
                "date": datetime.now(timezone.utc).date().isoformat(),
                "title": "Arrival Day",
                "day_notes": "Final detailed schedule is being refreshed from your confirmed preferences.",
                "activities": [day1_activity],
            }
        ]
        approximate_pin_used = True

    total_days = _safe_int(data.get("total_days"), len(days))
    if total_days <= 0:
        total_days = len(days)

    raw_hotel = data.get("hotel") if isinstance(data.get("hotel"), dict) else None
    if raw_hotel:
        hotel = {
            "name": raw_hotel.get("name")
            or _extract_hotel_name(days)
            or f"Recommended stay in {destination}",
            "stars": _safe_float(raw_hotel.get("stars")) or 4,
            "address": raw_hotel.get("address") or destination,
            "lat": _safe_float(raw_hotel.get("lat")) or round(base_lat + 0.015, 6),
            "lon": _safe_float(raw_hotel.get("lon")) or round(base_lon + 0.015, 6),
            "price_per_night": _safe_float(raw_hotel.get("price_per_night")),
            "currency": raw_hotel.get("currency") or currency,
            "loyalty_program": raw_hotel.get("loyalty_program"),
            "booking_notes": raw_hotel.get("booking_notes")
            or "Free cancellation policies vary by season; verify before payment.",
        }
    else:
        hotel = {
            "name": _extract_hotel_name(days) or f"Recommended stay in {destination}",
            "stars": 4,
            "address": destination,
            "lat": round(base_lat + 0.015, 6),
            "lon": round(base_lon + 0.015, 6),
            "price_per_night": None,
            "currency": currency,
            "loyalty_program": None,
            "booking_notes": "Shortlisted hotel details are being refreshed from live inventory.",
        }
        approximate_pin_used = True

    raw_flights = data.get("flights") if isinstance(data.get("flights"), dict) else {}
    outbound = _normalize_flight_leg(raw_flights.get("outbound"), currency=currency)
    return_leg = _normalize_flight_leg(raw_flights.get("return"), currency=currency)
    flights = (
        {"outbound": outbound, "return": return_leg} if outbound or return_leg else None
    )

    seasonal_warnings = (
        data.get("seasonal_warnings")
        if isinstance(data.get("seasonal_warnings"), list)
        else []
    )
    seasonal_warnings = [
        str(item).strip() for item in seasonal_warnings if str(item).strip()
    ]
    if len(seasonal_warnings) < 2:
        seasonal_warnings.extend(
            [
                "Start outdoor activities early to avoid midday heat and traffic spikes.",
                "Keep a hydration buffer and backup indoor option for one block each day.",
            ]
        )
    seasonal_warnings = seasonal_warnings[:4]

    tips = data.get("tips") if isinstance(data.get("tips"), list) else []
    tips = [str(item).strip() for item in tips if str(item).strip()]
    if approximate_pin_used:
        tips.append(
            "Some map pins are city-center approximations until precise geocodes are confirmed."
        )
    if len(tips) < 3:
        tips.extend(
            [
                "Confirm opening hours and ticket windows one day before each activity.",
                "Keep digital and offline copies of booking confirmations.",
                "Reserve airport/city transfers in advance during peak hours.",
            ]
        )
    tips = tips[:6]

    weather_summary = (
        str(data.get("weather_summary") or "").strip()
        or "Expect variable daytime conditions; carry hydration and sun protection."
    )
    best_season = (
        str(data.get("best_season") or "").strip()
        or "October-March usually offers the most comfortable weather window."
    )

    estimated_budget = (
        data.get("estimated_budget")
        if isinstance(data.get("estimated_budget"), dict)
        else {}
    )
    flights_total = _safe_float(estimated_budget.get("flights_total"))
    if flights_total is None:
        flights_total = _safe_float(estimated_budget.get("flights_total_inr"))

    accommodation_total = _safe_float(estimated_budget.get("accommodation_total"))
    if accommodation_total is None:
        accommodation_total = _safe_float(
            estimated_budget.get("accommodation_total_inr")
        )

    activities_total = _safe_float(estimated_budget.get("activities_total"))
    if activities_total is None:
        activities_total = _safe_float(estimated_budget.get("activities_total_inr"))

    food_per_day = _safe_float(estimated_budget.get("food_per_day"))
    if food_per_day is None:
        food_extra = _safe_float(estimated_budget.get("food_extra_inr"))
        if food_extra is not None and total_days > 0:
            food_per_day = round(food_extra / max(total_days, 1), 2)

    local_transport_per_day = _safe_float(
        estimated_budget.get("local_transport_per_day")
    )
    if local_transport_per_day is None:
        local_transport_total = _safe_float(estimated_budget.get("local_transport_inr"))
        if local_transport_total is not None and total_days > 0:
            local_transport_per_day = round(
                local_transport_total / max(total_days, 1), 2
            )

    if flights_total is None:
        outbound_price = (
            _safe_float(flights.get("outbound", {}).get("price_per_person"))
            if isinstance(flights, dict) and isinstance(flights.get("outbound"), dict)
            else None
        )
        flights_total = outbound_price
    if accommodation_total is None:
        nightly = _safe_float(hotel.get("price_per_night"))
        if nightly is not None:
            accommodation_total = nightly * max(total_days - 1, 1)
    if activities_total is None:
        ticket_costs = []
        for day in days:
            for activity in day.get("activities", []):
                ticket = (
                    activity.get("ticket")
                    if isinstance(activity.get("ticket"), dict)
                    else {}
                )
                cost = _safe_float(ticket.get("cost"))
                if cost is not None:
                    ticket_costs.append(cost)
        activities_total = sum(ticket_costs) if ticket_costs else None
    if food_per_day is None:
        food_per_day = 1800.0 if currency == "INR" else 45.0
    if local_transport_per_day is None:
        local_transport_per_day = 900.0 if currency == "INR" else 18.0

    total_estimate = _safe_float(estimated_budget.get("total_estimate"))
    if total_estimate is None:
        total_estimate = _safe_float(estimated_budget.get("total_estimate_inr"))
    if total_estimate is None:
        total_estimate = _safe_float(
            estimated_budget.get("total_estimate_with_savings_inr")
        )
    if total_estimate is None:
        total_estimate = (
            (flights_total or 0)
            + (accommodation_total or 0)
            + (activities_total or 0)
            + (food_per_day or 0) * max(total_days, 1)
            + (local_transport_per_day or 0) * max(total_days, 1)
        )

    budget_currency = str(estimated_budget.get("currency") or "").strip()
    if not budget_currency and any(
        estimated_budget.get(key) is not None
        for key in [
            "flights_total_inr",
            "accommodation_total_inr",
            "activities_total_inr",
            "food_extra_inr",
            "local_transport_inr",
            "total_estimate_inr",
            "total_estimate_with_savings_inr",
        ]
    ):
        budget_currency = "INR"

    panel_state = _build_panel_state(
        itinerary_data={"days": days, "total_days": total_days},
        panel_state=data.get("panel_state")
        if isinstance(data.get("panel_state"), dict)
        else None,
        source="normalized_itinerary",
    )

    normalized = {
        "destination": destination,
        "total_days": max(total_days, 1),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "weather_summary": weather_summary,
        "best_season": best_season,
        "seasonal_warnings": seasonal_warnings,
        "flights": flights,
        "hotel": hotel,
        "days": days,
        "panel_state": panel_state,
        "tips": tips,
        "estimated_budget": {
            "currency": budget_currency or currency,
            "flights_total": flights_total,
            "accommodation_total": accommodation_total,
            "activities_total": activities_total,
            "food_per_day": food_per_day,
            "local_transport_per_day": local_transport_per_day,
            "total_estimate": total_estimate,
            "flights_total_inr": _safe_float(estimated_budget.get("flights_total_inr")),
            "accommodation_total_inr": _safe_float(
                estimated_budget.get("accommodation_total_inr")
            ),
            "activities_total_inr": _safe_float(
                estimated_budget.get("activities_total_inr")
            ),
            "food_extra_inr": _safe_float(estimated_budget.get("food_extra_inr")),
            "local_transport_inr": _safe_float(
                estimated_budget.get("local_transport_inr")
            ),
            "total_estimate_inr": _safe_float(
                estimated_budget.get("total_estimate_inr")
            ),
            "total_estimate_with_savings_inr": _safe_float(
                estimated_budget.get("total_estimate_with_savings_inr")
            ),
            "accommodation_per_night": _safe_float(
                estimated_budget.get("accommodation_per_night")
            )
            or _safe_float(hotel.get("price_per_night")),
        },
    }
    return normalized


def _build_minimal_itinerary(destination: str) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    skeleton = {
        "destination": destination,
        "total_days": 1,
        "start_date": today,
        "end_date": today,
        "weather_summary": "Detailed weather and operational notes are being finalized.",
        "best_season": "October-March generally offers the most comfortable conditions.",
        "seasonal_warnings": [],
        "flights": {"outbound": None, "return": None},
        "hotel": None,
        "days": [
            {
                "day": 1,
                "date": today,
                "title": "Draft Itinerary",
                "day_notes": "Auto-saved structured fallback while final itinerary enrichment is retried.",
                "activities": [
                    {
                        "time": "10:00",
                        "duration_mins": 120,
                        "title": "Finalize itinerary details",
                        "description": "Core trip data was captured, and this draft keeps your itinerary panel populated while full enrichment recovers.",
                        "location": destination,
                        "lat": 0,
                        "lon": 0,
                        "category": "transport",
                        "ticket": None,
                        "opening_hours": None,
                        "transit_from_prev": None,
                        "weather_tip": None,
                        "buffer_after_mins": 30,
                    }
                ],
            }
        ],
        "tips": [
            "Retry finalize once to replace this draft with the full enriched itinerary."
        ],
        "estimated_budget": {"currency": "INR", "total_estimate": None},
    }
    return _normalize_itinerary_for_ui(
        skeleton,
        destination_hint=destination,
        context_text=destination,
    )


async def _repair_itinerary_with_llm(
    source_text: str,
    history: list[dict[str, Any]],
    user_message: str,
    dynamic_context: str,
) -> dict[str, Any] | None:
    """Best-effort recovery pass when primary itinerary extraction fails."""
    if not source_text.strip():
        return None

    history_tail = history[-8:]
    history_blob = "\n".join(
        f"{m.get('role', 'unknown')}: {str(m.get('content', ''))[:1000]}"
        for m in history_tail
    )
    compact_context = dynamic_context[:2500]
    compact_source = source_text[:8000]

    repair_prompt = (
        "You are a strict JSON formatter for a travel app. "
        "Reconstruct ONE valid itinerary JSON object only (no markdown, no xml, no comments, no backticks). "
        "You MUST include these top-level keys: destination, total_days, start_date, end_date, weather_summary, "
        "best_season, seasonal_warnings, flights, hotel, days, tips, estimated_budget. "
        "At least 1 day with at least 3 activities. "
        "Each activity must include time, duration_mins, title, description, location, lat, lon, category, "
        "ticket, opening_hours, transit_from_prev, weather_tip, buffer_after_mins. "
        "Use numeric lat/lon values (city-center approximation is allowed if exact geocode is missing)."
    )

    llm = _build_llm(streaming=False)
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=repair_prompt),
                HumanMessage(
                    content=(
                        f"User finalize request: {user_message}\n\n"
                        f"Dynamic context:\n{compact_context}\n\n"
                        f"Recent history:\n{history_blob}\n\n"
                        f"Source response to repair:\n{compact_source}"
                    )
                ),
            ]
        )
        repaired_text = _message_content_to_text(getattr(response, "content", ""))
        return _extract_itinerary(repaired_text, log_on_failure=False)
    except Exception as exc:
        logger.warning("Itinerary repair pass failed", error=str(exc))
        return None


async def _recover_itinerary_snapshot(
    *,
    source_text: str,
    history: list[dict[str, Any]],
    user_message: str,
    dynamic_context: str,
    parsed_stage: str | None,
    is_finalize_turn: bool,
    allow_minimal_fallback: bool,
) -> dict[str, Any] | None:
    parsed = _extract_itinerary(source_text, log_on_failure=False)
    if parsed:
        return parsed

    if _should_attempt_itinerary_repair(
        source_text,
        parsed_stage=parsed_stage,
        is_finalize_turn=is_finalize_turn,
    ):
        repaired = await _repair_itinerary_with_llm(
            source_text=source_text,
            history=history,
            user_message=user_message,
            dynamic_context=dynamic_context,
        )
        if repaired:
            return repaired

    if allow_minimal_fallback and (is_finalize_turn or parsed_stage == "complete"):
        inferred_destination = _infer_destination_hint(
            dynamic_context,
            source_text,
            user_message,
        )
        return _build_minimal_itinerary(inferred_destination)

    return None


def _build_llm(streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=streaming,
        max_tokens=20000,  # Ensure enough space for full itineraries
    )


def _build_agent_executor(dynamic_prompt: str = ""):
    llm = _build_llm()
    final_prompt = MAIN_SYSTEM_PROMPT
    if dynamic_prompt:
        final_prompt += f"\n\n{dynamic_prompt}"
    return create_react_agent(model=llm, tools=AGENT_TOOLS, prompt=final_prompt)


def _messages_to_langchain(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    result = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result


def _find_agent_tool(tool_name: str):
    for tool in AGENT_TOOLS:
        if getattr(tool, "name", "") == tool_name:
            return tool
    return None


async def _build_enforced_preflight_context(
    *,
    user_message: str,
    dynamic_context: str,
    stage: str | None,
) -> str:
    """Force temporal grounding and inject clearly marked KB reference snippets."""

    def _redact_user_specific_rag_lines(text: str) -> str:
        """Remove likely user-profile lines from retrieved KB snippets.

        This keeps destination facts while reducing accidental carry-over of
        traveler-specific values (party size, budgets, exact travel dates).
        """
        if not text:
            return text

        sensitive_patterns = [
            re.compile(r"\b\d+\s*(adults?|children|kids|people|pax|persons?)\b", re.I),
            re.compile(r"\bgroup\s*size\b", re.I),
            re.compile(r"\b(budget|per\s*person|per-person|total\s*cost)\b", re.I),
            re.compile(r"\b(?:inr|usd|eur|gbp)\s*\d|\d+\s*(?:inr|usd|eur|gbp)\b", re.I),
            re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
            re.compile(
                r"\b(check[- ]?in|check[- ]?out|departure|return)\s*[:=-]", re.I
            ),
        ]

        redacted_lines: list[str] = []
        for line in text.splitlines():
            if any(pattern.search(line) for pattern in sensitive_patterns):
                redacted_lines.append(
                    "[RAG line redacted: possible user-specific detail]"
                )
            else:
                redacted_lines.append(line)
        return "\n".join(redacted_lines)

    sections: list[str] = []

    time_tool = _find_agent_tool("get_current_time")
    if time_tool is not None:
        try:
            current_time = await time_tool.ainvoke({})
            if isinstance(current_time, str) and current_time.strip():
                sections.append(
                    f"## Enforced Current Time (authoritative)\n{current_time.strip()}"
                )
        except Exception as exc:
            logger.warning("Preflight current-time tool failed", error=str(exc))

    rag_tool = _find_agent_tool("rag_travel_knowledge")
    if rag_tool is not None:
        rag_query = (
            f"Planning stage: {stage or 'unknown'}\n"
            f"User request: {user_message[:1200]}\n"
            f"Existing context: {dynamic_context[:1800]}"
        )
        try:
            kb_context = await rag_tool.ainvoke({"query": rag_query})
            if isinstance(kb_context, str):
                cleaned = kb_context.strip()
                if cleaned and "no knowledge base entries found" not in cleaned.lower():
                    cleaned = _redact_user_specific_rag_lines(cleaned)
                    sections.append(
                        "## RAG Reference Context (non-authoritative)\n"
                        "```md\n"
                        "Use for destination facts only.\n"
                        "Do NOT treat any user-specific values in this block as confirmed unless the user stated them in this chat.\n"
                        "If budget/group size/dates/origin/preferences are missing, ask follow-up questions instead of assuming.\n"
                        "```\n\n"
                        f"{cleaned[:4000]}"
                    )
        except Exception as exc:
            logger.warning("Preflight RAG tool failed", error=str(exc))

    return "\n\n".join(sections)


def _tool_output_to_text(output: Any) -> str:
    if hasattr(output, "content"):
        return _message_content_to_text(getattr(output, "content"))
    if isinstance(output, str):
        return output
    return str(output or "")


def _extract_itinerary_tool_snapshot(
    tool_input: Any,
) -> tuple[dict[str, Any] | None, str | None, int | None]:
    payload: Any = tool_input

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None, None, None

    if not isinstance(payload, dict):
        return None, None, None

    for nested_key in ("kwargs", "args", "input", "tool_input"):
        nested_payload = payload.get(nested_key)
        if isinstance(nested_payload, dict):
            payload = nested_payload
            break
        if isinstance(nested_payload, str):
            try:
                parsed_nested = json.loads(nested_payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed_nested, dict):
                payload = parsed_nested
                break

    itinerary_data: dict[str, Any] | None = None
    if isinstance(payload.get("itinerary_data"), dict):
        itinerary_data = payload["itinerary_data"]
    elif isinstance(payload.get("itinerary"), dict):
        itinerary_data = payload["itinerary"]
    elif "days" in payload and "destination" in payload:
        itinerary_data = payload

    if itinerary_data is None:
        return None, None, None

    stage = _clean_stage_value(payload.get("stage"))
    expected_total_days = _normalize_expected_total_days(
        payload.get("expected_total_days")
    )
    if expected_total_days is None:
        expected_total_days = _normalize_expected_total_days(
            itinerary_data.get("total_days")
        )

    return itinerary_data, stage, expected_total_days


def _classify_tool_output(tool_name: str, output_text: str) -> str:
    stripped = output_text.strip()
    if not stripped:
        return "empty"

    lowered = stripped.lower()
    error_markers = [
        "unavailable",
        "technical issue",
        "[search_error:",
        "could not geocode",
        "knowledge base unavailable",
    ]
    empty_markers = [
        "no results found",
        "no knowledge base entries found",
        "could not find location",
    ]
    fallback_markers = [
        "fallback",
        "continue with web search",
        "use your training knowledge instead",
        "verify on booking site before purchase",
        "requires_user_verification",
    ]

    if any(marker in lowered for marker in error_markers):
        return "error"
    if any(marker in lowered for marker in empty_markers):
        return "empty"
    if any(marker in lowered for marker in fallback_markers):
        return "fallback"

    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            source_layer = parsed.get("source_layer")
            if isinstance(source_layer, str) and source_layer:
                if source_layer in {"no_live_data", "model_prior"}:
                    return "fallback"
                return source_layer
        except json.JSONDecodeError:
            pass

    if tool_name == "geocode_place" and "source: nominatim" in lowered:
        return "fallback"

    return "ok"


def _extract_itinerary(text: str, log_on_failure: bool = True) -> dict | None:
    candidates: list[str] = []

    text_wo_think = re.sub(
        r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE
    )

    match = re.search(r"<itinerary>(.*?)</itinerary>", text_wo_think, re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    fenced_json_matches = re.findall(
        r"```(?:json)?\s*([\s\S]*?)```", text_wo_think, flags=re.IGNORECASE
    )
    candidates.extend(candidate.strip() for candidate in fenced_json_matches)
    candidates.append(text_wo_think.strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        if not candidate:
            continue

        parsed: Any | None = None
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            pass

        if parsed is None:
            for idx, ch in enumerate(candidate):
                if ch != "{":
                    continue
                try:
                    parsed_obj, _ = decoder.raw_decode(candidate[idx:])
                    parsed = parsed_obj
                    break
                except json.JSONDecodeError:
                    continue

        if parsed is None:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end > start:
                maybe_obj = candidate[start : end + 1]
                try:
                    parsed = ast.literal_eval(maybe_obj)
                except (ValueError, SyntaxError):
                    parsed = None

        if parsed is None:
            continue

        if isinstance(parsed, dict):
            if isinstance(parsed.get("itinerary_data"), dict):
                return parsed["itinerary_data"]
            if "days" in parsed and "destination" in parsed:
                return parsed

    if log_on_failure:
        logger.warning("Failed to parse itinerary JSON", preview=text[:200])
    return None


def _extract_planning_stage(text: str) -> str | None:
    """Extract planning stage from <planning_stage> block.

    Tries to find a closed block first, then falls back to an unclosed block
    at the end of the text (in case of truncation).
    """
    closed_match = re.search(r"<planning_stage>(.*?)</planning_stage>", text, re.DOTALL)
    if closed_match:
        return closed_match.group(1).strip()

    # Fallback for truncated response
    unclosed_match = re.search(r"<planning_stage>([a-z_]+)$", text.strip())
    if unclosed_match:
        return unclosed_match.group(1).strip()

    return None


def _strip_agent_tags(text: str) -> str:
    """Remove purely structural tags (itinerary, stage) for storage.
    Note: We KEEP <think> tags because the UI uses them to render the Thought Process accordion.
    """
    # Closed tags
    text = re.sub(r"<itinerary>.*?</itinerary>", "", text, flags=re.DOTALL)
    text = re.sub(r"<planning_stage>.*?</planning_stage>", "", text, flags=re.DOTALL)
    # Unclosed tags (at end of response due to truncation)
    text = re.sub(r"<itinerary>.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"<planning_stage>.*$", "", text, flags=re.DOTALL)
    return text.strip()


def _response_contains_sensitive_fact_claims(text: str) -> bool:
    lowered = text.lower()
    patterns = [
        r"\blanguage\b",
        r"\bspoken\b",
        r"\bprefer(?:red)?\b",
        r"\bcommonly used\b",
        r"\bneighbou?rhood\b",
        r"\bbest area\b",
        r"\bideal area\b",
        r"\betiquette\b",
        r"\bcustoms?\b",
        r"\bopening hours?\b",
        r"\bclosed on\b",
        r"\bentry fee\b",
        r"\bticket fee\b",
        r"\boperational\b",
        r"\bseasonal\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _apply_fact_grounding_notice_if_needed(
    text: str, *, grounding_tools_used: set[str]
) -> str:
    """Add a narrow caution note when sensitive facts were stated without grounding tools."""
    if not text.strip():
        return text

    if not _response_contains_sensitive_fact_claims(text):
        return text

    if grounding_tools_used.intersection(
        {"rag_travel_knowledge", "search_web", "get_place_details", "get_weather"}
    ):
        return text

    notice = (
        "\n\nNote: destination language, cultural norms, neighborhood suitability, "
        "fees, and operating details should be treated as preliminary here unless "
        "explicitly verified from retrieved knowledge or live sources."
    )
    if notice.strip() in text:
        return text
    return text.rstrip() + notice


def _itinerary_signature(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _itinerary_day_count(data: dict[str, Any] | None) -> int:
    if not isinstance(data, dict):
        return 0
    days = data.get("days")
    if not isinstance(days, list):
        return 0
    return len([day for day in days if isinstance(day, dict)])


def _itinerary_activity_count(data: dict[str, Any] | None) -> int:
    if not isinstance(data, dict):
        return 0
    days = data.get("days")
    if not isinstance(days, list):
        return 0

    total = 0
    for day in days:
        if not isinstance(day, dict):
            continue
        activities = day.get("activities")
        if isinstance(activities, list):
            total += len(
                [activity for activity in activities if isinstance(activity, dict)]
            )
    return total


def _info_score(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, dict):
        return sum(_info_score(v) for v in value.values())
    if isinstance(value, list):
        return sum(_info_score(v) for v in value)
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 1


def _is_placeholder_hotel(hotel: Any) -> bool:
    if not isinstance(hotel, dict):
        return True
    name = str(hotel.get("name") or "").strip().lower()
    notes = str(hotel.get("booking_notes") or "").strip().lower()
    price = _safe_float(hotel.get("price_per_night"))
    loyalty = str(hotel.get("loyalty_program") or "").strip()
    has_specific_name = bool(name) and not name.startswith("recommended stay in")
    has_specific_details = price is not None or bool(loyalty)
    is_refresh_note = "being refreshed" in notes
    return not has_specific_name and not has_specific_details and is_refresh_note


def _is_placeholder_flights(flights: Any) -> bool:
    if not isinstance(flights, dict):
        return True
    outbound = flights.get("outbound")
    if not isinstance(outbound, dict):
        return True
    segments = outbound.get("segments")
    if not isinstance(segments, list) or not segments:
        return True

    meaningful_segments = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        from_airport = str(segment.get("from_airport") or "").strip().upper()
        to_airport = str(segment.get("to_airport") or "").strip().upper()
        has_route = from_airport not in {"", "TBD"} and to_airport not in {"", "TBD"}
        has_timing = any(
            segment.get(key) for key in ["departure", "arrival", "duration_mins"]
        )
        if has_route and has_timing:
            meaningful_segments += 1

    price = _safe_float(outbound.get("price_per_person"))
    return meaningful_segments == 0 and price is None


def _is_placeholder_activity(activity: Any, *, destination: str) -> bool:
    if not isinstance(activity, dict):
        return True
    title = str(activity.get("title") or "").strip().lower()
    description = str(activity.get("description") or "").strip().lower()
    location = str(activity.get("location") or "").strip().lower()

    generic_titles = {
        f"explore {destination.lower()}",
        f"arrival and orientation in {destination.lower()}",
        "finalize itinerary details",
    }
    if title in generic_titles:
        return True
    if (
        "curated city exploration block while final details are refreshed"
        in description
    ):
        return True
    if "draft keeps your itinerary panel populated" in description:
        return True
    if location == destination.lower() and not any(
        activity.get(key)
        for key in ["opening_hours", "weather_tip", "transit_from_prev"]
    ):
        ticket = activity.get("ticket")
        if not isinstance(ticket, dict) or _safe_float(ticket.get("cost")) is None:
            return True
    return False


def _merge_activities(
    existing_activities: list[dict[str, Any]],
    incoming_activities: list[dict[str, Any]],
    *,
    destination: str,
) -> list[dict[str, Any]]:
    existing_meaningful = [
        activity
        for activity in existing_activities
        if not _is_placeholder_activity(activity, destination=destination)
    ]
    incoming_meaningful = [
        activity
        for activity in incoming_activities
        if not _is_placeholder_activity(activity, destination=destination)
    ]

    if not incoming_meaningful and existing_activities:
        return existing_activities
    if len(incoming_meaningful) < len(existing_meaningful):
        return existing_activities
    if _info_score(incoming_activities) < _info_score(existing_activities):
        return existing_activities
    return incoming_activities or existing_activities


def _merge_day(
    previous: dict[str, Any], incoming: dict[str, Any], *, destination: str
) -> dict[str, Any]:
    merged = dict(previous)

    for key in ["day", "date"]:
        incoming_value = incoming.get(key)
        if incoming_value not in (None, ""):
            merged[key] = incoming_value

    incoming_title = str(incoming.get("title") or "").strip()
    incoming_notes = str(incoming.get("day_notes") or "").strip()
    if incoming_title and incoming_title not in {
        f"Day {merged.get('day', '')} Highlights".strip(),
        "Arrival Day",
        "Draft Itinerary",
    }:
        merged["title"] = incoming_title
    if (
        incoming_notes
        and "being refreshed from your confirmed preferences"
        not in incoming_notes.lower()
    ):
        merged["day_notes"] = incoming_notes

    existing_activities = (
        previous.get("activities")
        if isinstance(previous.get("activities"), list)
        else []
    )
    incoming_activities = (
        incoming.get("activities")
        if isinstance(incoming.get("activities"), list)
        else []
    )
    merged["activities"] = _merge_activities(
        [activity for activity in existing_activities if isinstance(activity, dict)],
        [activity for activity in incoming_activities if isinstance(activity, dict)],
        destination=destination,
    )
    return merged


def _merge_budget(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if isinstance(value, (int, float)):
            merged[key] = value
            continue
        if isinstance(value, str) and value.strip():
            merged[key] = value
            continue
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _merge_panel_state(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    merged_total_days: int,
    merged_actual_days: int,
) -> dict[str, Any]:
    merged = dict(existing)

    for key in ["stage", "source", "message"]:
        value = str(incoming.get(key) or "").strip()
        if value:
            merged[key] = value

    expected = _normalize_expected_total_days(incoming.get("expected_total_days"))
    if expected is None:
        expected = _normalize_expected_total_days(existing.get("expected_total_days"))
    if expected is None:
        expected = merged_total_days if merged_total_days > 0 else None

    incoming_actual = _safe_int(incoming.get("actual_days"), 0)
    existing_actual = _safe_int(existing.get("actual_days"), 0)
    actual_days = max(incoming_actual, existing_actual, merged_actual_days)

    if expected is not None:
        is_partial = actual_days < expected
        completion_ratio = round(actual_days / expected, 3) if expected > 0 else 0.0
    else:
        is_partial = False
        completion_ratio = 1.0 if actual_days > 0 else 0.0

    incoming_status = str(incoming.get("status") or "").strip().lower()
    existing_status = str(existing.get("status") or "").strip().lower()
    status = (
        incoming_status or existing_status or ("partial" if is_partial else "complete")
    )
    if status not in {"captured", "partial", "complete", "failed"}:
        status = "partial" if is_partial else "complete"

    merged.update(
        {
            "status": status,
            "expected_total_days": expected,
            "actual_days": actual_days,
            "completion_ratio": completion_ratio,
            "is_partial": is_partial,
            "updated_at": str(
                incoming.get("updated_at") or datetime.now(timezone.utc).isoformat()
            ),
        }
    )
    return merged


def _merge_days(
    existing_days: list[dict[str, Any]], incoming_days: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    day_map: dict[int, dict[str, Any]] = {}

    def _day_number(day: dict[str, Any], fallback: int) -> int:
        try:
            return int(day.get("day") or fallback)
        except (TypeError, ValueError):
            return fallback

    for idx, day in enumerate(existing_days):
        day_num = _day_number(day, idx + 1)
        day_map[day_num] = day

    for idx, day in enumerate(incoming_days):
        day_num = _day_number(day, idx + 1)
        previous = day_map.get(day_num)
        if previous is None:
            day_map[day_num] = day
            continue

        destination = str(
            day.get("destination") or previous.get("destination") or ""
        ).strip()
        day_map[day_num] = _merge_day(previous, day, destination=destination)

    merged_days = [day_map[num] for num in sorted(day_map.keys())]
    return merged_days


def _merge_itinerary_data(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge itinerary snapshots to avoid regressing newer/richer data during concurrent writes."""
    merged = dict(existing)

    simple_keys = [
        "destination",
        "start_date",
        "end_date",
        "weather_summary",
        "best_season",
    ]
    for key in simple_keys:
        value = incoming.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value

    incoming_flights = incoming.get("flights")
    existing_flights = existing.get("flights")
    if not _is_placeholder_flights(incoming_flights) or _is_placeholder_flights(
        existing_flights
    ):
        merged["flights"] = incoming_flights
    else:
        merged["flights"] = existing_flights

    incoming_hotel = incoming.get("hotel")
    existing_hotel = existing.get("hotel")
    if not _is_placeholder_hotel(incoming_hotel) or _is_placeholder_hotel(
        existing_hotel
    ):
        merged["hotel"] = incoming_hotel
    else:
        merged["hotel"] = existing_hotel

    existing_days = (
        existing.get("days") if isinstance(existing.get("days"), list) else []
    )
    incoming_days = (
        incoming.get("days") if isinstance(incoming.get("days"), list) else []
    )
    destination = str(
        incoming.get("destination") or existing.get("destination") or ""
    ).strip()
    merged_days = _merge_days(
        [
            {**d, "destination": destination}
            for d in existing_days
            if isinstance(d, dict)
        ],
        [
            {**d, "destination": destination}
            for d in incoming_days
            if isinstance(d, dict)
        ],
    )
    if merged_days:
        merged["days"] = [
            {k: v for k, v in day.items() if k != "destination"} for day in merged_days
        ]

    try:
        existing_total_days = int(existing.get("total_days") or 0)
    except (TypeError, ValueError):
        existing_total_days = 0
    try:
        incoming_total_days = int(incoming.get("total_days") or 0)
    except (TypeError, ValueError):
        incoming_total_days = 0
    merged["total_days"] = max(
        existing_total_days, incoming_total_days, len(merged_days)
    )

    existing_panel_state = (
        existing.get("panel_state")
        if isinstance(existing.get("panel_state"), dict)
        else {}
    )
    incoming_panel_state = (
        incoming.get("panel_state")
        if isinstance(incoming.get("panel_state"), dict)
        else {}
    )
    if existing_panel_state or incoming_panel_state or merged_days:
        merged["panel_state"] = _merge_panel_state(
            existing_panel_state,
            incoming_panel_state,
            merged_total_days=merged["total_days"],
            merged_actual_days=len(merged_days),
        )

    # Keep union of tips and warnings.
    tips_existing = (
        existing.get("tips") if isinstance(existing.get("tips"), list) else []
    )
    tips_incoming = (
        incoming.get("tips") if isinstance(incoming.get("tips"), list) else []
    )
    merged_tips = [
        str(item).strip()
        for item in [*tips_existing, *tips_incoming]
        if str(item).strip()
    ]
    if merged_tips:
        # Keep order and uniqueness.
        seen: set[str] = set()
        deduped_tips: list[str] = []
        for tip in merged_tips:
            key = tip.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_tips.append(tip)
        merged["tips"] = deduped_tips[:8]

    warnings_existing = (
        existing.get("seasonal_warnings")
        if isinstance(existing.get("seasonal_warnings"), list)
        else []
    )
    warnings_incoming = (
        incoming.get("seasonal_warnings")
        if isinstance(incoming.get("seasonal_warnings"), list)
        else []
    )
    merged_warnings = [
        str(item).strip()
        for item in [*warnings_existing, *warnings_incoming]
        if str(item).strip()
    ]
    if merged_warnings:
        seen_warnings: set[str] = set()
        deduped_warnings: list[str] = []
        for warning in merged_warnings:
            key = warning.lower()
            if key in seen_warnings:
                continue
            seen_warnings.add(key)
            deduped_warnings.append(warning)
        merged["seasonal_warnings"] = deduped_warnings[:6]

    existing_budget = (
        existing.get("estimated_budget")
        if isinstance(existing.get("estimated_budget"), dict)
        else {}
    )
    incoming_budget = (
        incoming.get("estimated_budget")
        if isinstance(incoming.get("estimated_budget"), dict)
        else {}
    )
    merged["estimated_budget"] = _merge_budget(existing_budget, incoming_budget)

    return merged


def _get_itinerary_lock(chat_id: uuid.UUID) -> asyncio.Lock:
    lock = _ITINERARY_WRITE_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _ITINERARY_WRITE_LOCKS[chat_id] = lock
    return lock


async def _load_existing_itinerary_data(
    db: AsyncSession, chat_id: uuid.UUID
) -> dict[str, Any] | None:
    result = await db.execute(
        select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
    )
    itinerary_row = result.scalars().first()
    if itinerary_row and isinstance(itinerary_row.itinerary_data, dict):
        return dict(itinerary_row.itinerary_data)
    return None


async def _load_progress_state(
    db: AsyncSession, chat_id: uuid.UUID
) -> tuple[str | None, str | None]:
    stage_result = await db.execute(
        select(PlanningSession).where(PlanningSession.chat_room_id == chat_id)
    )
    session = stage_result.scalars().first()
    stage = session.stage if session else None

    itinerary_result = await db.execute(
        select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
    )
    itinerary_row = itinerary_result.scalars().first()
    signature = None
    if itinerary_row and isinstance(itinerary_row.itinerary_data, dict):
        signature = _itinerary_signature(itinerary_row.itinerary_data)

    return stage, signature


async def _upsert_itinerary(
    db: AsyncSession,
    chat_id: uuid.UUID,
    data: dict[str, Any],
    *,
    source: str = "unknown",
) -> str:
    """Upsert itinerary with per-chat locking and merge to prevent concurrent write regressions."""
    lock = _get_itinerary_lock(chat_id)
    async with lock:
        # Also acquire a DB-level row lock so concurrent workers/processes serialize writes.
        await db.execute(
            select(ChatRoom.id).where(ChatRoom.id == chat_id).with_for_update()
        )

        existing = await db.execute(
            select(ChatItinerary)
            .where(ChatItinerary.chat_room_id == chat_id)
            .with_for_update()
        )
        existing_row = existing.scalars().first()

        if existing_row and isinstance(existing_row.itinerary_data, dict):
            existing_data = dict(existing_row.itinerary_data)
            merged = _merge_itinerary_data(existing_row.itinerary_data, data)
            existing_row.itinerary_data = merged
            existing_row.updated_at = datetime.now(timezone.utc)
            persisted_signature = _itinerary_signature(merged)
            logger.info(
                "Itinerary merge-upsert",
                chat_id=chat_id,
                source=source,
                existing_days=_itinerary_day_count(existing_data),
                incoming_days=_itinerary_day_count(data),
                merged_days=_itinerary_day_count(merged),
                merged_activities=_itinerary_activity_count(merged),
                signature=persisted_signature,
            )
            return persisted_signature

        if existing_row:
            existing_row.itinerary_data = data
            existing_row.updated_at = datetime.now(timezone.utc)
            persisted_signature = _itinerary_signature(data)
            logger.info(
                "Itinerary overwrite-upsert",
                chat_id=chat_id,
                source=source,
                incoming_days=_itinerary_day_count(data),
                incoming_activities=_itinerary_activity_count(data),
                signature=persisted_signature,
            )
            return persisted_signature

        db.add(ChatItinerary(chat_room_id=chat_id, itinerary_data=data))
        persisted_signature = _itinerary_signature(data)
        logger.info(
            "Itinerary inserted",
            chat_id=chat_id,
            source=source,
            incoming_days=_itinerary_day_count(data),
            incoming_activities=_itinerary_activity_count(data),
            signature=persisted_signature,
        )
        return persisted_signature


async def _persist_progress_snapshot(
    db: AsyncSession,
    chat_id: uuid.UUID,
    *,
    parsed_stage: str | None,
    parsed_itinerary: dict[str, Any] | None,
    destination_hint: str,
    context_text: str,
    last_stage: str | None,
    last_itinerary_signature: str | None,
) -> tuple[str | None, str | None, dict[str, Any] | None, bool]:
    stage_changed = bool(parsed_stage and parsed_stage != last_stage)
    normalized_itinerary: dict[str, Any] | None = None
    itinerary_changed = False
    next_itinerary_signature = last_itinerary_signature

    if parsed_itinerary:
        normalized_itinerary = _normalize_itinerary_for_ui(
            parsed_itinerary,
            destination_hint=destination_hint,
            context_text=context_text,
        )
        next_itinerary_signature = _itinerary_signature(normalized_itinerary)
        itinerary_changed = next_itinerary_signature != last_itinerary_signature

    if not stage_changed and not itinerary_changed:
        logger.info(
            "Progress snapshot skipped",
            chat_id=chat_id,
            parsed_stage=parsed_stage,
            last_stage=last_stage,
            stage_changed=stage_changed,
            has_parsed_itinerary=parsed_itinerary is not None,
            itinerary_changed=itinerary_changed,
        )
        return last_stage, last_itinerary_signature, normalized_itinerary, False

    if itinerary_changed and normalized_itinerary:
        next_itinerary_signature = await _upsert_itinerary(
            db,
            chat_id,
            normalized_itinerary,
            source="progress_snapshot",
        )

    if stage_changed and parsed_stage:
        await _upsert_planning_stage(db, chat_id, parsed_stage)

    logger.info(
        "Progress snapshot writing",
        chat_id=chat_id,
        stage_changed=stage_changed,
        parsed_stage=parsed_stage,
        itinerary_changed=itinerary_changed,
        next_signature=next_itinerary_signature,
    )

    await db.commit()
    return (
        parsed_stage or last_stage,
        next_itinerary_signature,
        normalized_itinerary,
        True,
    )


# ---------------------------------------------------------------------------
# Main streaming function
# ---------------------------------------------------------------------------


async def run_langchain_agent(
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the multi-step LangChain travel agent and stream tokens.

    Saves the assistant ChatMessage, upserts ChatItinerary, and updates
    PlanningSession stage on each turn.

    Yields:
        SSE-formatted text tokens, including [STEP:...] tool-call events.
    """
    # Extract dynamic system context (itinerary + planning session) from history
    dynamic_sys_prompt = ""
    if history and history[0].get("role") == "system":
        dynamic_sys_prompt = history.pop(0).get("content", "")

    (
        last_persisted_stage,
        last_persisted_itinerary_signature,
    ) = await _load_progress_state(db, chat_id)
    preflight_context = await _build_enforced_preflight_context(
        user_message=user_message,
        dynamic_context=dynamic_sys_prompt,
        stage=last_persisted_stage,
    )
    if preflight_context:
        dynamic_sys_prompt = (
            f"{dynamic_sys_prompt}\n\n---\n\n{preflight_context}"
            if dynamic_sys_prompt
            else preflight_context
        )

    executor = _build_agent_executor(dynamic_sys_prompt)
    chat_history = _messages_to_langchain(history)

    full_response = ""
    last_message_content = ""
    llm_candidates: list[str] = []
    itinerary_data: dict[str, Any] | None = None
    pending_tool_snapshot: tuple[dict[str, Any], str | None, int | None] | None = None
    saw_itinerary_tool_call = False
    grounding_tools_used: set[str] = set()
    prompt_tokens = 0
    completion_tokens = 0
    yielded_preflight_steps: set[str] = set()

    try:
        for step_token in [
            "[STEP:🕒 Synchronizing clock...]",
            "[STEP:📚 Checking knowledge base for current travel context...]",
        ]:
            if step_token not in yielded_preflight_steps:
                yielded_preflight_steps.add(step_token)
                yield step_token

        async for event in executor.astream_events(
            {"messages": chat_history + [HumanMessage(content=user_message)]},
            {"recursion_limit": 40},
            version="v2",
        ):
            kind = event.get("event", "")

            # Stream tool call starts as [STEP:] markers for the UI
            if kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", {})
                if tool_name in {
                    "rag_travel_knowledge",
                    "search_web",
                    "get_place_details",
                    "get_weather",
                }:
                    grounding_tools_used.add(tool_name)
                step_label = _tool_step_label(tool_name, tool_input)
                step_token = f"[STEP:{step_label}]"
                full_response += step_token
                yield step_token

                if tool_name == "update_itinerary_panel":
                    saw_itinerary_tool_call = True
                    (
                        tool_itinerary,
                        tool_stage,
                        tool_expected_days,
                    ) = _extract_itinerary_tool_snapshot(tool_input)
                    if tool_itinerary is not None:
                        pending_tool_snapshot = (
                            tool_itinerary,
                            tool_stage,
                            tool_expected_days,
                        )
                    else:
                        logger.warning(
                            "Failed to capture update_itinerary_panel tool input",
                            chat_id=chat_id,
                            tool_input_type=type(tool_input).__name__,
                            tool_input_preview=str(tool_input)[:1000],
                        )

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                tool_output = event.get("data", {}).get("output")
                output_text = _tool_output_to_text(tool_output)
                tool_status = _classify_tool_output(tool_name, output_text)
                preview = output_text[:240]
                log_payload = {
                    "chat_id": chat_id,
                    "tool": tool_name,
                    "status": tool_status,
                    "preview": preview,
                }
                if tool_status in {
                    "error",
                    "empty",
                    "fallback",
                    "model_prior",
                    "no_live_data",
                }:
                    logger.warning(
                        "LangChain tool completed with non-ideal result", **log_payload
                    )
                else:
                    logger.info("LangChain tool completed", **log_payload)

                if tool_name == "update_itinerary_panel" and pending_tool_snapshot:
                    try:
                        (
                            tool_itinerary,
                            tool_stage,
                            tool_expected_days,
                        ) = pending_tool_snapshot

                        if output_text.strip().startswith("{"):
                            try:
                                parsed_tool_output = json.loads(output_text)
                                tool_stage = (
                                    _clean_stage_value(parsed_tool_output.get("stage"))
                                    or tool_stage
                                )
                                tool_expected_days = (
                                    _normalize_expected_total_days(
                                        parsed_tool_output.get("expected_total_days")
                                    )
                                    or tool_expected_days
                                )
                            except json.JSONDecodeError:
                                pass

                        tool_snapshot = _inject_panel_state(
                            tool_itinerary,
                            stage=tool_stage,
                            expected_total_days=tool_expected_days,
                            source="update_itinerary_panel",
                            status="captured",
                        )
                        itinerary_data = tool_snapshot

                        (
                            last_persisted_stage,
                            last_persisted_itinerary_signature,
                            normalized_snapshot,
                            wrote_progress,
                        ) = await _persist_progress_snapshot(
                            db,
                            chat_id,
                            parsed_stage=tool_stage,
                            parsed_itinerary=tool_snapshot,
                            destination_hint=_infer_destination_hint(
                                dynamic_sys_prompt,
                                json.dumps(tool_itinerary, default=str)[:2000],
                                user_message,
                            ),
                            context_text="\n".join(
                                [
                                    dynamic_sys_prompt,
                                    user_message,
                                    json.dumps(tool_itinerary, default=str)[:6000],
                                ]
                            ),
                            last_stage=last_persisted_stage,
                            last_itinerary_signature=last_persisted_itinerary_signature,
                        )
                        if normalized_snapshot:
                            itinerary_data = normalized_snapshot
                        if wrote_progress:
                            logger.info(
                                "Structured itinerary snapshot persisted (langchain)",
                                chat_id=chat_id,
                                stage=last_persisted_stage,
                                itinerary_signature=last_persisted_itinerary_signature,
                            )
                    except Exception as snapshot_err:
                        await db.rollback()
                        logger.warning(
                            "Failed to persist structured itinerary tool snapshot (langchain)",
                            chat_id=chat_id,
                            error=str(snapshot_err),
                        )
                    finally:
                        pending_tool_snapshot = None

            # Stream LLM text tokens
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    full_response += token
                    yield token

            # Capture usage from the end of LLM calls
            elif kind == "on_chat_model_end":
                output = event.get("data", {}).get("output")
                if output:
                    output_text = _message_content_to_text(
                        getattr(output, "content", "")
                    )
                    if output_text:
                        last_message_content = output_text
                        llm_candidates.append(output_text)
                        maybe_stage = _extract_planning_stage(output_text)
                        maybe_itinerary = _extract_itinerary(
                            output_text, log_on_failure=False
                        )
                        if maybe_itinerary is None and _should_attempt_itinerary_repair(
                            output_text,
                            parsed_stage=maybe_stage,
                            is_finalize_turn=False,
                        ):
                            maybe_itinerary = await _recover_itinerary_snapshot(
                                source_text=output_text,
                                history=history,
                                user_message=user_message,
                                dynamic_context=dynamic_sys_prompt,
                                parsed_stage=maybe_stage,
                                is_finalize_turn=False,
                                allow_minimal_fallback=False,
                            )
                        if maybe_itinerary:
                            itinerary_data = maybe_itinerary

                        if maybe_stage or maybe_itinerary:
                            try:
                                (
                                    last_persisted_stage,
                                    last_persisted_itinerary_signature,
                                    normalized_snapshot,
                                    wrote_progress,
                                ) = await _persist_progress_snapshot(
                                    db,
                                    chat_id,
                                    parsed_stage=maybe_stage,
                                    parsed_itinerary=maybe_itinerary,
                                    destination_hint=_infer_destination_hint(
                                        dynamic_sys_prompt,
                                        output_text,
                                        user_message,
                                    ),
                                    context_text="\n".join(
                                        [dynamic_sys_prompt, user_message, output_text]
                                    ),
                                    last_stage=last_persisted_stage,
                                    last_itinerary_signature=last_persisted_itinerary_signature,
                                )
                                if normalized_snapshot:
                                    itinerary_data = normalized_snapshot
                                if wrote_progress:
                                    logger.info(
                                        "Progress snapshot persisted (langchain)",
                                        chat_id=chat_id,
                                        stage=last_persisted_stage,
                                        itinerary_signature=last_persisted_itinerary_signature,
                                    )
                            except Exception as progress_err:
                                await db.rollback()
                                logger.warning(
                                    "Failed progressive itinerary persistence (langchain)",
                                    chat_id=chat_id,
                                    error=str(progress_err),
                                )

                    # LangChain v0.2+ usage_metadata
                    usage = getattr(output, "usage_metadata", None)
                    if usage:
                        prompt_tokens += usage.get("input_tokens", 0)
                        completion_tokens += usage.get("output_tokens", 0)
                    else:
                        # Legacy/fallback additional_kwargs
                        usage_obj = output.additional_kwargs.get("usage")
                        if usage_obj:
                            prompt_tokens += usage_obj.get("prompt_tokens", 0)
                            completion_tokens += usage_obj.get("completion_tokens", 0)

    except Exception as e:
        error_msg = f"\n\n*An error occurred: {e}*"
        full_response += error_msg
        yield error_msg
        logger.exception("LangChain agent error", error=str(e), chat_id=chat_id)

    # -----------------------------------------------------------------------
    # Persist assistant message + itinerary + planning stage
    # -----------------------------------------------------------------------
    try:
        is_finalize_turn = _is_finalize_request(user_message)
        final_text = _pick_best_response_text(
            [last_message_content, *llm_candidates, full_response]
        )
        if not final_text:
            final_text = full_response

        parsed_stage = _extract_planning_stage(final_text)
        parsed_itinerary = itinerary_data or await _recover_itinerary_snapshot(
            source_text=final_text,
            history=history,
            user_message=user_message,
            dynamic_context=dynamic_sys_prompt,
            parsed_stage=parsed_stage,
            is_finalize_turn=is_finalize_turn,
            allow_minimal_fallback=last_persisted_itinerary_signature is None,
        )

        if parsed_itinerary is None:
            parsed_itinerary = await _load_existing_itinerary_data(db, chat_id)
            if parsed_itinerary is not None:
                logger.info(
                    "Reusing existing itinerary snapshot after final extraction miss",
                    chat_id=chat_id,
                    stage=parsed_stage,
                    saw_itinerary_tool_call=saw_itinerary_tool_call,
                )
            elif is_finalize_turn or parsed_stage == "complete":
                logger.warning(
                    "Finalize turn ended without persisted itinerary snapshot",
                    chat_id=chat_id,
                    stage=parsed_stage,
                    saw_itinerary_tool_call=saw_itinerary_tool_call,
                    final_text_preview=final_text[:1200],
                )

        if is_finalize_turn and not parsed_stage:
            parsed_stage = "complete"

        if parsed_itinerary:
            parsed_itinerary = _normalize_itinerary_for_ui(
                parsed_itinerary,
                destination_hint=_infer_destination_hint(
                    dynamic_sys_prompt, final_text, user_message
                ),
                context_text="\n".join([dynamic_sys_prompt, user_message, final_text]),
            )

        # Strip XML tags for stored message (UI already handles them)
        clean_response = _strip_agent_tags(final_text)
        # Also strip [STEP:] markers from stored message
        clean_response = re.sub(r"\[STEP:[^\]]*\]", "", clean_response).strip()
        clean_response = _apply_fact_grounding_notice_if_needed(
            clean_response,
            grounding_tools_used=grounding_tools_used,
        )

        # If the response only contained XML blocks, give it a friendly fallback
        if not clean_response and parsed_itinerary:
            clean_response = "✅ **Itinerary updated!** I have finalized the details and populated your travel plan. You can view the full enriched itinerary in the panel on the right."

        # Calculate cost
        msg_cost = calculate_minimax_cost(prompt_tokens, completion_tokens)

        assistant_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.assistant,
            content=clean_response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost=msg_cost,
            message_metadata={"agent": "langchain"},
        )
        db.add(assistant_msg)
        await db.flush()

        # Update user aggregate usage
        chat_room_res = await db.execute(select(ChatRoom).where(ChatRoom.id == chat_id))
        chat_room = chat_room_res.scalars().first()
        if chat_room:
            user_res = await db.execute(
                select(User).where(User.id == chat_room.user_id)
            )
            user = user_res.scalars().first()
            if user:
                user.total_tokens += prompt_tokens + completion_tokens
                user.total_cost += msg_cost
                # Update legacy field if desired (as millions)
                user.token_usage_millions += (
                    prompt_tokens + completion_tokens
                ) / 1_000_000

        # Update itinerary only when snapshot meaningfully changed.
        if parsed_itinerary:
            parsed_itinerary_signature = _itinerary_signature(parsed_itinerary)
            if parsed_itinerary_signature != last_persisted_itinerary_signature:
                last_persisted_itinerary_signature = await _upsert_itinerary(
                    db,
                    chat_id,
                    parsed_itinerary,
                    source="langchain_final",
                )

        # Update planning session stage only when advanced/changed.
        new_stage = parsed_stage
        if new_stage and new_stage != last_persisted_stage:
            await _upsert_planning_stage(db, chat_id, new_stage)
            last_persisted_stage = new_stage

        # Persist assistant output for future KB fallback.
        try:
            from app.agents.rag.vector_store import add_to_knowledge_base

            add_to_knowledge_base(
                text=(
                    f"Assistant response (langchain) for chat {chat_id}:\n"
                    f"{clean_response}\n\n"
                    f"Planning stage: {new_stage or 'unknown'}"
                ),
                metadata={
                    "source": "assistant_response_langchain",
                    "chat_id": str(chat_id),
                    "stage": new_stage or "unknown",
                },
            )
        except Exception as kb_err:
            logger.warning(
                "Failed to persist LangChain response to KB",
                error=str(kb_err),
                chat_id=chat_id,
            )

        await db.commit()
        logger.info(
            "Agent response saved",
            chat_id=chat_id,
            has_itinerary=parsed_itinerary is not None,
            stage=new_stage,
        )

    except Exception as e:
        await db.rollback()
        logger.exception("Failed to save agent response", error=str(e), chat_id=chat_id)


async def _upsert_planning_stage(
    db: AsyncSession, chat_id: uuid.UUID, new_stage: str
) -> None:
    """Create or update the PlanningSession stage."""
    result = await db.execute(
        select(PlanningSession).where(PlanningSession.chat_room_id == chat_id)
    )
    session = result.scalars().first()
    if session:
        session.stage = new_stage
        session.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            PlanningSession(
                chat_room_id=chat_id,
                stage=new_stage,
                preferences=dict(DEFAULT_PREFERENCES),
            )
        )


def _tool_step_label(tool_name: str, tool_input: dict) -> str:
    """Map tool names to human-readable step labels for the UI."""
    labels = {
        "search_flights": lambda i: f"✈️ Searching flights {i.get('origin_city', '')} → {i.get('destination_city', '')}...",
        "get_airport_transit": lambda i: f"🛫 Checking terminal transit at {i.get('airport_name', '')}...",
        "search_hotels": lambda i: f"🏨 Finding hotels in {i.get('destination', '')}...",
        "get_place_details": lambda i: f"📍 Getting details for {i.get('place_name', '')}...",
        "search_web": lambda i: f"🔍 Searching: {i.get('query', '')[:50]}...",
        "scrape_website": lambda i: f"🌐 Scraping: {i.get('url', '')[:50]}...",
        "geocode_place": lambda i: f"📍 Locating {i.get('place_name', '')}...",
        "get_weather": lambda i: "🌤️ Checking weather forecast...",
        "rag_travel_knowledge": lambda i: f"📚 Checking knowledge base for {i.get('query', '')[:40]}...",
        "get_current_time": lambda i: "🕒 Synchronizing clock...",
        "search_ground_transport": lambda i: f"🚆 Researching trains/buses to {i.get('destination', '')}...",
        "update_itinerary_panel": lambda i: "🧩 Updating itinerary panel snapshot...",
    }
    fn = labels.get(tool_name)
    if fn:
        try:
            return fn(tool_input)
        except Exception:
            pass
    return f"🔧 Using {tool_name}..."


def calculate_minimax_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculate cost for MiniMax m2.7 based on current rates:
    - Input: $0.30 / 1M tokens
    - Output: $1.20 / 1M tokens
    """
    input_rate = 0.30 / 1_000_000
    output_rate = 1.20 / 1_000_000
    return (prompt_tokens * input_rate) + (completion_tokens * output_rate)
