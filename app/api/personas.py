"""Manifest (persona library) endpoints — CRUD over the YAML files on disk.

The library is shared (not per-user), so these are guarded by require_user only
for authentication. RegistryError statuses (404/409) map straight to
HTTPException.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth.dependencies import require_user
from app.auth.service import User
from app.personas.registry import RegistryError, manifest_registry
from app.personas.schema import Manifest, Role

router = APIRouter(prefix="/manifests", tags=["manifests"])


@router.get("", response_model=list[Manifest])
async def list_manifests(
    user: Annotated[User, Depends(require_user)],
    role: Role | None = None,
) -> list[Manifest]:
    return manifest_registry.list(role)


@router.get("/{name}", response_model=Manifest)
async def get_manifest(
    name: str, user: Annotated[User, Depends(require_user)]
) -> Manifest:
    try:
        return manifest_registry.get(name)
    except RegistryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("", response_model=Manifest)
async def create_manifest(
    manifest: Manifest, user: Annotated[User, Depends(require_user)]
) -> Manifest:
    try:
        return manifest_registry.create(manifest)
    except RegistryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.put("/{name}", response_model=Manifest)
async def update_manifest(
    name: str, manifest: Manifest, user: Annotated[User, Depends(require_user)]
) -> Manifest:
    try:
        return manifest_registry.update(name, manifest)
    except RegistryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.delete("/{name}", status_code=204)
async def delete_manifest(
    name: str, user: Annotated[User, Depends(require_user)]
) -> Response:
    try:
        manifest_registry.delete(name)
    except RegistryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return Response(status_code=204)
