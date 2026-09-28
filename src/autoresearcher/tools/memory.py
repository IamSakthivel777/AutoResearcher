"""Small deterministic in-process vector index used by the Phase 2 tools."""

from __future__ import annotations

import hashlib
import math
import re
import threading

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[str] = Field(min_length=1, max_length=1_000)
    metadata: list[dict[str, str]] | None = None
    namespace: str = Field(default="default", min_length=1, max_length=100)

    @model_validator(mode="after")
    def matching_metadata(self) -> StoreInput:
        if self.metadata is not None and len(self.metadata) != len(self.texts):
            raise ValueError("metadata length must match texts length")
        return self


class StoredDocument(BaseModel):
    id: str
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)
    source_url: HttpUrl | None = None


class RetrievalResult(StoredDocument):
    score: float = Field(ge=-1, le=1)


class RetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)
    k: int = Field(default=5, ge=1, le=50)
    namespace: str = Field(default="default", min_length=1, max_length=100)


_DIMENSIONS = 128
_INDEX: dict[str, dict[str, tuple[StoredDocument, list[float]]]] = {}
_LOCK = threading.RLock()


def _embedding(text: str) -> list[float]:
    vector = [0.0] * _DIMENSIONS
    for token in re.findall(r"[\w'-]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % _DIMENSIONS
        vector[index] += -1.0 if digest[4] & 1 else 1.0
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


def embed_and_store(
    texts: list[str],
    *,
    metadata: list[dict[str, str]] | None = None,
    namespace: str = "default",
) -> list[str]:
    """Embed and store text locally using stable hashed bag-of-words vectors."""
    inputs = StoreInput(texts=texts, metadata=metadata, namespace=namespace)
    ids: list[str] = []
    with _LOCK:
        bucket = _INDEX.setdefault(inputs.namespace, {})
        for index, text in enumerate(inputs.texts):
            item_metadata = inputs.metadata[index] if inputs.metadata else {}
            digest = hashlib.sha256(
                f"{inputs.namespace}\0{text}\0{sorted(item_metadata.items())}".encode()
            ).hexdigest()[:20]
            document_id = f"D{digest}"
            source_url = item_metadata.get("source_url")
            document = StoredDocument.model_validate(
                {
                    "id": document_id,
                    "text": text,
                    "metadata": item_metadata,
                    "source_url": source_url,
                }
            )
            bucket[document_id] = (document, _embedding(text))
            ids.append(document_id)
    return ids


def retrieve_similar(
    query: str,
    *,
    k: int = 5,
    namespace: str = "default",
) -> list[RetrievalResult]:
    """Return the most similar locally stored texts by cosine similarity."""
    inputs = RetrievalInput(query=query, k=k, namespace=namespace)
    query_vector = _embedding(inputs.query)
    with _LOCK:
        items = list(_INDEX.get(inputs.namespace, {}).values())
    ranked = sorted(
        (
            (sum(left * right for left, right in zip(query_vector, vector, strict=True)), document)
            for document, vector in items
        ),
        key=lambda item: item[0],
        reverse=True,
    )[: inputs.k]
    return [
        RetrievalResult(
            **document.model_dump(),
            score=max(-1.0, min(1.0, round(score, 6))),
        )
        for score, document in ranked
    ]
