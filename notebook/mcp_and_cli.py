"""MCP tools and CLI subcommand for the Interactive Code Notebook.

MCP tools:
    - notebook_research: Run code_research and append to a notebook.
    - notebook_synthesize: Generate cross-entry synthesis.

CLI:
    - chunkhound notebook create <name>
    - chunkhound notebook show <name>
    - chunkhound notebook note <name> <text>
    - chunkhound notebook synthesize <name>
    - chunkhound notebook export <name> --format md --output file.md
    - chunkhound notebook list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.notebook.models import ChunkRef, Notebook, NotebookEntry
from chunkhound.notebook.store import NotebookStore


# =====================================================================
# MCP tool schemas
# =====================================================================

NOTEBOOK_RESEARCH_TOOL_SCHEMA: dict[str, Any] = {
    "name": "notebook_research",
    "description": (
        "Run deep code research and append the result to a named notebook. "
        "Creates the notebook if it doesn't exist."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query", "notebook"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Research question to investigate",
            },
            "notebook": {
                "type": "string",
                "description": "Notebook name or slug to append results to",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for this entry",
            },
            "path": {
                "type": "string",
                "description": "Optional path filter for the research",
            },
        },
    },
}

NOTEBOOK_SYNTHESIZE_TOOL_SCHEMA: dict[str, Any] = {
    "name": "notebook_synthesize",
    "description": (
        "Generate a coherent synthesis document from all entries in a notebook. "
        "Identifies themes, cross-references, and knowledge gaps."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["notebook"],
        "properties": {
            "notebook": {
                "type": "string",
                "description": "Notebook name or slug",
            },
            "focus": {
                "type": "string",
                "description": "Optional focusing question for the synthesis",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "json"],
                "default": "markdown",
            },
        },
    },
}


# =====================================================================
# MCP tool handlers
# =====================================================================

async def handle_notebook_research(
    arguments: dict[str, Any],
    store: NotebookStore,
    run_research_fn: Any,
    connector: Any | None = None,
) -> dict[str, Any]:
    """Handle ``notebook_research`` MCP tool invocation.

    Args:
        arguments: Tool arguments from MCP.
        store: NotebookStore instance.
        run_research_fn: Async callable that runs deep research and returns
                         a result dict with ``answer`` and ``metadata``.
        connector: Optional ConnectionDetector for auto-linking.
    """
    query = arguments.get("query", "")
    notebook_name = arguments.get("notebook", "default")
    tags = arguments.get("tags") or []
    path_filter = arguments.get("path")

    if not query:
        return {"error": "query is required"}

    # Run the actual research
    try:
        result = await run_research_fn(query=query, path=path_filter)
    except Exception as exc:
        return {"error": f"Research failed: {exc}"}

    answer = result.get("answer", "")
    metadata = result.get("metadata") or {}
    sources = metadata.get("sources") or {}

    # Build chunk references
    chunk_refs: list[ChunkRef] = []
    for chunk in (sources.get("chunks") or [])[:10]:
        chunk_refs.append(
            ChunkRef(
                chunk_id=int(chunk.get("chunk_id", 0)),
                file_path=str(chunk.get("file_path", "")),
                symbol=chunk.get("symbol"),
                start_line=chunk.get("start_line"),
                end_line=chunk.get("end_line"),
            )
        )

    # Create the entry
    entry = NotebookEntry(
        query=query,
        summary=answer,
        source_chunks=chunk_refs,
        tags=tags,
        confidence=float(metadata.get("confidence", 0.5)),
    )

    # Get or create notebook
    nb = store.get(notebook_name)
    if nb is None:
        nb = store.create(notebook_name)

    # Auto-detect connections
    if connector is not None:
        try:
            connections = await connector.detect_connections(entry, nb)
            logger.debug(
                f"Notebook: detected {len(connections)} connections for new entry"
            )
        except Exception as exc:
            logger.debug(f"Notebook: connection detection failed: {exc}")

    nb.add_entry(entry)
    store.save(nb)

    return {
        "notebook": nb.name,
        "entry_id": entry.id,
        "connections": entry.connections,
        "total_entries": nb.entry_count,
        "answer": answer,
    }


async def handle_notebook_synthesize(
    arguments: dict[str, Any],
    store: NotebookStore,
    synthesizer: Any,
) -> dict[str, Any]:
    """Handle ``notebook_synthesize`` MCP tool invocation."""
    notebook_name = arguments.get("notebook", "")
    focus = arguments.get("focus")
    output_format = arguments.get("format", "markdown")

    if not notebook_name:
        return {"error": "notebook name is required"}

    nb = store.get(notebook_name)
    if nb is None:
        return {"error": f"Notebook '{notebook_name}' not found"}

    if not nb.entries:
        return {"error": "Notebook has no entries to synthesize"}

    synthesis = await synthesizer.synthesize(nb, focus=focus)
    store.save(nb)

    if output_format == "json":
        return {
            "notebook": nb.name,
            "synthesis": synthesis,
            "entry_count": nb.entry_count,
        }

    return {"content": synthesis, "format": "markdown"}


# =====================================================================
# CLI subcommand
# =====================================================================

def add_notebook_subparser(subparsers: Any) -> None:
    """Register the ``notebook`` subcommand."""
    parser = subparsers.add_parser(
        "notebook",
        help="Manage interactive code research notebooks",
    )
    nb_sub = parser.add_subparsers(dest="notebook_action")

    # create
    create_p = nb_sub.add_parser("create", help="Create a new notebook")
    create_p.add_argument("name", help="Notebook name")

    # show
    show_p = nb_sub.add_parser("show", help="Display notebook contents")
    show_p.add_argument("name", help="Notebook name or slug")

    # list
    nb_sub.add_parser("list", help="List all notebooks")

    # note
    note_p = nb_sub.add_parser("note", help="Add a manual note to a notebook")
    note_p.add_argument("name", help="Notebook name or slug")
    note_p.add_argument("text", help="Note text")

    # synthesize
    synth_p = nb_sub.add_parser("synthesize", help="Generate cross-entry synthesis")
    synth_p.add_argument("name", help="Notebook name or slug")
    synth_p.add_argument("--focus", help="Optional focusing question")

    # export
    export_p = nb_sub.add_parser("export", help="Export notebook as markdown")
    export_p.add_argument("name", help="Notebook name or slug")
    export_p.add_argument(
        "--format", choices=["md", "json"], default="md", help="Export format"
    )
    export_p.add_argument(
        "--output", type=Path, help="Output file (default: stdout)"
    )

    # delete
    del_p = nb_sub.add_parser("delete", help="Delete a notebook")
    del_p.add_argument("name", help="Notebook name or slug")

    parser.set_defaults(func=_run_notebook_command)


def _run_notebook_command(args: argparse.Namespace) -> None:
    """Entry point for ``chunkhound notebook``."""
    from chunkhound.core.config.config import Config

    config = Config(args=args)
    target_dir = config.target_dir or Path(".").resolve()
    notebooks_base = target_dir / ".chunkhound"
    store = NotebookStore(notebooks_base)

    action = getattr(args, "notebook_action", None)

    if action == "create":
        nb = store.create(args.name)
        print(f"Created notebook: {nb.name} ({nb.slug})")

    elif action == "show":
        nb = store.get(args.name)
        if nb is None:
            print(f"Notebook '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        print(nb.to_markdown())

    elif action == "list":
        notebooks = store.list_all()
        if not notebooks:
            print("No notebooks found.")
            return
        print(f"{'Name':<40} {'Entries':>7}  Created")
        print("-" * 70)
        for nb in notebooks:
            print(
                f"{nb.name:<40} {nb.entry_count:>7}  "
                f"{nb.created_at.strftime('%Y-%m-%d')}"
            )

    elif action == "note":
        nb = store.get(args.name)
        if nb is None:
            print(f"Notebook '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        entry = NotebookEntry(
            query="Manual note",
            summary=args.text,
            note=args.text,
            confidence=1.0,
        )
        nb.add_entry(entry)
        store.save(nb)
        print(f"Note added to '{nb.name}' (entry {entry.id[:8]}...)")

    elif action == "synthesize":
        import asyncio

        nb = store.get(args.name)
        if nb is None:
            print(f"Notebook '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

        try:
            from chunkhound.llm_manager import LLMManager

            llm_config = config.llm
            if llm_config is None:
                print("LLM not configured. Cannot synthesize.", file=sys.stderr)
                sys.exit(1)

            utility_cfg, synth_cfg = llm_config.get_provider_configs()
            llm_manager = LLMManager(utility_cfg, synth_cfg)

            from chunkhound.notebook.synthesizer import NotebookSynthesizer

            synthesizer = NotebookSynthesizer(llm_manager.get_synthesis_provider())
            synthesis = asyncio.run(
                synthesizer.synthesize(nb, focus=getattr(args, "focus", None))
            )
            store.save(nb)
            print(synthesis)
        except Exception as exc:
            print(f"Synthesis failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif action == "export":
        nb = store.get(args.name)
        if nb is None:
            print(f"Notebook '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

        if args.format == "json":
            import json
            output = json.dumps(nb.to_dict(), indent=2, default=str)
        else:
            output = nb.to_markdown()

        if args.output:
            args.output.write_text(output, encoding="utf-8")
            print(f"Exported to {args.output}")
        else:
            print(output)

    elif action == "delete":
        if store.delete(args.name):
            print(f"Deleted notebook: {args.name}")
        else:
            print(f"Notebook '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

    else:
        print("Usage: chunkhound notebook {create|show|list|note|synthesize|export|delete}")