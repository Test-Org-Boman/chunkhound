"""NotebookStore – CRUD operations for notebook JSON files.

Notebooks are stored in ``.chunkhound/notebooks/<slug>.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.notebook.models import Notebook, NotebookEntry


class NotebookStore:
    """Filesystem-backed notebook storage."""

    def __init__(self, base_dir: Path) -> None:
        """
        Args:
            base_dir: Project root or ``.chunkhound`` directory.
                      Notebooks are stored under ``base_dir/notebooks/``.
        """
        self._notebooks_dir = base_dir / "notebooks"
        self._notebooks_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, name: str) -> Notebook:
        """Create a new empty notebook."""
        nb = Notebook(name=name)
        self._save(nb)
        logger.info(f"Notebook: created '{name}' at {self._path(nb)}")
        return nb

    def get(self, name_or_slug: str) -> Notebook | None:
        """Load a notebook by name or slug.  Returns None if not found."""
        path = self._resolve_path(name_or_slug)
        if path is None or not path.exists():
            return None
        return self._load(path)

    def save(self, notebook: Notebook) -> Path:
        """Persist a notebook to disk.  Returns the file path."""
        return self._save(notebook)

    def delete(self, name_or_slug: str) -> bool:
        """Delete a notebook file.  Returns True if deleted."""
        path = self._resolve_path(name_or_slug)
        if path is None or not path.exists():
            return False
        path.unlink()
        logger.info(f"Notebook: deleted {path}")
        return True

    def list_all(self) -> list[Notebook]:
        """Return all notebooks (lightweight: loads metadata only)."""
        notebooks: list[Notebook] = []
        for path in sorted(self._notebooks_dir.glob("*.json")):
            try:
                nb = self._load(path)
                if nb:
                    notebooks.append(nb)
            except Exception as exc:
                logger.debug(f"Notebook: failed to load {path}: {exc}")
        return notebooks

    # ------------------------------------------------------------------
    # Entry operations
    # ------------------------------------------------------------------

    def add_entry(
        self, name_or_slug: str, entry: NotebookEntry
    ) -> Notebook | None:
        """Add an entry to an existing notebook.  Returns the updated notebook."""
        nb = self.get(name_or_slug)
        if nb is None:
            return None
        nb.add_entry(entry)
        self._save(nb)
        return nb

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path(self, notebook: Notebook) -> Path:
        return self._notebooks_dir / f"{notebook.slug}.json"

    def _resolve_path(self, name_or_slug: str) -> Path | None:
        """Try to find a notebook file by name or slug."""
        # Try direct slug match
        candidate = self._notebooks_dir / f"{name_or_slug}.json"
        if candidate.exists():
            return candidate

        # Try slugifying the name
        import re
        slug = re.sub(r"[^\w\s-]", "", name_or_slug.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:60]
        candidate = self._notebooks_dir / f"{slug}.json"
        if candidate.exists():
            return candidate

        # Scan all notebooks for a name match
        for path in self._notebooks_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("name", "").lower() == name_or_slug.lower():
                    return path
            except Exception:
                continue

        return None

    def _save(self, notebook: Notebook) -> Path:
        path = self._path(notebook)
        path.write_text(
            json.dumps(notebook.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def _load(self, path: Path) -> Notebook | None:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return Notebook.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(f"Notebook: corrupt file {path}: {exc}")
            return None