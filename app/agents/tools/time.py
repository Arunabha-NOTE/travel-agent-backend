"""Time-related tools for the travel agent."""

from __future__ import annotations

from datetime import datetime, timezone
from langchain_core.tools import tool

from app.agents.tools.utils import persist_tool_result


@tool
def get_current_time() -> str:
    """Get the current date, time, and timezone.

    Use this to understand today's date and reason about travel windows,
    seasonal events, and booking lead times.

    Returns:
        A string with the current ISO formatted time and human-readable date.
    """
    now = datetime.now(timezone.utc)
    output = (
        f"Current UTC Time: {now.isoformat()}\n"
        f"Human Readable: {now.strftime('%A, %B %d, %Y %H:%M:%S')} UTC"
    )
    persist_tool_result(
        "get_current_time",
        output,
        metadata={"timezone": "UTC"},
        status="ok",
    )
    return output
