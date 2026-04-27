import re
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
async def rag_travel_knowledge(query: str, config: RunnableConfig) -> str:
    """Search the internal travel knowledge base for destination-specific information.

    Use this FIRST before web search — it contains curated data about popular
    destinations, cultural tips, visa info, seasonal guides, and local customs.
    It also retrieves your previous session history for continuity.

    Args:
        query: The travel question or topic to look up.
    """
    try:
        from app.agents.rag.vector_store import get_retriever

        # Extract user_id from config (passed from agent runner)
        user_id = config.get("configurable", {}).get("user_id")

        # 1. Search user-specific history (if any)
        user_docs = []
        if user_id is not None:
            user_retriever = get_retriever(k=3, filter={"user_id": user_id})
            user_docs = await user_retriever.ainvoke(query)

        # 2. Search global/curated knowledge
        public_retriever = get_retriever(k=3, filter={"is_public": True})
        public_docs = await public_retriever.ainvoke(query)

        # Merge and deduplicate by content hash
        seen_contents = set()
        all_docs = []
        for doc in user_docs + public_docs:
            content_hash = hash(doc.page_content)
            if content_hash not in seen_contents:
                all_docs.append(doc)
                seen_contents.add(content_hash)

        # Sort by relevance (not really possible here without scores,
        # so we just prefer user docs by putting them first)

        if not all_docs:
            return f"No relevant knowledge base entries found for: '{query}'"

        parts = []
        for i, doc in enumerate(all_docs, 1):
            source = doc.metadata.get("source", "knowledge base")
            # Sanitize content: remove explicit Chat IDs to prevent exposure
            content = doc.page_content
            content = re.sub(
                r"chat [a-f0-9-]{36}", "previous session", content, flags=re.I
            )
            parts.append(f"[KB {i}] (source: {source})\n{content}")

        return "\n\n---\n\n".join(parts)

    except Exception as e:
        return f"Knowledge base unavailable: {e}. Continue with web search."
