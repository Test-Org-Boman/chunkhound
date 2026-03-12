"""Temporal Code Intelligence for ChunkHound.

Enriches chunks with git blame metadata during indexing: last author,
change frequency, and churn score.  Exposes search filters by recency
and author, plus a dedicated ``history`` command for hotspot analysis.
"""

from chunkhound.history.models import ChunkTemporalMeta, TemporalQuery
from chunkhound.history.annotator import GitAnnotator
from chunkhound.history.service import HistoryService

__all__: list[str] = [
    "ChunkTemporalMeta",
    "GitAnnotator",
    "HistoryService",
    "TemporalQuery",
]