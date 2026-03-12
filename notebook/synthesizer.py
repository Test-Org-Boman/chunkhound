"""NotebookSynthesizer – cross-entry synthesis using LLM manager.

Groups notebook entries by auto-detected connection clusters, then
asks the synthesis LLM to produce a coherent document with themes,
cross-references, and a "gaps" section.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger

from chunkhound.interfaces.llm_provider import LLMProvider
from chunkhound.notebook.models import Notebook, NotebookEntry


class NotebookSynthesizer:
    """Generate coherent documents from accumulated research entries."""

    def __init__(self, synthesis_provider: LLMProvider) -> None:
        self._provider = synthesis_provider

    async def synthesize(
        self,
        notebook: Notebook,
        focus: str | None = None,
        max_completion_tokens: int = 8192,
    ) -> str:
        """Generate a cross-entry synthesis document.

        Args:
            notebook: The notebook to synthesize.
            focus: Optional focusing question (e.g. "How do auth and rate
                   limiting interact?").
            max_completion_tokens: Token budget for the LLM response.

        Returns:
            Markdown synthesis document.
        """
        if not notebook.entries:
            return "No entries to synthesize."

        # Group entries into clusters based on connections
        clusters = self._cluster_entries(notebook.entries)

        # Build the synthesis prompt
        prompt = self._build_prompt(notebook, clusters, focus)

        try:
            response = await self._provider.complete(
                prompt=prompt,
                system=self._system_prompt(),
                max_completion_tokens=max_completion_tokens,
            )
            synthesis = response.content
        except Exception as exc:
            logger.error(f"Notebook synthesis failed: {exc}")
            synthesis = f"Synthesis failed: {exc}"

        # Store on the notebook object
        notebook.synthesis = synthesis
        return synthesis

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster_entries(
        self, entries: list[NotebookEntry]
    ) -> list[list[NotebookEntry]]:
        """Group entries by their connection graph (connected components)."""
        id_to_entry: dict[str, NotebookEntry] = {e.id: e for e in entries}
        visited: set[str] = set()
        clusters: list[list[NotebookEntry]] = []

        for entry in entries:
            if entry.id in visited:
                continue

            # BFS to find connected component
            cluster: list[NotebookEntry] = []
            queue = [entry.id]
            while queue:
                eid = queue.pop(0)
                if eid in visited:
                    continue
                visited.add(eid)
                e = id_to_entry.get(eid)
                if e is not None:
                    cluster.append(e)
                    for conn_id in e.connections:
                        if conn_id not in visited and conn_id in id_to_entry:
                            queue.append(conn_id)

            if cluster:
                clusters.append(cluster)

        return clusters

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        return (
            "You are a code research analyst. You receive a notebook of "
            "accumulated research findings about a codebase. Your task is "
            "to synthesize them into a coherent, well-structured markdown "
            "document that identifies themes, explains relationships between "
            "findings, and highlights knowledge gaps."
        )

    def _build_prompt(
        self,
        notebook: Notebook,
        clusters: list[list[NotebookEntry]],
        focus: str | None,
    ) -> str:
        sections: list[str] = []

        sections.append(f"# Research Notebook: {notebook.name}")
        sections.append(f"Total entries: {notebook.entry_count}")
        sections.append(f"Thematic clusters: {len(clusters)}")
        sections.append("")

        if focus:
            sections.append(f"## Focus Question\n{focus}\n")

        for i, cluster in enumerate(clusters, 1):
            sections.append(f"## Cluster {i} ({len(cluster)} entries)")
            tags = set()
            for entry in cluster:
                tags.update(entry.tags)

            if tags:
                sections.append(f"Tags: {', '.join(sorted(tags))}")
            sections.append("")

            for entry in cluster:
                sections.append(f"### Query: {entry.query}")
                sections.append(f"Confidence: {entry.confidence:.2f}")
                if entry.tags:
                    sections.append(f"Tags: {', '.join(entry.tags)}")
                sections.append("")
                sections.append(entry.summary)
                sections.append("")

                if entry.source_chunks:
                    refs = ", ".join(
                        f"`{c.file_path}`" for c in entry.source_chunks[:3]
                    )
                    sections.append(f"Sources: {refs}")
                    sections.append("")

                if entry.note:
                    sections.append(f"> Note: {entry.note}")
                    sections.append("")

        sections.append("---")
        sections.append(
            "Please synthesize the above findings into a coherent document with:\n"
            "1. An executive summary\n"
            "2. Thematic sections grouping related findings\n"
            "3. Cross-references between related discoveries\n"
            "4. A 'Knowledge Gaps' section listing areas not yet explored\n"
            "5. Concrete next steps for further investigation"
        )

        return "\n".join(sections)