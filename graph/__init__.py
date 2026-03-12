"""Dependency Graph Explorer for ChunkHound.

Extracts import, call, and inheritance edges during parsing and stores
them in the database.  A ``code_graph`` MCP tool traverses relationships
upstream or downstream.  Deep research uses graph expansion to find
structurally connected chunks that vector search misses.
"""

from chunkhound.graph.models import Edge, EdgeType, GraphQuery, GraphResult
from chunkhound.graph.service import GraphService

__all__: list[str] = [
    "Edge",
    "EdgeType",
    "GraphQuery",
    "GraphResult",
    "GraphService",
]