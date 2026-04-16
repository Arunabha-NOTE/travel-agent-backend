"""MiniLM sentence-transformer embeddings for LangChain."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from langchain_core.embeddings import Embeddings


class MiniLMEmbeddings(Embeddings):
    """LangChain Embeddings wrapper for all-MiniLM-L6-v2.

    Uses sentence-transformers locally — no API key required.
    Embedding dimension: 384.
    """

    model_name: str = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        model = self._get_model()
        embedding = model.encode([text], convert_to_numpy=True, show_progress_bar=False)
        return embedding[0].tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> MiniLMEmbeddings:
    """Return a cached MiniLM embeddings instance."""
    return MiniLMEmbeddings()
