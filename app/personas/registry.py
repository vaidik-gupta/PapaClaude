"""ManifestRegistry — the persona library as YAML files on disk.

Each manifest lives in one `<name>.yaml` file under the manifests dir, with its
`name` field pinned to the filename stem. CRUD maps directly onto files. Two
shipped defaults (`default-parent`, `default-child`) are protected from deletion
so the app always has a usable persona for each role.

Errors are raised as `RegistryError` with an HTTP-ish `status` (404/409/400) the
API layer maps to `HTTPException`, keeping this layer framework-free.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import settings
from app.logging_config import get_logger
from app.personas.schema import Manifest, Role

logger = get_logger(__name__)

# Shipped defaults seeded on disk; deleting them is refused so each role always
# has a fallback persona.
PROTECTED_DEFAULTS = frozenset({"default-parent", "default-child"})


class RegistryError(Exception):
    """A registry failure carrying the status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ManifestRegistry:
    def __init__(self, manifests_dir: str | Path | None = None) -> None:
        self._dir = Path(manifests_dir or settings.manifests_dir)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.yaml"

    def _read(self, path: Path) -> Manifest:
        data = yaml.safe_load(path.read_text()) or {}
        return Manifest(**data)

    def _write(self, manifest: Manifest) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(manifest.name).write_text(
            yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False)
        )

    def list(self, role: Role | None = None) -> list[Manifest]:
        if not self._dir.exists():
            return []
        manifests = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                manifests.append(self._read(path))
            except Exception:  # noqa: BLE001 — skip a malformed file, don't fail the list
                logger.warning("Skipping unreadable manifest %s", path.name)
        if role is not None:
            manifests = [m for m in manifests if m.role is role]
        return manifests

    def get(self, name: str) -> Manifest:
        path = self._path(name)
        if not path.exists():
            raise RegistryError(404, f"manifest {name!r} not found")
        return self._read(path)

    def create(self, manifest: Manifest) -> Manifest:
        if self._path(manifest.name).exists():
            raise RegistryError(409, f"manifest {manifest.name!r} already exists")
        self._write(manifest)
        logger.info("Created manifest %s", manifest.name)
        return manifest

    def update(self, name: str, manifest: Manifest) -> Manifest:
        if not self._path(name).exists():
            raise RegistryError(404, f"manifest {name!r} not found")
        # The filename is authoritative: pin the manifest's name to the stem.
        pinned = manifest.model_copy(update={"name": name})
        self._write(pinned)
        return pinned

    def delete(self, name: str) -> None:
        if name in PROTECTED_DEFAULTS:
            raise RegistryError(409, f"manifest {name!r} is a shipped default and cannot be deleted")
        path = self._path(name)
        if not path.exists():
            raise RegistryError(404, f"manifest {name!r} not found")
        path.unlink()
        logger.info("Deleted manifest %s", name)


manifest_registry = ManifestRegistry()
