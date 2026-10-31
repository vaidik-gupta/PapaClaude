"""Bridge the Copilot SDK's native permission hook onto our widget overlay.

Built-in tools (fs/bash/edit) do not go through our custom `gate_tools` wrapper;
instead the runtime calls `on_permission_request` before invoking them. This
module turns that native hook into the *same* human-in-the-loop surface our
custom tools already use: the per-agent `{auto|ask|deny}` config decides, and an
`ask` routes to the W43 permission widget via the turn's `WidgetBridge`.

Mapping (native request kind -> permission-config key we gate it under):

    PermissionRequestRead  -> "read"    (filesystem-read capability)
    PermissionRequestWrite -> "write"   (filesystem-write capability)
    PermissionRequestShell -> "shell"   (bash)
    PermissionRequestUrl   -> "url"      (web fetch/search)

Each kind also chooses which widget surfaces on an `ask` (see `_WIDGET_ID`):
reads, shell, and url use the compact `permission` widget; writes use the `diff`
widget, which renders the proposed change (`PermissionRequestWrite.diff`) before
the user approves it.

Note on read-type tools: `view`, `grep`, and `glob` are all enabled (see
`client.ENABLED_BUILTIN_TOOLS`), but at the permission layer they are
*indistinguishable* — every one surfaces as `PermissionRequestRead` (kind
`read`) with a `path` and no tool name. So they share a single `read`
capability key rather than one key per tool; a decision for `read` governs all
three. The same holds for writes: `edit` and `create` both surface as
`PermissionRequestWrite` (kind `write`), so one `write` key governs both. Shell
(`bash`) is gated under `shell` and web fetch/search (`web_fetch`/`web_search`)
under `url`, again by request kind.

The config decision maps onto native decisions:

    auto -> PermissionDecisionApproveOnce
    deny -> PermissionDecisionReject
    ask  -> present the permission widget; grant -> ApproveOnce, else Reject
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit

from copilot.generated.rpc import (
    PermissionDecisionApproveForLocation,
    PermissionDecisionApproveForLocationApprovalWrite,
    PermissionDecisionApproveForSession,
    PermissionDecisionApproveForSessionApprovalCommands,
    PermissionDecisionApproveOnce,
    PermissionDecisionReject,
)
from copilot.generated.session_events import (
    PermissionRequest,
    PermissionRequestRead,
    PermissionRequestShell,
    PermissionRequestUrl,
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
    "shell": "permission",
    "url": "permission",
}


def _tool_key(request: PermissionRequest) -> str | None:
    """The permission-config key a native request is gated under, or None when
    the request kind is not one we natively gate yet.

    All filesystem reads (view/grep/glob) share the single `read` capability and
    all filesystem writes (edit/create) share the single `write` capability — the
    request carries the path/diff, never the originating tool name. Shell (`bash`)
    is gated under `shell`, and web fetch/search under `url` (by request kind)."""
    if isinstance(request, PermissionRequestRead):
        return "read"
    if isinstance(request, PermissionRequestWrite):
        return "write"
    if isinstance(request, PermissionRequestShell):
        return "shell"
    if isinstance(request, PermissionRequestUrl):
        return "url"
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
    if isinstance(request, PermissionRequestShell):
        command = request.full_command_text
        return {
            "tool": key,
            "args": {"command": command},
            "summary": f"Run `{command}`",
        }
    if isinstance(request, PermissionRequestUrl):
        return {
            "tool": key,
            "args": {"url": request.url},
            "summary": f"Fetch {request.url}",
        }
    return {"tool": key, "args": {}, "summary": f"Run {key}"}


@dataclass
class _Remember:
    """A "remember this grant" option for the permission widget.

    `label` is the exact scope shown on the widget button (so the user sees
    precisely what persists); `decision` is the native decision returned when the
    user picks it. One option per request kind — see `_remember_option`.
    """

    label: str
    decision: object


def _git_root(path: str | None) -> str | None:
    """The git top-level for `path` (or its directory), else `path` itself.

    Used as the `location_key` for a persisted write grant — the SDK stores a
    location grant under the project's git root / cwd, not a single file."""
    if not path:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return path


def _remember_option(
    key: str, request: PermissionRequest, working_directory: str | None
) -> _Remember | None:
    """The single "remember" grant offered for a request, or None when the kind
    offers no remembering (reads).

    Each option's `label` states exactly what the native decision persists:

      write -> ApproveForLocation(Write, git-root): all writes in the project
               location, persisted across sessions.
      shell -> ApproveForSession(Commands[...]): the specific command
               identifier(s), for the rest of this session.
      url   -> ApproveForSession(domain): calls to that domain, for the session.
    """
    if isinstance(request, PermissionRequestWrite):
        location_key = _git_root(working_directory or request.resolved_path)
        if not location_key:
            return None
        return _Remember(
            label=f"Always allow writes in {location_key}",
            decision=PermissionDecisionApproveForLocation(
                approval=PermissionDecisionApproveForLocationApprovalWrite(),
                location_key=location_key,
            ),
        )
    if isinstance(request, PermissionRequestShell):
        identifiers = [c.identifier for c in request.commands if c.identifier]
        if not identifiers:
            return None
        shown = ", ".join(f"`{i}`" for i in identifiers)
        return _Remember(
            label=f"Approve {shown} commands this session",
            decision=PermissionDecisionApproveForSession(
                approval=PermissionDecisionApproveForSessionApprovalCommands(
                    command_identifiers=identifiers
                )
            ),
        )
    if isinstance(request, PermissionRequestUrl):
        domain = urlsplit(request.url).hostname
        if not domain:
            return None
        return _Remember(
            label=f"Approve calls to {domain} this session",
            decision=PermissionDecisionApproveForSession(domain=domain),
        )
    return None


def build_permission_handler(
    permissions: dict[str, str] | None,
    bridge: WidgetBridge | None,
    working_directory: str | None = None,
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
        # Attach the kind's single "remember" option (if any) so the widget can
        # offer a clearly-labelled persistent grant alongside allow-once.
        widget_id = _WIDGET_ID.get(key, "permission")
        payload = _widget_payload(key, request)
        remember = _remember_option(key, request, working_directory)
        if remember is not None:
            payload["remember"] = {"label": remember.label}
        try:
            reply = await bridge.present_widget(widget_id, payload)
        except WidgetCancelled:
            return PermissionDecisionReject(feedback=f"'{key}' was cancelled before approval")
        if not reply.get("granted"):
            return PermissionDecisionReject(feedback=f"user denied '{key}'")
        if reply.get("scope") == "remember" and remember is not None:
            return remember.decision
        return PermissionDecisionApproveOnce()

    return handler
