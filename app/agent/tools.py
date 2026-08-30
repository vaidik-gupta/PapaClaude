"""Per-user content tools, exposed to the agent as an in-process SDK MCP server.

Every tool acts as one server-bound user: `owner` is captured in a closure by
build_content_server(owner) and is NEVER a tool parameter, so the model cannot
reach another user's data (a confused-deputy guard). The ResourceManager still
enforces ownership underneath, so this layer's only job is to bind the user.

ResourceManager calls are synchronous (boto3/pymongo), so each handler offloads
to a thread to avoid blocking the event loop (and the SSE stream). ValueErrors
become clean is_error results so the model can correct itself mid-turn instead
of crashing the turn.
"""

from __future__ import annotations

import asyncio
import json

from claude_agent_sdk import (
    McpSdkServerConfig,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from app.content.manager import ResourceManager, resource_manager
from app.logging_config import get_logger

logger = get_logger(__name__)

SERVER_NAME = "content"
TOOL_NAMES = ["inspect_tree", "list_data", "get_data", "add", "delete"]

# JSON Schema fragments for the tool inputs. Note: no `owner`/`username` field —
# the user is bound server-side, never chosen by the model.
_PATH = {"type": "array", "items": {"type": "string"}}
_PATH_ONLY = {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}


def allowed_tool_names() -> list[str]:
    """Fully-qualified MCP tool names, for ClaudeAgentOptions.allowed_tools."""
    return [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES]


def _ok(data) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def build_content_server(
    owner: str, manager: ResourceManager | None = None
) -> McpSdkServerConfig:
    """Build a fresh MCP server whose tools all act as `owner`."""
    return create_sdk_mcp_server(
        name=SERVER_NAME, tools=_content_tools(owner, manager or resource_manager)
    )


def _content_tools(owner: str, mgr: ResourceManager) -> list:
    """The user-bound tool handlers (a seam that stays testable in isolation)."""

    @tool(
        "inspect_tree",
        "Inspect the user's content tree (databases, containers, and data names "
        "they can reach). Omit path for the whole tree, or pass a path to view a "
        "subtree, e.g. ['mongodb', 'default', 'app'].",
        {"type": "object", "properties": {"path": _PATH}, "required": []},
    )
    async def inspect_tree(args):
        path = args.get("path") or []
        tree = mgr.tree_of(owner)
        if not path:
            return _ok(tree.to_dict())
        node = tree.get(path)
        if node is None:
            return _err(f"path {path} not found")
        return _ok(node.to_dict(len(path) - 1))

    @tool(
        "list_data",
        "List the data item names inside a container (table/bucket/collection), "
        "read from the database.",
        _PATH_ONLY,
    )
    async def list_data(args):
        try:
            names = await asyncio.to_thread(mgr.list_data, owner, args["path"])
        except ValueError as exc:
            return _err(str(exc))
        return _ok(names)

    @tool(
        "get_data",
        "Read a single datum's stored payload at a data-leaf path, e.g. "
        "['mongodb', 'default', 'app', 'users', 'u1'].",
        _PATH_ONLY,
    )
    async def get_data(args):
        try:
            data = await asyncio.to_thread(mgr.get_data, owner, args["path"])
        except ValueError as exc:
            return _err(str(exc))
        if data is None:
            return _err("datum not found")
        return _ok(data)

    @tool(
        "add",
        "Add a resource or a datum under a parent path. Provisions a container "
        "when no data is given; writes a datum (data required) at the data level. "
        "The kind is derived from the path depth per engine.",
        {
            "type": "object",
            "properties": {
                "parent_path": _PATH,
                "name": {"type": "string"},
                "metadata": {"type": "object"},
                "data": {"type": "object"},
            },
            "required": ["parent_path", "name"],
        },
    )
    async def add(args):
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

    @tool(
        "delete",
        "Delete the resource or datum at a path (removes its whole subtree). "
        "Destructive and irreversible.",
        _PATH_ONLY,
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def delete(args):
        try:
            await asyncio.to_thread(mgr.delete, owner, args["path"])
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:
            # Surface an infra failure to the model rather than crashing the turn.
            logger.exception("tool delete failed")
            return _err(f"infra error: {exc}")
        return _ok({"deleted": args["path"]})

    return [inspect_tree, list_data, get_data, add, delete]
