"""ConnectionDetector – auto-links notebook entries via embedding similarity.

When a new entry is added, computes cosine similarity between its summary
embedding and all existing entries.  Entries above a threshold are
linked via the ``connections`` field.
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

from chunkhound.notebook.models import Notebook, NotebookEntry


class ConnectionDetector:
    """Detect thematic connections between notebook entries."""

    def __init__(
        self,
        embed_fn: Any | None = None,
        threshold: float = 0.75,
    ) -> None:
        """
        Args:
            embed_fn: Async callable ``(texts: list[str]) -> list[list[float]]``.
                      Typically ``embedding_manager.get_provider().embed``.
            threshold: Minimum cosine similarity to create a connection.
        """
        self._embed = embed_fn
        self._threshold = threshold
        # Cache: entry_id → embedding vector
        self._cache: dict[str, list[float]] = {}

    async def detect_connections(
        self,
        new_entry: NotebookEntry,
        notebook: Notebook,
    ) -> list[str]:
        """Find existing entries connected to the new entry.

        Returns a list of entry IDs that are thematically similar.
        Also updates the new entry's ``connections`` field in place.
        """
        if self._embed is None:
            logger.debug("Notebook: no embedding function, skipping connection detection")
            return []

        existing = [e for e in notebook.entries if e.id != new_entry.id]
        if not existing:
            return []

        # Compute embeddings for all summaries (batch for efficiency)
        texts_to_embed: list[str] = []
        entry_ids: list[str] = []

        # New entry summary
        texts_to_embed.append(new_entry.summary or new_entry.query)

        # Existing entries (skip if already cached)
        uncached_indices: list[int] = []
        for e in existing:
            if e.id in self._cache:
                continue
            texts_to_embed.append(e.summary or e.query)
            uncached_indices.append(len(texts_to_embed) - 1)
            entry_ids.append(e.id)

        try:
            embeddings = await self._embed(texts_to_embed)
        except Exception as exc:
            logger.warning(f"Notebook: embedding failed for connection detection: {exc}")
            return []

        # Store results
        new_vec = embeddings[0]
        self._cache[new_entry.id] = new_vec

        for idx, eid in zip(uncached_indices, entry_ids):
            self._cache[eid] = embeddings[idx]

        # Compute similarities
        connected: list[str] = []
        for e in existing:
            other_vec = self._cache.get(e.id)
            if other_vec is None:
                continue
            sim = _cosine_similarity(new_vec, other_vec)
            if sim >= self._threshold:
                connected.append(e.id)
                # Bidirectional: also add new entry to the existing entry's connections
                if new_entry.id not in e.connections:
                    e.connections.append(new_entry.id)

        new_entry.connections.extend(connected)
        return connected

    def invalidate_cache(self, entry_id: str) -> None:
        """Remove a cached embedding when an entry is deleted."""
        self._cache.pop(entry_id, None)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)