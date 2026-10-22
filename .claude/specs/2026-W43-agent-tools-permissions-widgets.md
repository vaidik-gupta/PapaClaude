# Weekly Spec — 2026-W43 · Tools, Permissions & Widgets

**Week of:** 2026-10-21
**Theme:** Give the agent a real tooling layer. Three primitives — **tools** the
model sees, a per-agent **permission config** built from the manifest, and
**widgets** any tool can push to the UI mid-execution to involve the human.

> Supersedes the earlier "Agent ↔ User Interactions" draft. That draft split
> choice / permission / diff into three separate mechanisms (an `ask_user` tool,
> an `on_permission_request` tier gate, and diff-review wrappers) with a bespoke
> `interaction_request` event. We collapse all of that into **one primitive —
> the widget** — plus a permission config. Everything human-in-the-loop becomes
> "a tool presents a widget and waits."

---

## Motivation

A turn is one-directional today: prompt → stream → done. A tool runs to
completion and returns a `ToolResult`; it can never pause to involve the human.
Permissions are silently auto-approved (`PermissionHandler.approve_all`), and
`ChatEvents.tsx` renders everything read-only.

Rather than add bespoke machinery per interaction type, we add **one** general
mechanism and express every case on top of it.

---

## The three layers

1. **Tools** — the model-facing surface. A tool is still just
   `name + description + JSON schema`; that description (plus the system prompt)
   is the *only* way the model learns a capability exists. The model never sees
   permissions or widgets.
2. **Permissions** — a per-agent **permission config**, derived from the agent's
   manifest. Tools consult it to decide whether they already have access or must
   ask. Server-side, immutable from the model. For now it's a flat dict
   `{ tool: auto | ask | deny }` (see §Permission config).
3. **Widgets** — the universal human-in-the-loop primitive. **Any tool, at any
   point in its lifecycle, can present a widget and block on the user's
   response.** A widget is known to the backend only as an **`id` + `args`**; the
   frontend owns a registry mapping `id → React component`.

The elegance: with widgets as the one primitive, the other two interaction types
fall out for free —

- A **write/destructive tool** checks the permission config; if it lacks access
  it **presents a permission widget**, then proceeds or aborts on the answer.
- A **general question** to the user is just a **thin tool whose whole body is
  "present a choice widget, return the answer."**

---

## Core concept: the widget

### What it is
- **Backend view:** opaque. A widget instance is `{ widget_id, instance_id,
  args }`. The backend knows the id and the args it sent, and the typed response
  it gets back. It does **not** know how it looks.
- **Frontend view:** a full React component registered under `widget_id`. The
  registry renders it with `args` and hands it `respond(value)` / `cancel()`.

This keeps rendering entirely in the frontend (arbitrarily rich components) while
the backend/model stay rendering-agnostic.

### Lifecycle
```
tool handler                     backend bridge            SSE stream / UI
------------                     --------------            ---------------
value = await present_widget(      register pending
          id, args)      ───────▶ future(instance_id)
                                   emit `widget` event ───▶ registry[id] renders
                                   (id, instance_id, args)   component(args)
                                                             composer BLOCKED
                                   ◀── POST .../respond ───  user acts → respond(v)
          resolves ◀───────────── future.set_result(v)
tool continues with `value`                                 card → read-only
```

Cancellation (Esc / Stop / tab unmount) cancels the turn → the pending future is
**cancelled** → `present_widget` raises `WidgetCancelled` → the tool aborts
(typically returning a failure `ToolResult`) → the turn ends cleanly. This reuses
the existing Stop-button / Esc wiring.

### Blocking rule (for now)
**A pending widget blocks the chatbox.** The composer is disabled until the user
responds or cancels. One widget at a time per conversation. (Concurrent widgets
from parallel tool calls are out of scope — see Open questions.)

---

## Permission config (per-agent, from the manifest)

Every agent **builds a permission config from its manifest** when a turn starts.
Tools read it to decide "do I already have access, or must I ask (via a permission
widget)?"

- Lives server-side, per-agent; the model cannot read or mutate it.
- Built once per turn alongside the tool set (same seam as `owner` / `directory`).
- **For now the config is just a flat dict** `{ tool_name: permission }` where
  `permission` is one of:

  | Value  | Meaning                                                        |
  |--------|----------------------------------------------------------------|
  | `auto` | Allowed without asking — run immediately.                      |
  | `ask`  | Present a permission widget; run only if the user grants it.   |
  | `deny` | Never allowed — the tool returns a failure result, no widget.  |

  ```python
  # Example manifest-derived config
  {
      "inspect_tree": "auto",
      "get_data":     "auto",
      "add":          "ask",
      "delete":       "ask",
      "spawn_child":  "auto",
  }
  ```

  A tool missing from the dict falls back to a default (lean: `ask` for mutating
  tools, `auto` for read-only — final default TBD). The dict is the whole grammar
  this week; path/scope scoping comes later.

```python
perm = perms.get("delete", DEFAULT)      # "auto" | "ask" | "deny"
if perm == "deny":
    return _err("not permitted for this agent")
if perm == "ask":
    ok = await present_widget("permission", {"tool": "delete", "args": args, ...})
    if not ok["granted"]:
        return _err("user denied delete")
# perm == "auto" (or granted) → do the work
```

---

## Tools: the two patterns

The tool **declaration** is unchanged (name/description/schema — what the model
sees). What changes is what a handler may do internally.

### Pattern 1 — gated action tool (permission + optional diff)
`add` / `delete` (and future `edit`, `bash`, file tools):
1. look up `perms[tool]` → `deny` ⇒ failure result; `auto` ⇒ act; `ask` ⇒ step 2.
2. `present_widget("permission" | "diff", {...})` — a plain yes/no or a
   before/after review of the tool's **input**.
