"""Filesystem browse endpoint — backs the UI's directory picker.

Lists the immediate sub-directories of a server-side path so a user can navigate
and choose an agent's working directory. Read-only: it never exposes file
contents, only directory names. An empty path defaults to the user's home.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_user
from app.auth.service import User
from app.workspace import list_subdirectories

router = APIRouter(prefix="/fs", tags=["fs"])


@router.get("/dirs")
async def list_dirs(
    user: Annotated[User, Depends(require_user)],
    path: Annotated[str | None, Query()] = None,
) -> dict:
    """List sub-directories of `path` (defaults to home). 400 on a bad path."""
    try:
        return list_subdirectories(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
