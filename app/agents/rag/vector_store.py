"""pgvector-backed vector store for the travel knowledge base."""

from __future__ import annotations

from functools import lru_cache

from langchain_community.vectorstores import PGVector  # type: ignore

from app.agents.rag.embedder import get_embeddings
from app.core.config import settings


def _get_connection_string() -> str:
    """Return a psycopg2-compatible connection string for pgvector."""
    # LangChain PGVector needs a sync connection string (psycopg2)
    uri = settings.SQLALCHEMY_SYNC_DATABASE_URI
    return uri


@lru_cache(maxsize=1)
def get_vector_store() -> PGVector:
    """Return a cached PGVector store instance.

    Creates the pgvector extension and collection table on first use.
    """
    return PGVector(
        collection_name=settings.PGVECTOR_COLLECTION,
        connection_string=_get_connection_string(),
        embedding_function=get_embeddings(),
        pre_delete_collection=False,
        use_jsonb=True,
    )


def get_retriever(k: int = 4, filter: dict | None = None):
    """Return a LangChain retriever from the pgvector store.

    Args:
        k: Number of documents to retrieve (default 4).
        filter: Optional metadata filter for pgvector search.
    """
    store = get_vector_store()
    search_kwargs = {"k": k}
    if filter:
        search_kwargs["filter"] = filter

    return store.as_retriever(
        search_type="similarity",
        search_kwargs=search_kwargs,
    )


def add_to_knowledge_base(
    text: str,
    metadata: dict | None = None,
    user_id: int | None = None,
    is_public: bool = False,
):
    """Add a piece of text to the travel knowledge base vector store.

    Args:
        text: The content to store
        metadata: Optional metadata (e.g. source, chat_id, timestamp)
        user_id: Optional user ID to scope the knowledge
        is_public: If True, this knowledge is available to everyone
    """
    store = get_vector_store()
    meta = dict(metadata or {})
    if user_id is not None:
        meta["user_id"] = user_id
    meta["is_public"] = is_public

    store.add_texts(texts=[text], metadatas=[meta])