3. On grant ⇒ run the real work; on deny/cancel ⇒ failure `ToolResult`; nothing
   is written.

> The diff is the harness's rendering of the tool's input; the model only knows
> the tool exists and sees the final result.

### Pattern 2 — thin interaction tool
`ask_user` — its entire body is one widget:
```python
async def ask_user(inv):
    ans = await present_widget("choice", {
        "question": inv.arguments["question"],
        "options": inv.arguments.get("options"),
        "allow_free_text": inv.arguments.get("allow_free_text", True),
    })
    return _ok(ans["value"])
```
Declared to the model so it knows it *can* ask:
> "Ask the human and wait for an answer before continuing. Use when a decision
> materially changes your approach or requirements are ambiguous."

---

## Protocol & plumbing

### Per-turn bridge + global registry
Two pieces, because the **emit** side is per-turn but the **resolve** side is a
separate HTTP request:

- **`WidgetBridge` (per-turn):** holds the turn's event `queue` (already built in
  `run_turn`) so `present_widget` can push a `widget` event, and registers the
  pending future. Bound into the tool handlers at build time — `_build_tools` is
  already called **per-turn** inside `run_turn`, so tools can close over it just
  like `owner`/`directory` (confirmed in `app/agent/client.py`). A `contextvar`
  is the alternative if we don't want to widen every handler signature.
- **`PendingWidgets` (process-global):** `instance_id → Future`, so the
  `/respond` endpoint (a different coroutine) can resolve a future it didn't
  create. Keyed by `instance_id` (uuid) and validated against `conversation_id`.

### Event vocabulary
Extend `EventType` with:
- `widget` — payload `{ instance_id, widget_id, args }` (the present).
- `widget_response` — payload `{ instance_id, value, status: answered|cancelled }`
  (persisted so a reload replays a resolved widget as read-only/answered).

### Endpoint
`POST /conversations/{id}/widgets/{instance_id}/respond`
body: widget-specific JSON (e.g. `{ "value": "..."}` / `{ "granted": true }`)
→ looks up the future in `PendingWidgets`, validates ownership + conversation,
resolves it → the suspended tool (and the same SSE stream) continues.

### Cancel / timeout
- Stream cancelled (Stop/Esc/unmount) ⇒ cancel all pending futures for the turn.
- Optional per-widget timeout ⇒ cancel + failure result (value TBD).

---

## Frontend

### Widget registry
`frontend/src/widgets/registry.ts` — `Record<widget_id, WidgetComponent>` where

```ts
type WidgetProps<A, R> = {
  args: A;
  respond: (value: R) => void;   // POST .../respond
  cancel: () => void;            // Esc / Stop
};
```

Ship three widgets first:
- `choice` — question + option buttons + optional free-text (powers `ask_user`).
- `permission` — tool name + reason + **Allow / Deny**.
- `diff` — path + red/green before/after + **Approve / Reject**.

Unknown `widget_id` ⇒ a safe fallback card ("unsupported widget") that can still
cancel, so an older frontend never deadlocks a turn.

### Wiring
- `ChatPane` tracks `pendingWidget` (from the live `widget` event); while set, the
  composer is disabled and the widget is the focus.
- `respond`/`cancel` call the client fn; the SSE stream resumes; the card becomes
  read-only.
- **Tab status:** a distinct amber "needs-you" dot (alongside idle/streaming) when
  a widget is pending.
- Reload: resolved widgets render answered/disabled from `widget_response`.

---

## Deliverables / checklist

- [ ] `WidgetBridge` (per-turn) + `PendingWidgets` (global) + `present_widget()`.
- [ ] `EventType.WIDGET` + `WIDGET_RESPONSE` payloads (`schema.py`, `types.ts`).
- [ ] `POST /conversations/{id}/widgets/{instance_id}/respond` endpoint.
- [ ] Thread the bridge into `_build_tools` (contextvar or closure).
- [ ] Per-agent permission config from manifest — a `{ tool: auto|ask|deny }`
      dict — + lookup with a default.
- [ ] `ask_user` tool (Pattern 2).
- [ ] Gate `add`/`delete` via the config + permission/diff widget (Pattern 1);
      retire `approve_all` for gated tools.
- [ ] System-prompt line: mutating/destructive actions may be shown for approval;
      a denial is final.
- [ ] Frontend widget registry + `choice`/`permission`/`diff` components + unknown
      fallback.
- [ ] `ChatPane` gating, `respondWidget` client fn, amber "needs-you" tab dot.
- [ ] Cancel wiring: Stop/Esc cancels pending widgets → tool aborts cleanly.
- [ ] Tests: `present_widget` resolve + cancel, `ask_user` round-trip, a gated
      `delete` denied vs. approved, reload replay of a resolved widget;
      `pytest` + `ruff` + `tsc` + `vite build`.

---

## Open questions

- **Permission-config grammar:** the flat `{ tool: auto|ask|deny }` dict is fixed
  for now; later questions are where the manifest declares it and whether to grow
  to capability classes or path/scope scopes. Also: the fallback default for a
  tool absent from the dict.
- **Response typing:** does the backend validate a widget response against a
  per-`widget_id` schema, or stay fully opaque and trust the component?
- **Remembered grants:** does an `ask`→allow stick for the rest of the
  turn/session per tool, or prompt every time? (Lean: remember per-tool for the
  session; destructive always asks.)
- **Concurrency:** one blocking widget at a time (current plan) vs. a queue when
  parallel tool calls each want a widget.
- **Bridge delivery:** `contextvar` vs. widening tool-handler signatures to carry
  the bridge.
- **Timeout** for an unanswered widget.
