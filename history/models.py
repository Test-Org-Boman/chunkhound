"""Domain models for Temporal Code Intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ChunkTemporalMeta:
    """Git-derived temporal metadata for a single chunk.

    Computed during indexing by ``GitAnnotator`` and stored in the
    ``chunk_temporal`` table.

    Attributes:
        chunk_id:             FK to chunks.id
        last_modified_date:   Most recent commit touching this chunk's lines.
        last_author:          Author of the most recent commit.
        change_count_30d:     Commits touching these lines in last 30 days.
        change_count_90d:     Commits touching these lines in last 90 days.
        first_authored_date:  Earliest commit touching these lines.
        contributors:         Unique authors who have modified these lines.
        churn_score:          Normalised 0-1 (higher = more frequently changed).
    """

    chunk_id: int
    last_modified_date: datetime | None = None
    last_author: str | None = None
    change_count_30d: int = 0
    change_count_90d: int = 0
    first_authored_date: datetime | None = None
    contributors: list[str] = field(default_factory=list)
    churn_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "last_modified_date": (
                self.last_modified_date.isoformat()
                if self.last_modified_date
                else None
            ),
            "last_author": self.last_author,
            "change_count_30d": self.change_count_30d,
            "change_count_90d": self.change_count_90d,
            "first_authored_date": (
                self.first_authored_date.isoformat()
                if self.first_authored_date
                else None
            ),
            "contributors": self.contributors,
            "churn_score": self.churn_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkTemporalMeta:
        def _parse_dt(val: Any) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(str(val))

        return cls(
            chunk_id=int(data["chunk_id"]),
            last_modified_date=_parse_dt(data.get("last_modified_date")),
            last_author=data.get("last_author"),
            change_count_30d=int(data.get("change_count_30d", 0)),
            change_count_90d=int(data.get("change_count_90d", 0)),
            first_authored_date=_parse_dt(data.get("first_authored_date")),
            contributors=data.get("contributors") or [],
            churn_score=float(data.get("churn_score", 0.0)),
        )


@dataclass
class TemporalQuery:
    """Parameters for history-filtered searches."""

    changed_since: str | None = None  # e.g. "2w", "30d", "2025-01-01"
    changed_by: str | None = None     # author name or email substring
    min_churn: float | None = None    # minimum churn_score threshold
    sort_by: str = "relevance"        # "relevance" | "recency" | "churn"


@dataclass
class HotspotEntry:
    """A single entry in the hotspot report."""

    file_path: str
    symbol: str | None
    chunk_id: int
    churn_score: float
    change_count_90d: int
    last_author: str | None
    last_modified_date: datetime | None
    contributors: list[str] = field(default_factory=list)


@dataclass
class OwnershipEntry:
    """Ownership summary for a file or directory."""

    file_path: str
    primary_author: str | None
    total_contributors: int
    commit_share: dict[str, float] = field(default_factory=dict)  # author → %