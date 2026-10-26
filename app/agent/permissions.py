"""Per-agent permission config.

An agent's permission config is a flat dict `{ tool_name: permission }` where
permission is one of:

    auto  — allowed without asking; run immediately.
    ask   — present a permission widget; run only if the user grants it.
    deny  — never allowed; the tool returns a failure result, no widget.

The config is snapshotted onto the conversation's persona (from the manifest) and
read server-side each turn; the model can neither see nor change it. A tool absent
from the dict falls back to DEFAULT_PERMISSIONS (then `ask`).
"""

from __future__ import annotations

AUTO = "auto"
ASK = "ask"
DENY = "deny"
PERMISSIONS = (AUTO, ASK, DENY)

# Default stance per tool when a manifest does not specify one: read-only tools
# run freely; the destructive `delete` asks. Built-in tools are gated by
# capability, not tool name: `read` covers every filesystem read (view/grep/glob)
# and `write` covers every filesystem write (edit/create), which the SDK surfaces
# indistinguishably as `read`/`write` permission requests. Both ask by default so
# a read/write surfaces the permission widget until a manifest opts it to `auto`.
DEFAULT_PERMISSIONS: dict[str, str] = {
    "inspect_tree": AUTO,
    "list_data": AUTO,
    "get_data": AUTO,
    "add": AUTO,
    "delete": ASK,
    "spawn_child": AUTO,
    "read": ASK,
    "write": ASK,
}


def permission_for(config: dict[str, str] | None, tool: str) -> str:
    """Resolve the permission for `tool`: the agent's config wins, else the
    built-in default, else `ask` for an unknown tool."""
    if config and tool in config:
        value = config[tool]
        if value in PERMISSIONS:
            return value
    return DEFAULT_PERMISSIONS.get(tool, ASK)
