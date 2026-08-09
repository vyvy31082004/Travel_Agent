from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Protocol, Sequence

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from memory.long_term import TravelMemory
from settings import Settings


class EmbeddingError(RuntimeError):
    """Raised when embedding generation or validation fails safely."""


class MemoryEmbeddingProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]:
        """Embed one query string."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document strings."""


@dataclass(frozen=True)
class MemoryEmbeddingConfig:
    model: str
    dims: int


class GoogleMemoryEmbeddingProvider:
    def __init__(self, *, model: str) -> None:
        self._embeddings = GoogleGenerativeAIEmbeddings(model=model)

    async def embed_query(self, text: str) -> list[float]:
        return list(await self._embeddings.aembed_query(text))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return [list(vector) for vector in await self._embeddings.aembed_documents(list(texts))]


class MemoryEmbeddingService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: MemoryEmbeddingProvider | None = None,
    ) -> None:
        self._config = MemoryEmbeddingConfig(
            model=settings.long_term_memory_embedding_model,
            dims=settings.long_term_memory_vector_dims,
        )
        self._provider = provider

    @property
    def provider(self) -> MemoryEmbeddingProvider:
        if self._provider is None:
            self._provider = GoogleMemoryEmbeddingProvider(model=self._config.model)
        return self._provider

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def dims(self) -> int:
        return self._config.dims

    async def embed_query(self, text: str) -> list[float]:
        vector = await self.provider.embed_query(text)
        return validate_embedding_dimensions(vector, expected_dims=self._config.dims)

    async def embed_memory(self, memory: TravelMemory) -> list[float]:
        vectors = await self.provider.embed_documents([memory_embedding_text(memory)])
        if len(vectors) != 1:
            raise EmbeddingError("embedding provider returned an unexpected document count")
        return validate_embedding_dimensions(vectors[0], expected_dims=self._config.dims)


def validate_embedding_dimensions(
    vector: Sequence[float],
    *,
    expected_dims: int,
) -> list[float]:
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("embedding vector must contain numeric values") from exc
    if len(values) != expected_dims:
        raise EmbeddingError(
            f"embedding dimension mismatch: expected {expected_dims}, got {len(values)}"
        )
    if any(not math.isfinite(value) for value in values):
        raise EmbeddingError("embedding vector must contain only finite values")
    return values


def memory_embedding_text(memory: TravelMemory) -> str:
    parts = [
        f"memory: {memory.memory_text}",
        f"category: {memory.category}",
        f"domain: {memory.domain}",
    ]
    if memory.condition:
        parts.append(f"condition: {memory.condition}")
    return "\n".join(parts)


def memory_content_hash(memory: TravelMemory, *, model: str) -> str:
    payload = {
        "model": model,
        "memory_text": memory.memory_text,
        "category": str(memory.category),
        "domain": str(memory.domain),
        "condition": memory.condition or "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def vector_literal(vector: Sequence[float]) -> str:
    # psycopg does not adapt pgvector without the optional Python pgvector package.
    # This literal is still passed as a query parameter and cast to vector in SQL.
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
