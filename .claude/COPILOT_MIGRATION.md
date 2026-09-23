# PapaClaude — Migration Plan: Claude Agent SDK → GitHub Copilot SDK

## Why

We are losing the Claude.ai subscription (the OAuth token from `claude setup-token`)
and have no Anthropic API key. The GitHub Copilot SDK (GA June 2026, `pip install
github-copilot-sdk`) is the first-party analog: same agent runtime (planning, tool
calls, streaming, MCP, session management), and — crucially — it authenticates with a
**GitHub OAuth token backed by the Copilot subscription**, not a pay-as-you-go key.
Copilot also serves Claude models, so we can keep running Claude under the hood
(`model="claude-sonnet-4.5"`).

## Scope: what moves and what doesn't

The SDK coupling is confined to two files. Everything else is provider-neutral and is
**not touched**.

| Area | Files | Change |
|------|-------|--------|
| Agent harness | `app/agent/client.py` | Rewrite against Copilot SDK |
| Agent tools | `app/agent/tools.py` | Re-express 5 content tools as Copilot tools |
| Config | `app/config.py`, `.env*` | Swap `anthropic_api_key` → `github_token` |
| Host/deploy | `docker-compose.yml`, README | Copilot runtime instead of `@anthropic-ai/claude-code` |
| Tests | `tests/` (agent unit tests) | Update to new event/message fakes |

**Untouched (verified against call sites):** `app/conversations/manager.py`,
`app/conversations/schema.py`, the whole `app/api/*`, `app/content/*`, `app/auth/*`,
`app/db/*`, `app/loaders/*`. The manager only depends on:
- `run_turn(prompt, *, owner, resume_session_id) -> AsyncIterator[AgentEvent]`
- `AgentEvent(type: EventType, payload: dict)`
- the `RESULT` payload keys it reads in `_finalize`: `text`, `stop_reason`,
  `num_turns`, `total_cost_req`, `is_error`, `session_id`.

**Contract to preserve:** keep `AgentEvent`, `EventType`, and the `run_turn` signature
exactly. The migration succeeds if the manager and API compile and run unchanged.

## Copilot SDK API we will use (confirmed from docs)

```python
from copilot import CopilotClient, define_tool
from copilot.tools import Tool
from copilot.session import PermissionHandler
from copilot.session_events import (
    AssistantMessageData, AssistantMessageDeltaData, SessionIdleData,
)

async with CopilotClient(github_token=token) as client:
    session = await client.create_session(
        model="claude-sonnet-4.5",
        system_message={"mode": "replace", "content": system_prompt},
        tools=[...],                                  # native tools
        on_permission_request=PermissionHandler.approve_all,   # == old dontAsk
        streaming=True,
    )
    session.on(on_event)          # callback listener
    await session.send_and_wait(prompt)
    # resume later:
    session = await client.resume_session(session_id, on_permission_request=...)
```

## 1. Dependencies & auth

- `pyproject.toml`: drop `claude-agent-sdk`, add `github-copilot-sdk`.
- `app/config.py`: replace `anthropic_api_key: str = ""` with `github_token: str = ""`
  (and optional `copilot_model: str = "claude-sonnet-4.5"`).
- `.env` / `.env.example`: replace `ANTHROPIC_API_KEY` with `GITHUB_TOKEN`
  (`gho_` / `ghu_` / `github_pat_` accepted). The token is a service-level credential,
  same single-credential shape we have today.
- Host: the SDK spawns a Copilot runtime process (like the old dependency on the Claude
  Code CLI). Update `docker-compose.yml` / image to install the Copilot runtime instead
  of `npm i -g @anthropic-ai/claude-code`, and drop the `claude setup-token` step.

> Multi-user note: today `owner` scopes *tools*, while model auth is one service
> credential. That stays. Per-user GitHub OAuth (each user's own Copilot subscription
> via the OAuth App code-exchange flow) is a **later** enhancement, not part of this
> swap.

## 2. `client.py` rewrite

