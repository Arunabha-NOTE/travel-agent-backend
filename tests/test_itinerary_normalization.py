from __future__ import annotations

import json
from pathlib import Path

from app.agents.langchain_agent import _normalize_itinerary_for_ui


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "frankfurt_itinerary_response.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_normalization_does_not_invent_flights_when_missing() -> None:
    data = load_fixture()
    data["flights"] = {"outbound": None, "return": None}

    normalized = _normalize_itinerary_for_ui(
        data,
        destination_hint="Frankfurt, Germany",
        context_text="User is traveling to Frankfurt for work",
    )

    assert normalized["flights"] is None


def test_normalization_preserves_return_leg_when_provided() -> None:
    data = load_fixture()
    data["flights"]["return"] = {
        "currency": "INR",
        "cabin_class": "economy",
        "price_per_person": 42000,
        "total_duration_mins": 610,
        "segments": [
            {
                "airline": "Lufthansa",
                "flight_number": None,
                "from_airport": "FRA",
                "from_terminal": "T1",
                "to_airport": "DEL",
                "to_terminal": "T3",
                "departure": "14:30",
                "arrival": "01:10",
                "duration_mins": 490,
                "layover_transit_mins": 50,
            }
        ],
    }

    normalized = _normalize_itinerary_for_ui(
        data,
        destination_hint="Frankfurt, Germany",
        context_text="Return flight from Frankfurt to Delhi is confirmed",
    )

    assert normalized["flights"] is not None
    assert normalized["flights"]["return"] is not None
    assert normalized["flights"]["return"]["segments"][0]["from_airport"] == "FRA"
    assert normalized["flights"]["return"]["segments"][0]["to_airport"] == "DEL"
