"""Thin wrapper around the GitHub Copilot SDK.

Requires the Copilot runtime on the host (spawned by the SDK). Auth is a GitHub
token backed by a Copilot subscription (`gho_` / `ghu_` / `github_pat_`), set as
GITHUB_TOKEN; if unset the SDK falls back to the logged-in GitHub user.

The Copilot SDK is callback- and session-based, unlike the Claude SDK's async
`query()`. This module hides both differences behind the same seams the rest of
the app already depends on:
  * `run_turn(...) -> AsyncIterator[AgentEvent]` — a callback→queue bridge turns
    the SDK's `session.on(...)` stream back into an async iterator.
  * `AgentEvent` / `EventType` — our stable vocabulary, mapped in `_translate`.
The manager, API, and persistence layers are unchanged.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import uuid4

from copilot import CopilotClient, PermissionHandler, ToolSet
from copilot.session import CopilotSession
from copilot.session_events import (
    AssistantMessageData,
    AssistantReasoningData,
    SessionErrorData,
    SessionIdleData,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from copilot.session_events import (
    AssistantUsageData as _UsageData,
)

from app.agent.native_permissions import build_permission_handler
from app.agent.user_input import build_user_input_handler
from app.agent.tools import (
    build_content_tools,
    build_spawn_child_tool,
    gate_tools,
)
from app.agent.widgets import WidgetBridge
from app.config import settings
from app.conversations.schema import EventType
from app.logging_config import get_logger

logger = get_logger(__name__)

# Built-in SDK tools enabled for a turn, in addition to our custom tools. These
# are the read-type filesystem tools — `view` (read a file), `grep` (search
# contents), `glob` (match paths) — plus the write tools (`edit`/`create`), the
# shell (`bash`), web access (`web_fetch`/`web_search`), and the `ask_user`
# elicitation primitive. Each is gated by capability via the native permission
# hook (reads together, writes together, shell, url); see native_permissions.
ENABLED_BUILTIN_TOOLS = [
    "view",
    "grep",
    "glob",
    "edit",
    "create",
    "bash",
    "web_fetch",
    "web_search",
    "ask_user",
]


def _available_tools() -> ToolSet:
    """The explicit tool allowlist for a turn: every custom tool we register
    plus the enabled built-ins. Without this allowlist the runtime's built-in
    fs/shell tools would be silently reachable and auto-approved."""
    tools = ToolSet().add_custom("*")
    for name in ENABLED_BUILTIN_TOOLS:
        tools.add_builtin(name)
    return tools

# send_and_wait defaults to a 60s timeout — far too short for an agent turn.
TURN_TIMEOUT_SECONDS = 600.0


@dataclass
class AgentEvent:
    """One translated item from the SDK stream. The manager wraps this into a
    persisted domain Event (adding turn/conversation ids and an index)."""

    type: EventType
    payload: dict


# --- Copilot client lifecycle (one lazily-started runtime for the process) ----

_client: CopilotClient | None = None
_client_lock = asyncio.Lock()


# The Copilot CLI checks these before its stored OAuth token, so a stray value
# would shadow the device-login session. Stripped from the runtime env in local.
_TOKEN_ENV_VARS = ("GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN")


def _new_client() -> CopilotClient:
    """Build the Copilot client for the current environment.

    Local dev uses the logged-in Copilot user (device login via the Copilot/gh
    CLI). Token env vars are stripped from the spawned runtime so a stray
    GITHUB_TOKEN can't shadow the OAuth session — the CLI's credential order puts
    GITHUB_TOKEN ahead of the stored login.

    TODO(prod): use a Copilot-entitled, SSO-authorized token from the deployment
    secret store for non-local envs. (A personal fine-grained PAT does not carry
    an org Copilot seat, so it won't work for org-provisioned Copilot.)
    """
    if settings.environment == "local":
        logger.info("Copilot SDK auth: logged-in user (local)")
        env = {k: v for k, v in os.environ.items() if k not in _TOKEN_ENV_VARS}
        return CopilotClient(use_logged_in_user=True, env=env)
    token = settings.github_token.strip() or None
    logger.info("Copilot SDK auth: %s", "GITHUB_TOKEN" if token else "logged-in user")
    return CopilotClient(github_token=token)


async def _get_client() -> CopilotClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                c = _new_client()
                await c.start()
                _client = c
                logger.debug("Copilot runtime started")
    return _client


def _system_message(system_prompt: str | None) -> dict:
    """Append our persona instructions onto Copilot's built-in coding-agent
    system prompt rather than replacing it.

    `append` mode keeps the full CLI foundation — identity, tool-efficiency and
    parallel-calling guidance, code-change rules, safety guardrails, and per-tool
    instructions — and adds our persona content on top, so a persona is an
    *add-on* to Copilot's proven coding behavior, not a wholesale replacement.
    (`replace` mode, used previously, discarded all of that — including the SDK's
    security restrictions.) With no persona prompt we append nothing and run on
    the pure foundation.
    """
    content = (system_prompt or "").strip()
    message: dict = {"mode": "append"}
    if content:
        message["content"] = content
    return message


# --- Event translation --------------------------------------------------------


def _translate(data: object) -> Iterator[AgentEvent]:
    """Map one Copilot session-event `data` object into zero or more domain
    events. Pure and side-effect free so it can be unit-tested with constructed
    event data, no live session required. The terminal RESULT event is assembled
    separately by `_TurnState` because it aggregates across the whole turn.
    """
    if isinstance(data, AssistantMessageData):
        yield AgentEvent(EventType.ASSISTANT_TEXT, {"text": data.content})
    elif isinstance(data, AssistantReasoningData):
        yield AgentEvent(EventType.THINKING, {"thinking": data.content})
    elif isinstance(data, ToolExecutionStartData):
        yield AgentEvent(
            EventType.TOOL_USE,
            {"id": data.tool_call_id, "name": data.tool_name, "input": data.arguments},
        )
    elif isinstance(data, ToolExecutionCompleteData):
        content = data.result.content if (data.success and data.result) else None
        if content is None and data.error is not None:
            content = data.error.message
        yield AgentEvent(
            EventType.TOOL_RESULT,
            {
                "tool_use_id": data.tool_call_id,
                "content": content,
                "is_error": not data.success,
            },
        )
    elif isinstance(data, SessionErrorData):
        yield AgentEvent(EventType.ERROR, {"message": data.message})


class _TurnState:
    """Accumulates the pieces of the terminal RESULT event across a turn.

    Copilot reports the final answer, request cost, and finish reason across
    several events (assistant messages + per-call usage), so — unlike the Claude
    SDK's single ResultMessage — the RESULT payload is built up here and emitted on
    SessionIdleData. Copilot's `cost` is a premium-request count, not dollars.
    """

    def __init__(self) -> None:
        self.text = ""
        self.total_req: float | None = None
        self.finish_reason: str | None = None
        self.aborted = False
        self.saw_error = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.context_used: int | None = None
        self.context_window: int | None = None
        self.model: str | None = None

    def observe(self, data: object) -> None:
        if isinstance(data, AssistantMessageData):
            self.text = data.content  # last assistant message is the final answer
        elif isinstance(data, _UsageData):
            if data.cost is not None:
                self.total_req = (self.total_req or 0.0) + data.cost
            if data.finish_reason is not None:
                self.finish_reason = data.finish_reason
            if data.input_tokens is not None:
                self.input_tokens += data.input_tokens
                self.context_used = data.input_tokens  # last call's prompt size
            if data.output_tokens is not None:
                self.output_tokens += data.output_tokens
            if data.max_prompt_tokens is not None:
                self.context_window = data.max_prompt_tokens
            if data.model is not None:
                self.model = data.model
        elif isinstance(data, SessionErrorData):
            self.saw_error = True
        elif isinstance(data, SessionIdleData):
            self.aborted = bool(data.aborted)

    def result_payload(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "stop_reason": self.finish_reason,
            "num_turns": None,  # no clean Copilot equivalent
            "total_cost_req": self.total_req,
            "is_error": self.saw_error or self.aborted,
            "text": self.text,
            "input_tokens": self.input_tokens or None,
            "output_tokens": self.output_tokens or None,
            "context_used": self.context_used,
            "context_window": self.context_window,
            "model": self.model,
        }


# --- Turn execution -----------------------------------------------------------


def _build_tools(
    owner: str,
    allowed_tools: list[str] | None,
    role: str | None,
    conversation_id: str | None,
    permissions: dict[str, str] | None = None,
    bridge: WidgetBridge | None = None,
) -> list:
    """Assemble the session's tools: the persona's allowed content tools, plus
    the parent-only `spawn_child` tool for a parent conversation. Every tool is
    then wrapped once by `gate_tools`, so permission handling is uniform and new
    tools are gated automatically."""
    tools = build_content_tools(owner, allowed=allowed_tools)
    if role == "parent" and conversation_id is not None:
        tools.append(build_spawn_child_tool(owner, conversation_id))
    return gate_tools(tools, permissions, bridge)


async def _open_session(
    client: CopilotClient,
    owner: str,
    resume_session_id: str | None,
    new_session_id: str,
    system_prompt: str | None,
    tools: list,
    permission_handler,
    user_input_handler=None,
    working_directory: str | None = None,
) -> CopilotSession:
    """Create a fresh session (bound to a session id we own) or resume one.

    The agent's tool surface is an explicit allowlist (`_available_tools`): our
    user-bound custom tools plus the enabled built-ins — every other built-in
    (bash/edit/grep/…) stays unreachable. Custom tools are pre-approved; built-in
    tools are gated by `permission_handler`, which maps the per-agent
    `{auto|ask|deny}` config onto native decisions and routes `ask` to a widget.
    The built-in `ask_user` tool routes through `user_input_handler` to a
    choice/question widget. `working_directory` attaches the agent to a
    filesystem directory.
    """
    kwargs = {
        "model": settings.copilot_model or None,
        "tools": tools,
        "system_message": _system_message(system_prompt),
        "available_tools": _available_tools(),
        "on_permission_request": permission_handler,
    }
    if user_input_handler is not None:
        kwargs["on_user_input_request"] = user_input_handler
    if working_directory:
        kwargs["working_directory"] = working_directory
    if resume_session_id:
        return await client.resume_session(resume_session_id, **kwargs)
    return await client.create_session(session_id=new_session_id, **kwargs)


@dataclass
class _Failure:
    """Sentinel pushed onto the bridge queue when the turn raises."""

    exc: BaseException


async def run_turn(
    prompt: str,
    *,
    owner: str,
    resume_session_id: str | None = None,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    role: str | None = None,
    conversation_id: str | None = None,
    working_directory: str | None = None,
    permissions: dict[str, str] | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run one turn, resuming the given session, and stream translated events.

    We own the session id: on the first turn a uuid is generated and supplied to
    `create_session`, then emitted in the RESULT event so the manager persists it
    and resumes it next turn. Exceptions from the SDK propagate to the caller
    (the manager records the turn as errored).
    """
    client = await _get_client()
    session_id = resume_session_id or uuid4().hex
    queue: asyncio.Queue[AgentEvent | _Failure | None] = asyncio.Queue()
    state = _TurnState()
    bridge = WidgetBridge(
        emit=lambda etype, payload: queue.put_nowait(AgentEvent(etype, payload)),
        conversation_id=conversation_id or session_id,
    )

    def on_event(event) -> None:
        data = event.data
        for ev in _translate(data):
            queue.put_nowait(ev)
        state.observe(data)
        if isinstance(data, SessionIdleData):
            queue.put_nowait(AgentEvent(EventType.RESULT, state.result_payload(session_id)))

    tools = _build_tools(owner, allowed_tools, role, conversation_id, permissions, bridge)
    permission_handler = build_permission_handler(permissions, bridge, working_directory)
    user_input_handler = build_user_input_handler(bridge)
    session = await _open_session(
        client,
        owner,
        resume_session_id,
        session_id,
        system_prompt,
        tools,
        permission_handler,
        user_input_handler,
        working_directory,
    )
    logger.debug("Running turn for %s (resume=%s)", owner, resume_session_id)

    async def _drive() -> None:
        try:
            await session.send_and_wait(prompt, timeout=TURN_TIMEOUT_SECONDS)
        except BaseException as exc:  # noqa: BLE001 — relay to the consumer verbatim
            queue.put_nowait(_Failure(exc))
        finally:
            queue.put_nowait(None)  # always terminate the stream

    async with session:
        session.on(on_event)
        drive_task = asyncio.create_task(_drive())
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, _Failure):
                    raise item.exc
                yield item
        finally:
            # Unblock any tool still awaiting a widget before we join the
            # driver, otherwise send_and_wait could deadlock on a pending future.
            bridge.cancel_all()
            await drive_task


async def run_agent(prompt: str, system_prompt: str | None = None) -> str:
    """Run a single-turn, tool-less query and return the assistant's text."""
    client = await _get_client()
    chunks: list[str] = []

    def on_event(event) -> None:
        if isinstance(event.data, AssistantMessageData):
            chunks.append(event.data.content)

    session = await client.create_session(
        model=settings.copilot_model or None,
        system_message=_system_message(system_prompt),
        on_permission_request=PermissionHandler.approve_all,
    )
    async with session:
        session.on(on_event)
        await session.send_and_wait(prompt, timeout=TURN_TIMEOUT_SECONDS)
    return "".join(chunks)
