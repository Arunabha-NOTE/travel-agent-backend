"""Firecrawl web search and scrape tools for the travel agent."""

from __future__ import annotations

from langchain_core.tools import tool

from app.core.config import settings
from app.agents.tools.utils import persist_tool_result


@tool
async def search_web(query: str, limit: int = 5) -> str:
    """Search the web for travel-related URLs and snippets using Firecrawl.

    Use this tool to find up-to-date links, articles, recommendations, and news about a
    destination. Unlike a full scrape, this quickly returns search results and brief snippets.

    Args:
        query: The search query string (e.g. "best temples to visit in Kyoto").
        limit: Number of results to retrieve (default 5).

    Returns:
        A list of search results featuring Title, URL, and a short snippet.
    """
    try:
        from firecrawl.v1 import V1FirecrawlApp

        app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

        # .search() typically returns a V1SearchResponse with .data: list[V1ScrapResponse]
        result = app.search(query=query, limit=limit)

        if not result or not getattr(result, "data", None):
            return f"No links found for query: '{query}'"

        parts = []
        for i, item in enumerate(result.data, 1):
            if isinstance(item, dict):
                title = item.get("title") or "Untitled"
                url = item.get("url") or "No URL"
                snippet = item.get("description") or (
                    item.get("metadata", {}).get("description")
                    if isinstance(item.get("metadata"), dict)
                    else None
                )
                content = item.get("markdown", "")
            else:
                title = getattr(item, "title", "Untitled") or "Untitled"
                url = getattr(item, "url", "No URL") or "No URL"

                # Check for metadata
                metadata = getattr(item, "metadata", None)
                if metadata and isinstance(metadata, dict):
                    snippet = metadata.get("description")
                else:
                    snippet = getattr(item, "description", None)
                content = getattr(item, "markdown", "") or ""

            # If no snippet, use the first 300 chars of markdown
            if not snippet:
                snippet = content[:300] + "..." if content else "No snippet available."

            parts.append(f"[Result {i}] {title}\nURL: {url}\nSnippet: {snippet}")

        results_str = (
            "\n\n".join(parts) if parts else f"No links found for query: '{query}'"
        )
        persist_tool_result(
            "search_web",
            f"Web search links for '{query}':\n{results_str}",
            metadata={"query": query, "limit": limit},
            status="ok" if parts else "empty",
        )
        return results_str

    except Exception as e:
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "Firecrawl search_web error", error=str(e), query=query
        )
        output = f"Web search unavailable (error: {e}). Use your training knowledge."
        persist_tool_result(
            "search_web", output, metadata={"query": query}, status="error"
        )
        return output


@tool
async def scrape_website(url: str) -> str:
    """Scrape the full markdown content of a specific website URL.

    Use this tool after you find a promising link via search_web, or if the user provided a URL.
    This extracts the main content of the article or page, allowing you to read its full details.

    Args:
        url: The absolute HTTP/HTTPS URL of the site to scrape.

    Returns:
        The markdown content extracted from the website text.
    """
    try:
        from firecrawl.v1 import V1FirecrawlApp

        app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

        # Scrape a single URL into markdown format
        result = app.scrape_url(url, params={"formats": ["markdown"]})

        content = ""
        if isinstance(result, dict):
            content = result.get("markdown") or result.get("content") or ""
        else:
            content = (
                getattr(result, "markdown", None)
                or getattr(result, "content", None)
                or ""
            )

        if not content:
            return f"No readable markdown content could be extracted from: {url}"

        # Truncate aggressively to prevent context blowing out.
        if len(content) > 6000:
            content = content[:6000] + "...\n[Content Truncated due to length]"

        persist_tool_result(
            "scrape_website",
            f"Scraped content from {url}, length: {len(content)}",
            metadata={"url": url},
            status="ok",
        )
        return content

    except Exception as e:
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "Firecrawl scrape_website error", error=str(e), url=url
        )
        output = f"Failed to scrape website {url} (error: {e})."
        persist_tool_result(
            "scrape_website", output, metadata={"url": url}, status="error"
        )
        return output
