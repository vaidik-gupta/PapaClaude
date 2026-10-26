"""Bridge the Copilot SDK's native permission hook onto our widget overlay.

Built-in tools (fs/bash/edit) do not go through our custom `gate_tools` wrapper;
instead the runtime calls `on_permission_request` before invoking them. This
module turns that native hook into the *same* human-in-the-loop surface our
custom tools already use: the per-agent `{auto|ask|deny}` config decides, and an
`ask` routes to the W43 permission widget via the turn's `WidgetBridge`.

Mapping (native request kind -> permission-config key we gate it under):

    PermissionRequestRead  -> "read"    (filesystem-read capability)
    PermissionRequestWrite -> "write"   (filesystem-write capability)

Each kind also chooses which widget surfaces on an `ask` (see `_WIDGET_ID`):
reads use the compact `permission` widget; writes use the `diff` widget, which
renders the proposed change (`PermissionRequestWrite.diff`) before the user
approves it.

Note on read-type tools: `view`, `grep`, and `glob` are all enabled (see
`client.ENABLED_BUILTIN_TOOLS`), but at the permission layer they are
*indistinguishable* — every one surfaces as `PermissionRequestRead` (kind
`read`) with a `path` and no tool name. So they share a single `read`
capability key rather than one key per tool; a decision for `read` governs all
three. The same holds for writes: `edit` and `create` both surface as
`PermissionRequestWrite` (kind `write`), so one `write` key governs both. As
exec built-ins land, add their kinds here (Shell -> "bash").

The config decision maps onto native decisions:

    auto -> PermissionDecisionApproveOnce
    deny -> PermissionDecisionReject
    ask  -> present the permission widget; grant -> ApproveOnce, else Reject
"""

from __future__ import annotations

from copilot.generated.rpc import (
    PermissionDecisionApproveOnce,
    PermissionDecisionReject,
)
from copilot.generated.session_events import (
    PermissionRequest,
    PermissionRequestRead,
    PermissionRequestWrite,
)

from app.agent.permissions import AUTO, DENY, permission_for
from app.agent.widgets import WidgetBridge, WidgetCancelled
from app.logging_config import get_logger

logger = get_logger(__name__)

# Which overlay widget surfaces on an `ask`, per permission-config key. Reads use
# the compact confirm card; writes use the diff widget so the user sees the
# proposed change before approving. Unlisted keys fall back to `permission`.
_WIDGET_ID: dict[str, str] = {
    "read": "permission",
    "write": "diff",
}


def _tool_key(request: PermissionRequest) -> str | None:
    """The permission-config key a native request is gated under, or None when
    the request kind is not one we natively gate yet.

    All filesystem reads (view/grep/glob) share the single `read` capability and
    all filesystem writes (edit/create) share the single `write` capability — the
    request carries the path/diff, never the originating tool name."""
    if isinstance(request, PermissionRequestRead):
        return "read"
    if isinstance(request, PermissionRequestWrite):
        return "write"
    return None


def _widget_payload(key: str, request: PermissionRequest) -> dict:
    """Build the permission-widget payload for a native request."""
    if isinstance(request, PermissionRequestRead):
        return {
            "tool": key,
            "args": {"path": request.path},
            "summary": f"Read {request.path}",
        }
    if isinstance(request, PermissionRequestWrite):
        return {
            "tool": key,
            "file_name": request.file_name,
            "diff": request.diff,
            "summary": f"Write {request.file_name}",
        }
    return {"tool": key, "args": {}, "summary": f"Run {key}"}


def build_permission_handler(
    permissions: dict[str, str] | None,
    bridge: WidgetBridge | None,
):
    """Build the async `on_permission_request` handler for one turn.

    Captures the per-agent permission config and the turn's widget bridge, so an
    `ask` decision can present a widget and block on the user's answer. When
    `bridge` is None (non-turn paths) an `ask` proceeds, since there is no stream
    to surface a widget on.
    """

    async def handler(request, invocation):  # noqa: ANN001 — SDK-typed union
        key = _tool_key(request)
        if key is None:
            # A request kind we don't gate yet. The tool allowlist already keeps
            # unscoped tools unreachable, so approve-once rather than hang/break.
            logger.warning(
                "Unmapped native permission request %s; approving once",
                type(request).__name__,
            )
            return PermissionDecisionApproveOnce()

        perm = permission_for(permissions, key)
        if perm == DENY:
            return PermissionDecisionReject(
                feedback=f"'{key}' is not permitted for this agent"
            )
        if perm == AUTO or bridge is None:
            return PermissionDecisionApproveOnce()

        # ASK: present the permission widget and block until the user answers.
        widget_id = _WIDGET_ID.get(key, "permission")
        try:
            reply = await bridge.present_widget(widget_id, _widget_payload(key, request))
        except WidgetCancelled:
            return PermissionDecisionReject(feedback=f"'{key}' was cancelled before approval")
        if reply.get("granted"):
            return PermissionDecisionApproveOnce()
        return PermissionDecisionReject(feedback=f"user denied '{key}'")

    return handler