Two adapters do all the work; the public surface (`AgentEvent`, `EventType`,
`run_turn`, `run_agent`) is unchanged.

### 2a. Session lifecycle
- Hold one module-level `CopilotClient(github_token=settings.github_token)` (opened
  once, like the current implicit CLI process).
- **We own the session id.** `create_session(session_id=...)` and
  `resume_session(session_id, ...)` both take the id as an argument, and there is *no*
  public `id`/`session_id` property on `CopilotSession` to read back. So: on the first
  turn generate a uuid, pass it as `session_id=` to `create_session`, and emit it in the
  `RESULT` event; on later turns call `resume_session(resume_session_id, ...)`. The
  manager's `_finalize` already persists it as `sdk_session_id` (first-turn save + change
  detection) — no manager change.
- Sessions are context managers (`async with session`) and `client.create_session` is a
  coroutine returning a `CopilotSession`. `permission_mode="dontAsk"` →
  `on_permission_request=PermissionHandler.approve_all`. `strict_mcp_config` has no
  analog (dropped — we pass native tools, not an MCP server).

### 2b. Callback → async-generator bridge
Copilot streams via `session.on(callback)`; our contract yields via `async for`. Bridge
with an `asyncio.Queue`:

```python
async def run_turn(prompt, *, owner, resume_session_id=None, system_prompt=None):
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    def on_event(event):
        for ev in _translate(event.data):     # new _translate over Copilot data types
            queue.put_nowait(ev)
        if isinstance(event.data, SessionIdleData):
            queue.put_nowait(None)            # sentinel: turn complete

    session = await _open_session(owner, resume_session_id, system_prompt)
    async with session:
        session.on(on_event)     # returns an unsubscribe fn; fine to ignore
        # NOTE: send_and_wait defaults to timeout=60.0 — far too short for an agent
        # turn. Pass a large timeout (e.g. 600) or a config value.
        send_task = asyncio.create_task(session.send_and_wait(prompt, timeout=600))
        try:
            while (ev := await queue.get()) is not None:
                yield ev
            await send_task            # surface any error raised by the turn
        finally:
            send_task.cancel()
```

Exceptions propagate to the manager (its `try/except` records an `ERROR` event) —
contract preserved. The turn error type is `copilot.StopError` (subclass of
`Exception`); a `SessionErrorData` event can also be mapped to our `ERROR` type inside
`_translate` for richer detail.

### 2c. New `_translate` (Copilot data types → our `EventType`)
Map `copilot.session_events` data classes onto the existing vocabulary:

All names/fields below are **verified against `github-copilot-sdk==1.0.14`**:

| Copilot event data (`copilot.session_events`) | Fields used | Our `EventType` | Payload |
|--------------------|-----------------|-----------------|---------|
| `AssistantMessageDeltaData` | `delta_content` | `ASSISTANT_TEXT` (streaming) | `{"text": delta_content}` |
| `AssistantMessageData` | `content` | `ASSISTANT_TEXT` (final) | `{"text": content}` |
| `AssistantReasoningData` | `content` | `THINKING` | `{"thinking": content}` (delta variant: `AssistantReasoningDeltaData`) |
| `ToolExecutionStartData` | `tool_call_id`, `tool_name`, `arguments` | `TOOL_USE` | `{"id": tool_call_id, "name": tool_name, "input": arguments}` |
| `ToolExecutionCompleteData` | `success`, `tool_call_id`, `result.content`, `error.message` | `TOOL_RESULT` | `{"tool_use_id": tool_call_id, "content": result.content if success else error.message, "is_error": not success}` |
| `AssistantUsageData` | `cost`, `finish_reason` | (fold into `RESULT`) | accumulate cost + last finish_reason |
| `SessionErrorData` | `error_type`, `message` | `ERROR` | `{"message": message}` |
| `SessionIdleData` | `aborted` | `RESULT` | see below (terminal signal) |

