"""Firecrawl web search tool for the travel agent."""

from __future__ import annotations

from langchain_core.tools import tool

from app.core.config import settings


@tool
async def firecrawl_search(query: str, num_results: int = 3) -> str:
    """Search the web for travel-related information using Firecrawl.

    Use this tool to find up-to-date information about travel destinations,
    attractions, restaurants, tips, visa requirements, and more.

    Args:
        query: The search query string (e.g. "best temples to visit in Kyoto").
        num_results: Number of results to retrieve (default 3, max 5).

    Returns:
        Concatenated scraped content from top search results.
    """
    try:
        from firecrawl import FirecrawlApp  # type: ignore[import]

        app = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

        # Use Firecrawl search endpoint
        result = app.search(
            query=query,
            limit=min(num_results, 5),
        )

        if not result or not result.get("data"):
            return f"No results found for query: '{query}'"

        parts = []
        for i, item in enumerate(result["data"], 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            content = (
                item.get("markdown")
                or item.get("content")
                or item.get("description")
                or ""
            )
            # Truncate long content
            if len(content) > 1500:
                content = content[:1500] + "..."
            parts.append(f"[Result {i}] {title}\nURL: {url}\n\n{content}")

        return "\n\n---\n\n".join(parts)

    except ImportError:
        return "Firecrawl not installed. Run: uv add firecrawl-py"
    except Exception as e:
        # Graceful fallback so agent can still function without valid key
        return f"Web search unavailable (Firecrawl error: {e}). Use your training knowledge instead."
