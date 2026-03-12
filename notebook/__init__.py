"""Interactive Code Notebook for ChunkHound.

A persistent workspace that accumulates research findings across queries.
Auto-detects connections between entries via embedding similarity.
Generates cross-entry synthesis documents on demand.
"""

from chunkhound.notebook.models import Notebook, NotebookEntry
from chunkhound.notebook.store import NotebookStore
from chunkhound.notebook.connector import ConnectionDetector
from chunkhound.notebook.synthesizer import NotebookSynthesizer

__all__: list[str] = [
    "ConnectionDetector",
    "Notebook",
    "NotebookEntry",
    "NotebookStore",
    "NotebookSynthesizer",
]