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

from app.agent.permissions import ASK, DENY, permission_for
from app.agent.widgets import WidgetBridge, WidgetCancelled
from app.content.manager import ResourceManager, resource_manager
from app.logging_config import get_logger
from app.workspace import resolve_directory

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


def _summarize(tool: str, args: dict) -> str:
    """A short human-readable description of a gated call, shown in the widget."""
    if tool == "delete":
        return f"Delete {args.get('path')} — this removes its whole subtree and is irreversible."
    return f"Run {tool} with {args}"


def build_content_tools(
    owner: str,
    manager: ResourceManager | None = None,
    allowed: list[str] | None = None,
) -> list[Tool]:
    """Build the Copilot content tools whose handlers all act as `owner`.

    `allowed` restricts the set to the named tools (a persona's allowed_tools);
    None means all content tools. Permission gating is applied separately and
    uniformly by `gate_tools`, so these handlers stay permission-agnostic.
    """
    tools = _content_tools(owner, manager or resource_manager)
    if allowed is not None:
        allow = set(allowed)
        tools = [t for t in tools if t.name in allow]
    return tools


def gate_tools(
    tools: list[Tool],
    permissions: dict[str, str] | None,
    bridge: WidgetBridge | None,
) -> list[Tool]:
    """Wrap every tool's handler with the agent's permission check.

    One place decides, for *any* tool, whether a call runs (`auto`), is refused
    (`deny`), or must be confirmed via a permission widget (`ask`). Tools never
    implement this themselves — adding a new tool gets gating for free. When
    `bridge` is None (non-turn paths) an `ask` tool proceeds, since there is no
    stream to surface a widget on.
    """
    for tool in tools:
        tool.handler = _with_permission(tool.name, tool.handler, permissions, bridge)
    return tools


def _with_permission(name: str, inner, permissions, bridge):
    async def gated(inv: ToolInvocation) -> ToolResult:
        perm = permission_for(permissions, name)
        if perm == DENY:
            return _err(f"'{name}' is not permitted for this agent")
        if perm == ASK and bridge is not None:
            try:
                reply = await bridge.present_widget(
                    "permission",
                    {"tool": name, "args": inv.arguments, "summary": _summarize(name, inv.arguments)},
                )
            except WidgetCancelled:
                return _err(f"'{name}' was cancelled before approval")
            if not reply.get("granted"):
                return _err(f"user denied '{name}'")
        return await inner(inv)

    return gated


def build_spawn_child_tool(owner: str, parent_id: str) -> Tool:
    """Build the parent-only `spawn_child` tool.

    Its handler calls the conversation manager to create a role=child
    conversation under `parent_id`, seeding the child with `context` as its task.
    The manager is imported lazily inside the handler to avoid a circular import
    (manager -> client -> tools -> manager).
    """

    async def spawn_child(inv: ToolInvocation) -> ToolResult:
        from app.conversations.manager import conversation_manager

        args = inv.arguments
        manifest_name = args["manifest_name"]
        context = args.get("context")
        title = args.get("title")
        raw_dir = args.get("directory")
        directory: str | None = None
        if raw_dir is not None and str(raw_dir).strip():
            try:
                directory = resolve_directory(raw_dir)
            except ValueError as exc:
                return _err(str(exc))
        try:
            child = await conversation_manager.create_child(
                parent_id=parent_id,
                owner=owner,
                manifest_name=manifest_name,
                title=title,
                task=context,
                directory=directory,
            )
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("spawn_child failed")
            return _err(f"infra error: {exc}")
        return _ok(
            {
                "child_id": child.id,
                "title": child.title,
                "manifest_name": child.manifest_name,
                "directory": child.directory,
            }
        )

    return Tool(
        name="spawn_child",
        description=(
            "Spawn a focused child agent under this project to carry out a scoped "
            "subtask. `manifest_name` picks a child persona from the library; "
            "`context` is a self-contained instruction string seeded as the child's "
            "task (the only channel it receives); optional `title` names the child; "
            "optional `directory` sets the child's working directory (must be an "
            "existing path) and defaults to this project's directory when omitted."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manifest_name": {"type": "string"},
                "context": {"type": "string"},
                "title": {"type": "string"},
                "directory": {"type": "string"},
            },
            "required": ["manifest_name", "context"],
        },
        handler=spawn_child,
        skip_permission=True,
    )


def _content_tools(
    owner: str,
    mgr: ResourceManager,
) -> list[Tool]:
    """The user-bound tool handlers (a seam that stays testable in isolation).

    Each handler takes a Copilot ToolInvocation and reads its `.arguments`; the
    tools are first-party and pre-approved (`skip_permission=True`), so no SDK
    permission round-trip is needed. Our per-agent permission config (applied by
    `gate_tools`) gates these handlers independently.
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