`RESULT` payload is assembled at idle from state accumulated during the turn:
```python
{
  "session_id": our_session_id,      # the uuid we supplied to create_session (§2a)
  "stop_reason": last_finish_reason, # from AssistantUsageData.finish_reason
  "num_turns": None,                 # no direct equivalent
  "total_cost_req": total_cost,      # SUM of AssistantUsageData.cost (it IS exposed)
  "is_error": bool(saw_error or SessionIdleData.aborted),
  "text": last_assistant_content,    # from the final AssistantMessageData.content
}
```
> Correction to the v1 draft: cost **is** available (`AssistantUsageData.cost: float |
> None`) and `stop_reason` maps to `AssistantUsageData.finish_reason`, so `TurnResult`
> keeps working as-is. Only `num_turns` has no clean source.

Keep `ASSISTANT_TEXT` semantics stable: either emit deltas (needs `streaming=True`) or
only the final message. Recommend **final-only first** (simplest, matches current
block-based behavior), add deltas as a follow-up.

### 2d. `run_agent` (single-shot)
Rewrite as a thin `create_session` → `send_and_wait` → return accumulated assistant
text. No resume, no tools (matches current `DEFAULT_SYSTEM_PROMPT` usage).

## 3. `tools.py` rewrite

The current design stays: `build_content_server(owner)` binds `owner` in a **closure**
(confused-deputy guard — never a tool parameter). Only the registration mechanism
changes from an in-process SDK MCP server to Copilot's native `Tool` list.

- Replace `create_sdk_mcp_server(...)` with a function returning `list[Tool]`
  (`from copilot import Tool`).
