"""Tool for updating the live itinerary panel."""

from __future__ import annotations

from typing import Any
import json
from langchain_core.tools import tool

from app.agents.tools.utils import persist_tool_result


@tool
async def update_itinerary_panel(
    itinerary_data: dict[str, Any],
    stage: str | None = None,
    expected_total_days: int | None = None,
) -> str:
    """Send the complete, fully formed JSON itinerary to the user's interface.

    You MUST use this tool to persist or update the itinerary whenever the plan changes.
    It replaces the mechanism of writing XML ```json... <itinerary>``` blocks directly to the chat stream.

    Args:
        itinerary_data: The full JSON object representing the entire itinerary plan.
            Must strictly conform to the expected schema including 'destination', 'total_days',
            'flights', 'hotel', 'days', and 'tips'.
        stage: The current planning stage (e.g., 'initial', 'flights', 'hotels', 'day_plan', 'done').
        expected_total_days: The overall number of days being planned (helps UI progress bars).

    Returns:
        A confirmation message that the itinerary was successfully updated.
    """

    persist_tool_result(
        "update_itinerary_panel",
        "Itinerary sent to UI correctly with JSON data length: "
        + str(len(json.dumps(itinerary_data))),
        metadata={"stage": stage, "expected_total_days": expected_total_days},
        status="ok",
    )

    return "✅ the itinerary panel was updated successfully. You do not need to print the raw json in your text response."
