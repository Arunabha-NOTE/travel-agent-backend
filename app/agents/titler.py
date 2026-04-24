"""Auto-generate concise chat titles from early conversation context."""

from __future__ import annotations

import re
from typing import Any, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You generate concise, descriptive titles for travel planning chats. "
    "Return ONLY the title text. "
    "Keep it 3-6 words, under 40 characters, and avoid punctuation-heavy output."
)


def _to_title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


def _extract_trip_title_from_query(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return None

    lowered = normalized.lower()
    prefixes = [
        "plan a trip to ",
        "plan trip to ",
        "trip to ",
        "travel to ",
        "vacation to ",
        "holiday to ",
    ]

    destination: str | None = None
    origin: str | None = None

    for prefix in prefixes:
        if lowered.startswith(prefix):
            remainder = normalized[len(prefix) :].strip()
            split_match = re.split(
                r"\s+(?:from|for|with|on|in|during|between)\s+",
                remainder,
                maxsplit=1,
                flags=re.IGNORECASE,
            )
            destination = split_match[0].strip(" ,.?!")
            from_match = re.search(r"\bfrom\s+([a-zA-Z ]+)", remainder, re.IGNORECASE)
            if from_match:
                origin = from_match.group(1).strip(" ,.?!")
            break

    if destination:
        destination = _to_title_case(destination)
        if origin:
            origin = _to_title_case(origin)
            return f"{destination} {origin} Trip"
        return f"{destination} Trip"

    route_match = re.search(
        r"\bto\s+([a-zA-Z ]+?)\s+from\s+([a-zA-Z ]+)\b", normalized, re.IGNORECASE
    )
    if route_match:
        destination = _to_title_case(route_match.group(1).strip(" ,.?!"))
        origin = _to_title_case(route_match.group(2).strip(" ,.?!"))
        return f"{destination} {origin} Trip"

    go_match = re.search(
        r"\b(?:go to|travel to|visit)\s+([a-zA-Z ]+?)(?:[,.]|\s+i\s+live\b|\s+from\b|$)",
        normalized,
        re.IGNORECASE,
    )
    if go_match:
        destination = _to_title_case(go_match.group(1).strip(" ,.?!"))

        live_match = re.search(
            r"\b(?:i\s+live\s+in|we\s+live\s+in|from)\s+([a-zA-Z ]+?)(?:[,.]|\s+we\b|\s+travel\b|\s+dates\b|$)",
            normalized,
            re.IGNORECASE,
        )
        if live_match:
            origin = _to_title_case(live_match.group(1).strip(" ,.?!"))
            return f"{destination} {origin} Trip"

        return f"{destination} Trip"

    return None


def _normalize_seed_text(seed: str | Sequence[dict[str, Any]]) -> str:
    if isinstance(seed, str):
        return seed.strip()[:800]

    if not isinstance(seed, Sequence):
        return ""

    parts: list[str] = []
    for message in seed[:8]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user")).strip() or "user"
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        parts.append(f"{role}: {content}")

    combined = "\n".join(parts)
    return combined[:1200]


def _clean_title(raw: str) -> str | None:
    title = raw.strip().strip('"').strip("'")
    title = re.sub(r"\s+", " ", title)

    # Reject obvious instruction leakages.
    leaked_markers = [
        "the user",
        "asking for",
        "summary",
        "instruction",
        "generate",
        "title:",
        "possible title",
        "conversation history",
    ]
    lowered = title.lower()
    if any(marker in lowered for marker in leaked_markers):
        return None

    if not title or len(title) > 60:
        return None

    return title


async def generate_chat_title(seed: str | Sequence[dict[str, Any]]) -> str | None:
    """Generate a chat title from either raw text or conversation messages.

    Args:
        seed: Either a user message string or a sequence of role/content dicts.

    Returns:
        A concise title or None if title generation fails validation.
    """
    snippet = _normalize_seed_text(seed)
    if not snippet:
        logger.info("Titler skipped due empty seed")
        return None

    if isinstance(seed, str):
        heuristic_title = _extract_trip_title_from_query(seed)
        if heuristic_title:
            logger.info("Titler generated heuristic title", title=heuristic_title)
            return heuristic_title

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate a short title for this travel-planning conversation:\n\n"
                        f"{snippet}"
                    ),
                },
            ],
            max_tokens=24,
            temperature=0.3,
        )

        raw = response.choices[0].message.content or ""
        title = _clean_title(raw)
        if not title:
            logger.warning("Titler returned invalid title", raw_preview=raw[:120])
            return None

        logger.info("Titler generated title", title=title)
        return title

    except Exception as exc:
        logger.exception("Failed to generate chat title", error=str(exc))
        return None
