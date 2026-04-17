import asyncio
import pytest
from firecrawl.v1 import V1FirecrawlApp
from app.core.config import settings


@pytest.mark.asyncio
async def test_firecrawl():
    print(f"Testing Firecrawl with API Key: {settings.FIRECRAWL_API_KEY[:5]}...")
    app = V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

    query = "Pune to Delhi flights May 23 2026 price"
    print(f"Searching: {query}")

    try:
        result = app.search(query, limit=3)
        print(
            f"Result data: {result.data if hasattr(result, 'data') else result.get('data', [])}"
        )
        if result.data:
            for i, item in enumerate(result.data):
                print(f"\n--- Result {i + 1} ---")
                print(f"Title: {getattr(item, 'title', 'N/A')}")
                print(f"URL: {getattr(item, 'url', 'N/A')}")
                content = getattr(item, "markdown", None) or getattr(
                    item, "description", None
                )
                print(f"Content length: {len(content) if content else 0}")
                print(f"Preview: {str(content)[:200] if content else 'EMPTY'}")
        else:
            print("No data returned in .data field.")
    except Exception as e:
        print(f"Firecrawl Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_firecrawl())
