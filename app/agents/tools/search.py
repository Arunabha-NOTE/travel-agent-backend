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
        # firecrawl-py v4+ uses V1FirecrawlApp
        from firecrawl.v1 import V1FirecrawlApp

        app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

        # .search() returns a V1SearchResponse with .data: list[V1ScrapeResponse]
        result = app.search(query=query, limit=min(num_results, 5))

        if not result or not result.data:
            return f"No results found for query: '{query}'"

        parts = []
        for i, item in enumerate(result.data, 1):
            title = getattr(item, "title", None) or "Untitled"
            url = getattr(item, "url", "") or ""
            content = (
                getattr(item, "markdown", None)
                or getattr(item, "description", None)
                or ""
            )
            # Truncate long content
            if len(content) > 1500:
                content = content[:1500] + "..."
            parts.append(f"[Result {i}] {title}\nURL: {url}\n\n{content}")

        return (
            "\n\n---\n\n".join(parts)
            if parts
            else f"No results found for query: '{query}'"
        )

    except ImportError:
        # Fallback for older SDK versions (< v4)
        try:
            from firecrawl import FirecrawlApp  # type: ignore[import]

            app_old = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
            result = app_old.search(query=query, limit=min(num_results, 5))
            raw_data = result.get("data", []) if isinstance(result, dict) else []
            parts = []
            for i, item in enumerate(raw_data, 1):
                title = item.get("title", "Untitled")
                url = item.get("url", "")
                content = (
                    item.get("markdown")
                    or item.get("content")
                    or item.get("description")
                    or ""
                )
                if len(content) > 1500:
                    content = content[:1500] + "..."
                parts.append(f"[Result {i}] {title}\nURL: {url}\n\n{content}")
            return (
                "\n\n---\n\n".join(parts)
                if parts
                else f"No results found for query: '{query}'"
            )
        except Exception as e2:
            return f"Web search unavailable: {e2}. Use your training knowledge instead."

    except Exception as e:
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "Firecrawl search error", error=str(e), query=query
        )
        return f"Web search unavailable (Firecrawl error: {e}). Use your training knowledge instead."
