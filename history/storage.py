"""History storage – DuckDB schema and queries for chunk_temporal table."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from chunkhound.history.models import ChunkTemporalMeta


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------

TEMPORAL_TABLE_DDL = """\
CREATE TABLE IF NOT EXISTS chunk_temporal (
    chunk_id             BIGINT PRIMARY KEY,
    last_modified_date   TIMESTAMP,
    last_author          TEXT,
    change_count_30d     INTEGER DEFAULT 0,
    change_count_90d     INTEGER DEFAULT 0,
    first_authored_date  TIMESTAMP,
    contributors         JSON,
    churn_score          FLOAT DEFAULT 0.0
);
"""

TEMPORAL_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_temporal_author ON chunk_temporal (last_author);",
    "CREATE INDEX IF NOT EXISTS idx_temporal_churn ON chunk_temporal (churn_score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_temporal_modified ON chunk_temporal (last_modified_date DESC);",
]


def create_temporal_schema(execute_fn: Any) -> None:
    """Create the chunk_temporal table idempotently."""
    execute_fn(TEMPORAL_TABLE_DDL)
    for ddl in TEMPORAL_INDEXES_DDL:
        execute_fn(ddl)
    logger.debug("History: chunk_temporal schema ensured.")


# ------------------------------------------------------------------
# Write operations
# ------------------------------------------------------------------

def upsert_temporal_batch(
    execute_fn: Any,
    metas: list[ChunkTemporalMeta],
    batch_size: int = 500,
) -> int:
    """Upsert temporal metadata for chunks.  Returns rows affected."""
    if not metas:
        return 0

    total = 0
    for i in range(0, len(metas), batch_size):
        batch = metas[i : i + batch_size]
        values_parts: list[str] = []
        for m in batch:
            lmd = f"'{m.last_modified_date.isoformat()}'" if m.last_modified_date else "NULL"
            fad = f"'{m.first_authored_date.isoformat()}'" if m.first_authored_date else "NULL"
            la = f"'{_escape(m.last_author)}'" if m.last_author else "NULL"
            contribs = f"'{_escape(json.dumps(m.contributors))}'"
            values_parts.append(
                f"({m.chunk_id}, {lmd}, {la}, {m.change_count_30d}, "
                f"{m.change_count_90d}, {fad}, {contribs}, {m.churn_score})"
            )

        values_clause = ", ".join(values_parts)
        sql = (
            "INSERT OR REPLACE INTO chunk_temporal "
            "(chunk_id, last_modified_date, last_author, change_count_30d, "
            "change_count_90d, first_authored_date, contributors, churn_score) "
            f"VALUES {values_clause}"
        )
        execute_fn(sql)
        total += len(batch)

    return total


def delete_temporal_for_chunks(execute_fn: Any, chunk_ids: list[int]) -> None:
    """Remove temporal metadata for deleted chunks."""
    if not chunk_ids:
        return
    id_list = ", ".join(str(c) for c in chunk_ids)
    execute_fn(f"DELETE FROM chunk_temporal WHERE chunk_id IN ({id_list})")


# ------------------------------------------------------------------
# Read operations
# ------------------------------------------------------------------

def get_hotspots(
    execute_fn: Any,
    top_k: int = 20,
    path_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return the most frequently changed chunks."""
    path_clause = ""
    if path_filter:
        path_clause = f"AND f.path LIKE '{_escape(path_filter)}%'"
    sql = (
        "SELECT ct.*, c.symbol, f.path AS file_path "
        "FROM chunk_temporal ct "
        "JOIN chunks c ON c.id = ct.chunk_id "
        "JOIN files f ON f.id = c.file_id "
        f"WHERE ct.churn_score > 0 {path_clause} "
        f"ORDER BY ct.churn_score DESC LIMIT {top_k}"
    )
    return execute_fn(sql)


def get_ownership(
    execute_fn: Any,
    path_filter: str,
) -> list[dict[str, Any]]:
    """Return authorship breakdown for files under a path."""
    sql = (
        "SELECT f.path AS file_path, ct.last_author, "
        "ct.contributors, ct.churn_score, "
        "COUNT(*) as chunk_count "
        "FROM chunk_temporal ct "
        "JOIN chunks c ON c.id = ct.chunk_id "
        "JOIN files f ON f.id = c.file_id "
        f"WHERE f.path LIKE '{_escape(path_filter)}%' "
        "GROUP BY f.path, ct.last_author, ct.contributors, ct.churn_score "
        "ORDER BY f.path"
    )
    return execute_fn(sql)


def filter_chunks_by_temporal(
    execute_fn: Any,
    chunk_ids: list[int],
    changed_since: str | None = None,
    changed_by: str | None = None,
    min_churn: float | None = None,
) -> list[int]:
    """Filter a set of chunk IDs by temporal criteria."""
    if not chunk_ids:
        return []

    id_list = ", ".join(str(c) for c in chunk_ids)
    conditions = [f"ct.chunk_id IN ({id_list})"]

    if changed_since:
        date_expr = _parse_since(changed_since)
        if date_expr:
            conditions.append(f"ct.last_modified_date >= '{date_expr}'")

    if changed_by:
        conditions.append(f"ct.last_author LIKE '%{_escape(changed_by)}%'")

    if min_churn is not None:
        conditions.append(f"ct.churn_score >= {min_churn}")

    where = " AND ".join(conditions)
    sql = f"SELECT ct.chunk_id FROM chunk_temporal ct WHERE {where}"
    rows = execute_fn(sql)
    return [int(r["chunk_id"]) for r in rows]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _escape(value: str) -> str:
    return value.replace("'", "''")


def _parse_since(value: str) -> str | None:
    """Parse relative date strings like '2w', '30d', or ISO dates."""
    from datetime import datetime, timedelta, timezone

    value = value.strip()

    if value.endswith("d"):
        try:
            days = int(value[:-1])
            dt = datetime.now(timezone.utc) - timedelta(days=days)
            return dt.isoformat()
        except ValueError:
            pass

    if value.endswith("w"):
        try:
            weeks = int(value[:-1])
            dt = datetime.now(timezone.utc) - timedelta(weeks=weeks)
            return dt.isoformat()
        except ValueError:
            pass

    # Try ISO date
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError:
        pass

    return None