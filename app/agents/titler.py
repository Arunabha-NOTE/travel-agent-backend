"""Auto-generate a chat room title from the first user message."""

from __future__ import annotations
import re

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TITLE_PROMPT = (
    "Generate a short, descriptive title (3-6 words) for a travel planning chat "
    "based on the user's first message. Return ONLY the title — no quotes, no punctuation at the end, "
    "no explanation.\n\nUser message: {message}"
)


async def generate_chat_title(user_message: str) -> str | None:
    """Call Minimax to produce a concise chat title from the first message.

    Returns the title string, or None on failure (caller should keep default).
    """
    try:
        from openai import AsyncOpenAI  # already a dep via langchain-openai

        client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

        # Truncate very long messages — we only need the gist
        snippet = user_message[:500]

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": _TITLE_PROMPT.format(message=snippet),
                }
            ],
            max_tokens=20,
            temperature=0.4,
        )

        raw = response.choices[0].message.content or ""
        # Strip <think>...</think> reasoning blocks that minimax-m2.7 emits
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        title = raw.strip().strip('"').strip("'").strip()

        if title and len(title) <= 100:
            logger.info("Chat title generated", title=title)
            return title

        return None

    except Exception as exc:
        logger.warning("Failed to auto-generate chat title", error=str(exc))
        return None
