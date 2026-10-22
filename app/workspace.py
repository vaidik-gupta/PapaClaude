"""Working-directory helpers for agents.

Every conversation is attached to a filesystem directory (its agent's working
directory). These helpers resolve a user-supplied path to a canonical absolute
path and enforce the "must exist" rule, and list sub-directories for the UI's
directory picker. Keeping this in one module lets the API routes, the
`spawn_child` tool, and the browse endpoint share the exact same semantics.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_directory(raw: str | None) -> str:
    """Expand and validate a directory path, returning its absolute form.

    Expands `~` and environment variables, resolves symlinks/`..`, and requires
    the result to be an existing directory. Raises ValueError otherwise.
    """
    if raw is None or not str(raw).strip():
        raise ValueError("directory is required")
    expanded = os.path.expandvars(str(raw).strip())
    path = Path(expanded).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:  # pragma: no cover - resolve rarely raises
        raise ValueError(f"invalid directory: {raw}") from exc
    if not resolved.is_dir():
        raise ValueError(f"directory does not exist: {raw}")
    return str(resolved)


def list_subdirectories(raw: str | None) -> dict:
    """List the immediate sub-directories of a path for the directory picker.

    An empty/None path defaults to the user's home. Returns the resolved path,
    its parent (None at the filesystem root), the home directory, and the sorted
    names of child directories (unreadable entries are skipped).
    """
    base = raw if raw and str(raw).strip() else "~"
    path = Path(resolve_directory(base))
    entries: list[str] = []
    try:
        for child in path.iterdir():
            try:
                if child.is_dir():
                    entries.append(child.name)
            except OSError:
                continue
    except PermissionError as exc:
        raise ValueError(f"permission denied: {path}") from exc
    entries.sort(key=str.lower)
    parent = str(path.parent)
    return {
        "path": str(path),
        "parent": None if parent == str(path) else parent,
        "home": str(Path.home()),
        "entries": entries,
    }
