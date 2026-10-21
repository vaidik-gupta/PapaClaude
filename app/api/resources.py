"""Resource endpoints — request a db, add a resource/datum, read, delete.

Everything operates on the authenticated user's ContentTree via the
ResourceManager, which mutates the DB first and only then the tree. Adds carry a
wrapper: `name` (stored in the tree), optional `metadata` (stored on the node),
and optional `data` (the payload — required at the data level, written to the DB
but never stored in the tree).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_user
from app.auth.service import User
from app.content import Engine, resource_manager
from app.logging_config import get_logger

router = APIRouter(prefix="/resources", tags=["resources"])
logger = get_logger(__name__)


class RequestDBBody(BaseModel):
    engine: Engine
    name: str
    metadata: dict = {}


class AddBody(BaseModel):
    parent_path: list[str]
    name: str
    metadata: dict = {}
    data: dict | None = None  # required when the target level is the data level


class NodeResponse(BaseModel):
    path: list[str]
    node: dict


class DataResponse(BaseModel):
    path: list[str]
    data: dict | None


def _add(username: str, path: list[str], metadata: dict, data: dict | None) -> NodeResponse:
    try:
        node = resource_manager.add(username, path, metadata=metadata, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — DB/provider failure
        logger.exception("infra add failed")
        raise HTTPException(status_code=502, detail=f"infra error: {exc}") from exc
    return NodeResponse(path=path, node=node.to_dict(len(path) - 1))


@router.post("/db", response_model=NodeResponse)
def request_db(body: RequestDBBody, user: Annotated[User, Depends(require_user)]) -> NodeResponse:
    """Request a new db instance of a given engine (layer 1 of the tree)."""
    return _add(user.username, [body.engine.value, body.name], body.metadata, None)


@router.post("", response_model=NodeResponse)
def add_resource(body: AddBody, user: Annotated[User, Depends(require_user)]) -> NodeResponse:
    """Add a resource or a datum under a directory; its kind is derived per engine."""
    return _add(user.username, [*body.parent_path, body.name], body.metadata, body.data)


@router.post("/reload")
def reload_tree(user: Annotated[User, Depends(require_user)]) -> dict:
    """Re-read the user's content tree from durable storage into the cache."""
    return resource_manager.reload(user.username).to_dict()


@router.get("")
def get_tree(user: Annotated[User, Depends(require_user)]) -> dict:
    """Return the user's whole content tree (all engine roots and their subtrees)."""
    return resource_manager.tree_of(user.username).to_dict()


@router.get("/data/{resource_path:path}", response_model=DataResponse)
def read_data(
    resource_path: str, user: Annotated[User, Depends(require_user)]
) -> DataResponse:
    """Read a single datum's payload from the DB (data leaves only)."""
    path = [seg for seg in resource_path.split("/") if seg]
    try:
        data = resource_manager.get_data(user.username, path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — DB/provider failure
        logger.exception("infra get_data failed")
        raise HTTPException(status_code=502, detail=f"infra error: {exc}") from exc
    return DataResponse(path=path, data=data)


@router.get("/{resource_path:path}", response_model=NodeResponse)
def read_resource(
    resource_path: str, user: Annotated[User, Depends(require_user)]
) -> NodeResponse:
    """Read the resource (and its subtree) at a slash-separated path."""
    path = [seg for seg in resource_path.split("/") if seg]
    try:
        node = resource_manager.tree_of(user.username).get(path)
    except ValueError as exc:  # malformed path (e.g. unknown engine)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if node is None:
        raise HTTPException(status_code=404, detail=f"resource {path} not found")
    return NodeResponse(path=path, node=node.to_dict(len(path) - 1))


@router.delete("/{resource_path:path}", response_model=NodeResponse)
def delete_resource(
    resource_path: str, user: Annotated[User, Depends(require_user)]
) -> NodeResponse:
    """Delete the resource/datum at a path (removes its whole subtree)."""
    path = [seg for seg in resource_path.split("/") if seg]
    try:
        resource_manager.delete(user.username, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — DB/provider failure
        logger.exception("infra delete failed")
        raise HTTPException(status_code=502, detail=f"infra error: {exc}") from exc
    return NodeResponse(path=path, node={"deleted": True})
