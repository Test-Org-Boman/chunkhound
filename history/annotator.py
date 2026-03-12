"""GitAnnotator – extracts temporal metadata from git log / blame.

Runs during indexing (after chunks are extracted, before embedding)
to enrich each chunk with authorship and change-frequency data.
"""

from __future__ import annotations

import math
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.history.models import ChunkTemporalMeta


class GitAnnotator:
    """Compute per-chunk temporal metadata from git history."""

    def __init__(self, project_root: Path, *, timeout_s: float = 10.0) -> None:
        self._root = project_root
        self._timeout = timeout_s
        # Cache: file_path → list of (line_no, author, date) from blame
        self._blame_cache: dict[str, list[tuple[int, str, datetime]]] = {}
        # Cache: file_path → list of (author, date, lines_changed) from log
        self._log_cache: dict[str, list[tuple[str, datetime, set[int]]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def annotate_chunks(
        self,
        file_path: str,
        chunks: list[dict[str, Any]],
    ) -> list[ChunkTemporalMeta]:
        """Annotate a list of chunks from one file with temporal metadata.

        Args:
            file_path: Relative path to the file (from project root).
            chunks:    Chunk dicts with ``id``, ``start_line``, ``end_line``.

        Returns:
            One ``ChunkTemporalMeta`` per chunk.
        """
        blame_lines = self._get_blame(file_path)
        log_entries = self._get_log(file_path)
        now = datetime.now(timezone.utc)

        results: list[ChunkTemporalMeta] = []
        for chunk in chunks:
            chunk_id = chunk.get("id") or chunk.get("chunk_id")
            if chunk_id is None:
                continue
            start = int(chunk.get("start_line", 1))
            end = int(chunk.get("end_line", start))

            meta = self._compute_meta(
                chunk_id=int(chunk_id),
                start_line=start,
                end_line=end,
                blame_lines=blame_lines,
                log_entries=log_entries,
                now=now,
            )
            results.append(meta)

        return results

    # ------------------------------------------------------------------
    # Git blame
    # ------------------------------------------------------------------

    def _get_blame(
        self, file_path: str
    ) -> list[tuple[int, str, datetime]]:
        if file_path in self._blame_cache:
            return self._blame_cache[file_path]

        result: list[tuple[int, str, datetime]] = []
        try:
            proc = subprocess.run(
                [
                    "git", "blame", "--porcelain", "--", file_path,
                ],
                capture_output=True,
                text=True,
                cwd=str(self._root),
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                self._blame_cache[file_path] = []
                return []

            current_author = ""
            current_time = 0
            line_no = 0

            for line in proc.stdout.splitlines():
                if line.startswith("author "):
                    current_author = line[7:].strip()
                elif line.startswith("author-time "):
                    try:
                        current_time = int(line[12:].strip())
                    except ValueError:
                        current_time = 0
                elif line.startswith("\t"):
                    # Content line — we've now seen all header fields.
                    line_no += 1
                    dt = datetime.fromtimestamp(current_time, tz=timezone.utc)
                    result.append((line_no, current_author, dt))

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.debug(f"History: git blame failed for {file_path}: {exc}")

        self._blame_cache[file_path] = result
        return result

    # ------------------------------------------------------------------
    # Git log
    # ------------------------------------------------------------------

    def _get_log(
        self, file_path: str
    ) -> list[tuple[str, datetime, set[int]]]:
        if file_path in self._log_cache:
            return self._log_cache[file_path]

        result: list[tuple[str, datetime, set[int]]] = []
        try:
            proc = subprocess.run(
                [
                    "git", "log", "--follow", "--format=%an|%at",
                    "--numstat", "--", file_path,
                ],
                capture_output=True,
                text=True,
                cwd=str(self._root),
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                self._log_cache[file_path] = []
                return []

            author = ""
            commit_dt = datetime.now(timezone.utc)

            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "|" in line and not line[0].isdigit():
                    parts = line.split("|", 1)
                    author = parts[0].strip()
                    try:
                        ts = int(parts[1].strip())
                        commit_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    except (ValueError, IndexError):
                        pass
                    # Simplified: we don't track exact changed lines from log,
                    # only from blame.  Log gives us commit frequency.
                    result.append((author, commit_dt, set()))

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.debug(f"History: git log failed for {file_path}: {exc}")

        self._log_cache[file_path] = result
        return result

    # ------------------------------------------------------------------
    # Compute per-chunk metadata
    # ------------------------------------------------------------------

    def _compute_meta(
        self,
        chunk_id: int,
        start_line: int,
        end_line: int,
        blame_lines: list[tuple[int, str, datetime]],
        log_entries: list[tuple[str, datetime, set[int]]],
        now: datetime,
    ) -> ChunkTemporalMeta:
        # Filter blame to lines in this chunk's range
        chunk_blame = [
            (ln, author, dt)
            for ln, author, dt in blame_lines
            if start_line <= ln <= end_line
        ]

        if not chunk_blame:
            return ChunkTemporalMeta(chunk_id=chunk_id)

        # Derived fields from blame
        authors: dict[str, int] = defaultdict(int)
        dates: list[datetime] = []
        for _ln, author, dt in chunk_blame:
            authors[author] += 1
            dates.append(dt)

        dates.sort()
        most_recent = dates[-1]
        earliest = dates[0]
        last_author = max(
            chunk_blame, key=lambda x: x[2]
        )[1]
        contributors = list(authors.keys())

        # Count commits in 30d / 90d windows using log entries
        cutoff_30d = now - timedelta(days=30)
        cutoff_90d = now - timedelta(days=90)
        count_30d = sum(1 for _, dt, _ in log_entries if dt >= cutoff_30d)
        count_90d = sum(1 for _, dt, _ in log_entries if dt >= cutoff_90d)

        # Churn score: exponential-decay weighted commit frequency (90d window)
        churn = self._compute_churn(log_entries, now)

        return ChunkTemporalMeta(
            chunk_id=chunk_id,
            last_modified_date=most_recent,
            last_author=last_author,
            change_count_30d=count_30d,
            change_count_90d=count_90d,
            first_authored_date=earliest,
            contributors=contributors,
            churn_score=churn,
        )

    @staticmethod
    def _compute_churn(
        log_entries: list[tuple[str, datetime, set[int]]],
        now: datetime,
        decay_half_life_days: float = 30.0,
    ) -> float:
        """Compute a normalised churn score using exponential decay.

        More recent commits contribute more to the score.  The result
        is clamped to [0, 1] via a sigmoid-like mapping.
        """
        if not log_entries:
            return 0.0

        raw = 0.0
        for _, dt, _ in log_entries:
            age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
            weight = math.exp(-0.693 * age_days / decay_half_life_days)
            raw += weight

        # Map raw score to [0, 1] using tanh
        return min(1.0, math.tanh(raw / 5.0))