- Each of the 5 tools (`inspect_tree`, `list_data`, `get_data`, `add`, `delete`) becomes
  a `Tool(name=..., description=..., parameters=<existing JSON schema>, handler=...)`.
  The JSON-schema fragments (`_PATH`, `_PATH_ONLY`, and `add`'s object schema) port
  **verbatim** — `Tool.parameters` is a JSON-Schema `dict` (verified).
- **Handler contract (verified):** `handler: Callable[[ToolInvocation], ToolResult |
  Awaitable[ToolResult]]` — a single `ToolInvocation` arg with
  `.session_id / .tool_call_id / .tool_name / .arguments`. Read args from
  `invocation.arguments` (replaces today's `args` dict). Handlers stay `async` and keep
  `asyncio.to_thread` offloading.
- **Result shape changes** from the MCP `{"content":[...]}` dict to a `ToolResult`
  (`from copilot import ToolResult`):
  - success → `ToolResult(text_result_for_llm=<text>, result_type=...)`
  - error   → set `ToolResult.error=<msg>` (its own field, not an `is_error` flag).
  Rewrite `_ok`/`_err` to build `ToolResult`. (`ToolResultType` is required; confirm the
  success value when wiring — it's the one enum-ish value to pin down at code time.)
- `allowed_tools` / `SERVER_NAME` / `dontAsk` / `strict_mcp_config`: dropped. Tools go
  straight to `create_session(tools=[...])` and `on_permission_request=
  PermissionHandler.approve_all`. Per-tool `skip_permission=True` is also available on
  `Tool` if we want to bypass prompts at the tool level.

> Alternative: register the tools as an **MCP server** instead (Copilot supports MCP,
> tools surface as `<server-key>-<tool-name>`). Only worth it if we want the exact same
> `mcp__content__*` names elsewhere. Native `Tool` is simpler; recommend native.

## 4. Schema / metadata impact

- `TurnResult.total_cost_req` **is** populated (`AssistantUsageData.cost`, summed over the
  turn) — no schema change, keeps working. (Corrects the v1 assumption.)
- `stop_reason` ← `AssistantUsageData.finish_reason`. `num_turns` → `None` (no clean
  source). Both already nullable — no schema change.
- `sdk_session_id` semantics unchanged, but the value is now a uuid **we generate and
  supply** to `create_session(session_id=...)`, not one the SDK hands back.

## 5. Open items — VERIFIED against `github-copilot-sdk==1.0.14`

All five resolved by introspecting the installed package:

1. **Tool-call / tool-result events** — ✅ Yes, tool execution surfaces as events.
   Call = `ToolExecutionStartData` (`tool_call_id`, `tool_name`, `arguments`); result =
   `ToolExecutionCompleteData` (`success`, `tool_call_id`, `result.content`,
   `error.message`). (Also `ToolExecutionProgressData` / `ToolExecutionPartialResultData`
   for streaming progress — ignore for v1.) Mapping in §2c.
2. **Session id** — ✅ There is **no** public id property on `CopilotSession`
   (`__init__(session_id, client, ...)` stores it privately). Resolution: *we* supply the
   id via `create_session(session_id=<uuid>)` and reuse it for `resume_session`. No
   read-back needed. (`client.get_last_session_id()` also exists as a fallback.)
3. **Error channel** — ✅ `send_and_wait` raises `copilot.StopError` on failure (propagates
   to the manager). Additionally `SessionErrorData` events carry `error_type`/`message`;
   tool-handler failures are reported via `ToolResult.error`. Note `send_and_wait` has a
   **60s default timeout** — must be raised (§2b).
4. **Reasoning/thinking event** — ✅ Exists: `AssistantReasoningData` (`content`) and
   `AssistantReasoningDeltaData`. Maps to `THINKING`.
5. **Model availability** — ⚠️ Partially. The API is `client.list_models() ->
   list[ModelInfo]` (each `ModelInfo` has `id`, `name`, `capabilities`, `billing`). The
   *actual* set of available models depends on the authenticated Copilot plan and can
   only be confirmed with a real token. **One remaining runtime check** (needs a token):
   ```
   .venv/bin/python -c "import asyncio,copilot; \
     print([m.id for m in asyncio.run(copilot.CopilotClient(github_token='<gho_...>').list_models())])"
   ```
   Then set `settings.copilot_model` to a returned Claude id (e.g. `claude-sonnet-4.5`).

> Note: `create_session`/`resume_session` also natively accept `mcp_servers:
> dict[str, MCPServerConfig]` — so the §3 MCP alternative is fully supported if we ever
> want it. Native `Tool` remains the recommendation.

## 6. Test plan (goal-driven)

- **Unit — `_translate`:** feed constructed Copilot event-data objects, assert the exact
  `AgentEvent(type, payload)` sequence. Mirror of the current `_translate` test. →
  verify: same `EventType`s emitted for equivalent inputs.
- **Unit — tools:** call each handler with a fake `ResourceManager`, assert `owner` is
  bound and never taken from args; assert `_err` on `ValueError`. → verify: confused-
  deputy guard intact.
- **Integration — manager:** inject a fake `run_turn` async-gen (unchanged from today's
  test) → confirms the contract held, manager untouched.
- **E2E (`@pytest.mark.e2e`):** one real turn against Copilot with a test token; assert a
  `RESULT` event with a `session_id`, then a second turn resumes it.

## 7. Sequenced steps

1. Verify §5 open items against the installed SDK. → verify: names/attrs confirmed.
2. Swap deps + config + `.env` (§1). → verify: app boots, imports resolve.
3. Rewrite `tools.py` to `list[Tool]` (§3). → verify: tool unit tests pass.
4. Rewrite `client.py`: session lifecycle + queue bridge + `_translate` (§2). → verify:
   `_translate` unit tests pass; manager integration test passes with real `run_turn`
   shape (fake session).
5. Update host/deploy (§1) + README auth section. → verify: container starts, runtime
   present.
6. E2E turn + resume against Copilot (§6). → verify: two-turn conversation persists and
   resumes.
7. Delete now-dead Claude-SDK code paths (API-key bridge in old `client.py`, MCP
   `SERVER_NAME`/`allowed_tool_names` if unused elsewhere). → verify: no orphan imports.

## Effort

~2 files rewritten (~250 lines), config + deploy touch-ups, tests updated. The manager,
API, content, auth, and DB layers do not change. Risk is concentrated in the
callback→generator bridge and the event-name mapping (§5), both isolated to `client.py`.
