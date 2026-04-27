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
    user_id: int | None = None,
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
        add_to_knowledge_base(text=text, metadata=meta, user_id=user_id)
    except Exception as e:
        logger.warning("Failed to persist tool result", tool=tool_name, error=str(e))


async def get_kb_fallback(query: str, k: int = 3, user_id: int | None = None) -> str:
    """Fetch concise fallback context from vector DB."""
    try:
        from app.agents.rag.vector_store import get_retriever

        # Search user-specific and public
        user_docs = []
        if user_id is not None:
            user_retriever = get_retriever(k=k, filter={"user_id": user_id})
            user_docs = await user_retriever.ainvoke(query)

        public_retriever = get_retriever(k=k, filter={"is_public": True})
        public_docs = await public_retriever.ainvoke(query)

        # Merge and deduplicate
        seen = set()
        all_docs = []
        for doc in user_docs + public_docs:
            if doc.page_content not in seen:
                all_docs.append(doc)
                seen.add(doc.page_content)

        if not all_docs:
            return ""

        parts: list[str] = []
        for i, doc in enumerate(all_docs[:k], 1):
            source = doc.metadata.get("source", "knowledge_base")
            content = (doc.page_content or "").strip()
            if not content:
                continue
            parts.append(f"[KB {i}] ({source})\n{content[:1500]}")

        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning("KB fallback retrieval failed", error=str(e), query=query)
        return ""


async def get_kb_fallback_docs(
    query: str, k: int = 3, user_id: int | None = None
) -> list[KBFallbackDoc]:
    """Fetch raw KB fallback documents with metadata for date-aware filtering."""
    try:
        from app.agents.rag.vector_store import get_retriever

        kb_filter = {"user_id": user_id} if user_id is not None else None
        retriever = get_retriever(k=k, filter=kb_filter)
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
