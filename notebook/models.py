"""Domain models for the Interactive Code Notebook."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ChunkRef:
    """Lightweight reference to a code chunk found during research."""

    chunk_id: int
    file_path: str
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
        }
        if self.symbol:
            d["symbol"] = self.symbol
        if self.start_line is not None:
            d["start_line"] = self.start_line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkRef:
        return cls(
            chunk_id=int(data["chunk_id"]),
            file_path=str(data["file_path"]),
            symbol=data.get("symbol"),
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
        )


@dataclass
class NotebookEntry:
    """A single research finding in the notebook.

    Attributes:
        id:             Unique entry identifier (UUID).
        timestamp:      When this entry was created.
        query:          The original research question.
        summary:        LLM-synthesised finding.
        source_chunks:  Referenced code locations.
        tags:           User- or auto-generated tags.
        connections:    IDs of related entries (auto-detected or manual).
        confidence:     How well the question was answered (0-1).
        note:           Optional user-added manual annotation.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    query: str = ""
    summary: str = ""
    source_chunks: list[ChunkRef] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    confidence: float = 0.0
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "query": self.query,
            "summary": self.summary,
            "source_chunks": [c.to_dict() for c in self.source_chunks],
            "tags": self.tags,
            "connections": self.connections,
            "confidence": self.confidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotebookEntry:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else datetime.now(timezone.utc)
            ),
            query=data.get("query", ""),
            summary=data.get("summary", ""),
            source_chunks=[
                ChunkRef.from_dict(c) for c in (data.get("source_chunks") or [])
            ],
            tags=data.get("tags") or [],
            connections=data.get("connections") or [],
            confidence=float(data.get("confidence", 0.0)),
            note=data.get("note"),
        )


@dataclass
class Notebook:
    """A persistent research journal.

    Stored as a JSON file in ``.chunkhound/notebooks/<slug>.json``.
    """

    name: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    entries: list[NotebookEntry] = field(default_factory=list)
    synthesis: str | None = None

    @property
    def slug(self) -> str:
        """Filesystem-safe name derived from the notebook name."""
        import re
        slug = re.sub(r"[^\w\s-]", "", self.name.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")
        return slug[:60] or "untitled"

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def add_entry(self, entry: NotebookEntry) -> None:
        self.entries.append(entry)

    def get_entry(self, entry_id: str) -> NotebookEntry | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def all_tags(self) -> list[str]:
        """Return deduplicated sorted list of all tags."""
        tags: set[str] = set()
        for e in self.entries:
            tags.update(e.tags)
        return sorted(tags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "entries": [e.to_dict() for e in self.entries],
            "synthesis": self.synthesis,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Notebook:
        return cls(
            name=data.get("name", "Untitled"),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else datetime.now(timezone.utc)
            ),
            entries=[
                NotebookEntry.from_dict(e) for e in (data.get("entries") or [])
            ],
            synthesis=data.get("synthesis"),
        )

    def to_markdown(self) -> str:
        """Export the notebook as a readable markdown document."""
        lines: list[str] = [
            f"# {self.name}",
            "",
            f"*Created: {self.created_at.strftime('%Y-%m-%d %H:%M UTC')} "
            f"| {self.entry_count} entries*",
            "",
        ]

        if self.synthesis:
            lines.extend(["## Synthesis", "", self.synthesis, ""])

        for i, entry in enumerate(self.entries, 1):
            lines.append(f"## Entry {i}: {entry.query}")
            lines.append("")
            if entry.tags:
                lines.append(f"*Tags: {', '.join(entry.tags)}*")
                lines.append("")
            lines.append(entry.summary)
            lines.append("")
            if entry.source_chunks:
                lines.append("**Sources:**")
                for ref in entry.source_chunks[:5]:
                    symbol = f" ({ref.symbol})" if ref.symbol else ""
                    line_info = (
                        f":{ref.start_line}-{ref.end_line}"
                        if ref.start_line
                        else ""
                    )
                    lines.append(f"- `{ref.file_path}{line_info}`{symbol}")
                lines.append("")
            if entry.note:
                lines.append(f"> **Note:** {entry.note}")
                lines.append("")
            if entry.connections:
                lines.append(
                    f"*Connected to: {len(entry.connections)} other entries*"
                )
                lines.append("")

        return "\n".join(lines)