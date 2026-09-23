"""Per-user content tools, exposed to the agent as Copilot SDK Tool objects.

Every tool acts as one bound user: `owner` is captured in a closure by
build_content_tools(owner) and is NEVER a tool parameter, so the model cannot
reach another user's data (a confused-deputy guard). The ResourceManager still
enforces ownership underneath, so this layer's only job is to bind the user.

ResourceManager calls are synchronous (boto3/pymongo), so each handler offloads
to a thread to avoid blocking the event loop (and the SSE stream). ValueErrors
become "failure" ToolResults so the model can correct itself mid-turn instead of
crashing the turn.
"""

from __future__ import annotations

import asyncio
import json

from copilot import Tool, ToolInvocation, ToolResult

from app.content.manager import ResourceManager, resource_manager
from app.logging_config import get_logger

logger = get_logger(__name__)

TOOL_NAMES = ["inspect_tree", "list_data", "get_data", "add", "delete"]

# JSON Schema fragments for the tool inputs. Note: no `owner`/`username` field —
# the user is bound server-side, never chosen by the model.
_PATH = {"type": "array", "items": {"type": "string"}}
_PATH_ONLY = {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}


def _ok(data) -> ToolResult:
    text = data if isinstance(data, str) else json.dumps(data, default=str)
    return ToolResult(text_result_for_llm=text)


def _err(msg: str) -> ToolResult:
    return ToolResult(text_result_for_llm=msg, result_type="failure", error=msg)


def build_content_tools(owner: str, manager: ResourceManager | None = None) -> list[Tool]:
    """Build the Copilot tools whose handlers all act as `owner`."""
    return _content_tools(owner, manager or resource_manager)


def _content_tools(owner: str, mgr: ResourceManager) -> list[Tool]:
    """The user-bound tool handlers (a seam that stays testable in isolation).

    Each handler takes a Copilot ToolInvocation and reads its `.arguments`; the
    tools are first-party and pre-approved (`skip_permission=True`), so no
    permission round-trip is needed for the bound owner's own content.
    """

    async def inspect_tree(inv: ToolInvocation) -> ToolResult:
        path = inv.arguments.get("path") or []
        tree = mgr.tree_of(owner)
        if not path:
            return _ok(tree.to_dict())
        node = tree.get(path)
        if node is None:
            return _err(f"path {path} not found")
        return _ok(node.to_dict(len(path) - 1))

    async def list_data(inv: ToolInvocation) -> ToolResult:
        try:
            names = await asyncio.to_thread(mgr.list_data, owner, inv.arguments["path"])
        except ValueError as exc:
            return _err(str(exc))
        return _ok(names)

    async def get_data(inv: ToolInvocation) -> ToolResult:
        try:
            data = await asyncio.to_thread(mgr.get_data, owner, inv.arguments["path"])
        except ValueError as exc:
            return _err(str(exc))
        if data is None:
            return _err("datum not found")
        return _ok(data)

    async def add(inv: ToolInvocation) -> ToolResult:
        args = inv.arguments
        path = [*args["parent_path"], args["name"]]
        try:
            node = await asyncio.to_thread(
                mgr.add, owner, path, metadata=args.get("metadata"), data=args.get("data")
            )
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:
            # Surface an infra failure to the model rather than crashing the turn.
            logger.exception("tool add failed")
            return _err(f"infra error: {exc}")
        return _ok({"added": path, "kind": node.kind.value})

    async def delete(inv: ToolInvocation) -> ToolResult:
        try:
            await asyncio.to_thread(mgr.delete, owner, inv.arguments["path"])
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:
            # Surface an infra failure to the model rather than crashing the turn.
            logger.exception("tool delete failed")
            return _err(f"infra error: {exc}")
        return _ok({"deleted": inv.arguments["path"]})

    return [
        Tool(
            name="inspect_tree",
            description=(
                "Inspect the user's content tree (databases, containers, and data names "
                "they can reach). Omit path for the whole tree, or pass a path to view a "
                "subtree, e.g. ['mongodb', 'default', 'app']."
            ),
            parameters={"type": "object", "properties": {"path": _PATH}, "required": []},
            handler=inspect_tree,
            skip_permission=True,
        ),
        Tool(
            name="list_data",
            description=(
                "List the data item names inside a container (table/bucket/collection), "
                "read from the database."
            ),
            parameters=_PATH_ONLY,
            handler=list_data,
            skip_permission=True,
        ),
        Tool(
            name="get_data",
            description=(
                "Read a single datum's stored payload at a data-leaf path, e.g. "
                "['mongodb', 'default', 'app', 'users', 'u1']."
            ),
            parameters=_PATH_ONLY,
            handler=get_data,
            skip_permission=True,
        ),
        Tool(
            name="add",
            description=(
                "Add a resource or a datum under a parent path. Provisions a container "
                "when no data is given; writes a datum (data required) at the data level. "
                "The kind is derived from the path depth per engine."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "parent_path": _PATH,
                    "name": {"type": "string"},
                    "metadata": {"type": "object"},
                    "data": {"type": "object"},
                },
                "required": ["parent_path", "name"],
            },
            handler=add,
            skip_permission=True,
        ),
        Tool(
            name="delete",
            description=(
                "Delete the resource or datum at a path (removes its whole subtree). "
                "Destructive and irreversible."
            ),
            parameters=_PATH_ONLY,
            handler=delete,
            skip_permission=True,
        ),
    ]
