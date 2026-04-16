"""RAG retriever tool for LangChain agent."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
async def rag_travel_knowledge(query: str) -> str:
    """Search the internal travel knowledge base for destination-specific information.

    Use this FIRST before web search — it contains curated data about popular
    destinations, cultural tips, visa info, seasonal guides, and local customs.

    Args:
        query: The travel question or topic to look up.

    Returns:
        Relevant excerpts from the knowledge base.
    """
    try:
        from app.agents.rag.vector_store import get_retriever

        retriever = get_retriever(k=4)
        docs = await retriever.ainvoke(query)

        if not docs:
            return f"No knowledge base entries found for: '{query}'"

        parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "knowledge base")
            parts.append(f"[KB {i}] (source: {source})\n{doc.page_content}")

        return "\n\n---\n\n".join(parts)

    except Exception as e:
        return f"Knowledge base unavailable: {e}. Continue with web search."
