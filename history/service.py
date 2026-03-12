"""HistoryService – high-level API for temporal code intelligence.

Consumed by:
* CLI ``chunkhound history`` subcommand
* MCP search tools (via ``--changed-since`` / ``--author`` filters)
* Deep research synthesis (adds "Recent Activity" section)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.history.annotator import GitAnnotator
from chunkhound.history.models import ChunkTemporalMeta, HotspotEntry, TemporalQuery
from chunkhound.history.storage import (
    filter_chunks_by_temporal,
    get_hotspots,
    get_ownership,
    upsert_temporal_batch,
)


class HistoryService:
    """Provides temporal queries and indexing-time annotation."""

    def __init__(
        self,
        execute_fn: Any,
        project_root: Path,
    ) -> None:
        self._exec = execute_fn
        self._project_root = project_root
        self._annotator = GitAnnotator(project_root)

    # ------------------------------------------------------------------
    # Indexing-time annotation
    # ------------------------------------------------------------------

    def annotate_and_store(
        self,
        file_path: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Annotate chunks for a file and persist temporal metadata.

        Call this after chunks are inserted into the DB but before
        embedding generation.

        Returns:
            Number of chunks annotated.
        """
        metas = self._annotator.annotate_chunks(file_path, chunks)
        return upsert_temporal_batch(self._exec, metas)

    # ------------------------------------------------------------------
    # Query-time filtering
    # ------------------------------------------------------------------

    def filter_results(
        self,
        chunk_ids: list[int],
        temporal: TemporalQuery,
    ) -> list[int]:
        """Apply temporal filters to a set of search results."""
        return filter_chunks_by_temporal(
            self._exec,
            chunk_ids,
            changed_since=temporal.changed_since,
            changed_by=temporal.changed_by,
            min_churn=temporal.min_churn,
        )

    # ------------------------------------------------------------------
    # Hotspot analysis
    # ------------------------------------------------------------------

    def get_hotspots(
        self, top_k: int = 20, path_filter: str | None = None
    ) -> list[HotspotEntry]:
        """Return the most actively changed code areas."""
        rows = get_hotspots(self._exec, top_k, path_filter)
        return [
            HotspotEntry(
                file_path=r.get("file_path", ""),
                symbol=r.get("symbol"),
                chunk_id=int(r["chunk_id"]),
                churn_score=float(r.get("churn_score", 0)),
                change_count_90d=int(r.get("change_count_90d", 0)),
                last_author=r.get("last_author"),
                last_modified_date=r.get("last_modified_date"),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Ownership analysis
    # ------------------------------------------------------------------

    def get_ownership(self, path_filter: str) -> list[dict[str, Any]]:
        """Return authorship breakdown for a path."""
        return get_ownership(self._exec, path_filter)

    # ------------------------------------------------------------------
    # Research integration
    # ------------------------------------------------------------------

    def format_recent_activity_section(
        self, chunk_ids: list[int], top_k: int = 5
    ) -> str:
        """Generate a 'Recent Activity' markdown section for deep research.

        Appended to synthesis output to give AI agents temporal context.
        """
        if not chunk_ids:
            return ""

        id_list = ", ".join(str(c) for c in chunk_ids)
        rows = self._exec(
            f"SELECT ct.*, c.symbol, f.path AS file_path "
            f"FROM chunk_temporal ct "
            f"JOIN chunks c ON c.id = ct.chunk_id "
            f"JOIN files f ON f.id = c.file_id "
            f"WHERE ct.chunk_id IN ({id_list}) "
            f"ORDER BY ct.churn_score DESC LIMIT {top_k}"
        )

        if not rows:
            return ""

        lines = ["## Recent Activity", ""]
        for row in rows:
            symbol = row.get("symbol") or "unknown"
            path = row.get("file_path") or ""
            author = row.get("last_author") or "unknown"
            churn = float(row.get("churn_score", 0))
            count_90d = int(row.get("change_count_90d", 0))
            stability = "actively changing" if churn > 0.5 else "stable"

            lines.append(
                f"- **{symbol}** (`{path}`): {stability} "
                f"({count_90d} commits in 90d, last by {author}, "
                f"churn={churn:.2f})"
            )

        return "\n".join(lines)


# ------------------------------------------------------------------
# CLI subcommand
# ------------------------------------------------------------------

def add_history_subparser(subparsers: Any) -> None:
    """Register the ``history`` subcommand."""
    parser = subparsers.add_parser(
        "history",
        help="Explore temporal code intelligence (hotspots, ownership, timelines)",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File or directory path to analyse",
    )
    parser.add_argument(
        "--hotspots",
        action="store_true",
        help="Show most frequently changed code areas",
    )
    parser.add_argument(
        "--ownership",
        action="store_true",
        help="Show authorship breakdown",
    )
    parser.add_argument(
        "--since",
        help="Filter to changes after this date (e.g. 2025-01-01, 2w, 30d)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of results to show (default: 20)",
    )
    parser.set_defaults(func=_run_history_command)


def _run_history_command(args: argparse.Namespace) -> None:
    """Entry point for ``chunkhound history``."""
    from chunkhound.core.config.config import Config
    from chunkhound.database_factory import create_services

    config = Config(args=args)
    db_path = config.database.get_db_path()
    services = create_services(db_path, config)
    target_dir = config.target_dir or Path(".").resolve()

    history_svc = HistoryService(
        execute_fn=services.provider.execute_query,
        project_root=target_dir,
    )

    if args.hotspots:
        hotspots = history_svc.get_hotspots(top_k=args.top, path_filter=args.path)
        if not hotspots:
            print("No hotspots found. Run 'chunkhound index' first.", file=sys.stderr)
            return
        print(f"{'Churn':>6}  {'90d':>4}  {'Author':<20}  {'Symbol':<30}  Path")
        print("-" * 90)
        for h in hotspots:
            print(
                f"{h.churn_score:6.3f}  {h.change_count_90d:4d}  "
                f"{(h.last_author or 'unknown'):<20}  "
                f"{(h.symbol or '-'):<30}  {h.file_path}"
            )
        return

    if args.ownership:
        rows = history_svc.get_ownership(args.path)
        if not rows:
            print("No ownership data found.", file=sys.stderr)
            return
        print(f"{'Author':<25}  {'Chunks':>6}  Path")
        print("-" * 70)
        for row in rows:
            print(
                f"{(row.get('last_author') or 'unknown'):<25}  "
                f"{row.get('chunk_count', 0):6d}  "
                f"{row.get('file_path', '')}"
            )
        return

    # Default: show recent activity summary
    section = history_svc.format_recent_activity_section(
        chunk_ids=[],  # Would need chunk IDs from search; show general hotspots
        top_k=args.top,
    )
    if section:
        print(section)
    else:
        hotspots = history_svc.get_hotspots(top_k=args.top, path_filter=args.path)
        if hotspots:
            for h in hotspots:
                print(f"  {h.churn_score:.2f}  {h.symbol or '-':<30} {h.file_path}")
        else:
            print("No temporal data found. Run 'chunkhound index' first.")