"""Shared utility helpers for agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class KBFallbackDoc:
    """Structured KB fallback result with content and metadata."""

    content: str
    source: str
    metadata: dict[str, Any]


def persist_tool_result(
    tool_name: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    status: str = "ok",
) -> None:
    """Persist tool outputs/errors so later runs can fall back to KB context."""
    try:
        from app.agents.rag.vector_store import add_to_knowledge_base

        meta = dict(metadata or {})
        meta.update(
            {
                "source": tool_name,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        add_to_knowledge_base(text=text, metadata=meta)
    except Exception as e:
        logger.warning("Failed to persist tool result", tool=tool_name, error=str(e))


async def get_kb_fallback(query: str, k: int = 3) -> str:
    """Fetch concise fallback context from vector DB."""
    try:
        from app.agents.rag.vector_store import get_retriever

        retriever = get_retriever(k=k)
        docs = await retriever.ainvoke(query)
        if not docs:
            return ""

        parts: list[str] = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "knowledge_base")
            content = (doc.page_content or "").strip()
            if not content:
                continue
            parts.append(f"[KB {i}] ({source})\n{content[:1500]}")

        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning("KB fallback retrieval failed", error=str(e), query=query)
        return ""


async def get_kb_fallback_docs(query: str, k: int = 3) -> list[KBFallbackDoc]:
    """Fetch raw KB fallback documents with metadata for date-aware filtering."""
    try:
        from app.agents.rag.vector_store import get_retriever

        retriever = get_retriever(k=k)
        docs = await retriever.ainvoke(query)
        if not docs:
            return []

        results: list[KBFallbackDoc] = []
        for doc in docs:
            content = (doc.page_content or "").strip()
            if not content:
                continue
            metadata = dict(doc.metadata or {})
            results.append(
                KBFallbackDoc(
                    content=content,
                    source=str(metadata.get("source", "knowledge_base")),
                    metadata=metadata,
                )
            )
        return results
    except Exception as e:
        logger.warning("KB fallback doc retrieval failed", error=str(e), query=query)
        return []
