# Weekly Spec — 2026-W44 · Tool Arsenal, Richer Widgets & Permission Hardening

**Week of:** 2026-10-28
**Theme:** Make the tooling layer from W43 actually *usable*. W43 shipped the
three primitives (tools, a per-agent permission config, and the widget as the
unifying human-in-the-loop mechanism) with one permission widget gating `delete`
via a central `gate_tools` wrapper. This week we grow the **arsenal** (filesystem
/ bash / edit), add the **widget kinds** those tools need (diff, choice,
question), and **harden the permission flow** so a real workload isn't death by a
thousand prompts.

> **Major revision after SDK capability discovery (2026-10-22).** The Copilot
> SDK already ships the fs/bash/edit arsenal as **built-in tools**, and its
> native `on_permission_request` hook can be **awaited** (bridge to a widget) and
> carries rich typed payloads — including a ready-made **diff** for writes and an
> **approve-for-session** decision (remember-grants). This turns most of the
> "arsenal" from *implementation* into *configuration + a permission bridge*. See
> the new **SDK Capability Discovery** section — it reshapes items 1, 6, and 11.

> Builds directly on `2026-W43-agent-tools-permissions-widgets.md`. The widget
> primitive, `WidgetBridge` / `PendingWidgets`, the `widget` / `widget_response`
> events, the `{tool: auto|ask|deny}` config, and `gate_tools` are all in place
> and unchanged in concept — we extend them.

---

## Motivation

After W43 the plumbing works end-to-end, but a few gaps block real use:

- With a real arsenal, every `ask` tool prompts on **every** call — deleting five
  files means five identical prompts.
- There is **one** widget kind (permission). Edit/write/bash tools need
  **diff**, **choice**, and **free-text** interactions.
- An unanswered widget holds the SSE connection and SDK session open **forever**.
- Switching tabs or reloading mid-widget silently **kills the turn**.
- There is **no UI** to see or change an agent's permission config.

This week closes the highest-leverage of these so the arsenal lands on solid
ground.

---

## SDK Capability Discovery (reshapes the plan)

Empirically verified against the installed `copilot` SDK
(`/Users/vaidikg/MyMaid/.venv/.../copilot/`) on 2026-10-22.

**1. The arsenal already exists as built-in tools.** In our default
`mode="copilot-cli"` client, the runtime registers built-in `view`/`read_file`,
`write_file`/edit, `shell`/`bash`, `grep`, `Glob`, plus the orchestration set
(`ask_user`, `task`, `skill`, `read_agent`, …). You scope them with
`create_session(available_tools=..., excluded_tools=...)` using a `ToolSet`
(`ToolSet().add_builtin("bash")`, patterns like `builtin:*`, `custom:my_tool`,
`mcp:*`). So **we do not hand-write read/edit/bash** — we enable and scope the
built-ins.

- **Security note (fix now-ish):** we currently pass **only** our custom
  `tools=` and `on_permission_request=PermissionHandler.approve_all`, and never
  set `available_tools`/`excluded_tools`. In copilot-cli mode that means the
  built-in fs/shell tools are **reachable and silently auto-approved** — the
  `_open_session` docstring claim that the agent is "sandboxed to a per-user
  content tool surface" is inaccurate. First task this week: set an explicit
  `available_tools` allowlist (or `excluded_tools`) and stop blanket-approving.

**2. The native permission hook can drive our widgets.** `_PermissionHandlerFn`
returns `... | Awaitable[...]`, so `on_permission_request` can be **async and
block on a human response** — exactly what a widget needs. The request is a
typed union carrying everything a widget must render:

| Variant | Key fields |
|---|---|
| `PermissionRequestWrite` | `file_name`, **`diff`**, `new_file_contents`, `resolved_path`, `can_offer_session_approval` |
| `PermissionRequestShell` | `commands`, `full_command_text`, `resolved_paths`, `warning`, `intention` |
| `PermissionRequestRead` | `path`, `resolved_path` |
| `PermissionRequestCustomTool` | `tool_name`, `tool_description`, `args`, `skip_permission` |

Each carries a `tool_call_id`, so a handler can correlate concurrent requests.

**3. Remember-grants and the diff widget are effectively free.** Decision
results already include `PermissionDecisionApproveOnce`,
**`PermissionDecisionApproveForSession`** (= remember for session),
`PermissionDecisionApproveForLocation` (per-path), `PermissionDecisionApprovePermanently`,
and reject/deny variants. And `PermissionRequestWrite.diff` is a ready-made
unified diff. So item 1 (remember-grants) and item 6 (diff widget) are largely
*native* rather than hand-built.

**4. `ask_user` is a native built-in** with its own user-input request path — the
free-text question widget (item 8) may be a thin bridge rather than a custom
wrapper tool.

### Resulting architecture decision

Two permission surfaces, one UI:

- **Built-in tools** (fs/bash/edit) → gated through the SDK's native
  `on_permission_request`, which we make **async** and route to the **same**
  widget overlay (`present_widget`) we built in W43, mapping the typed request →
  widget payload and the widget's answer → `ApproveOnce` / `ApproveForSession` /
  `Reject`.
- **Our custom content tools** (`get_data`, `delete`, `spawn_child`, …) → stay on
  the W43 `gate_tools` + `{auto|ask|deny}` config path (they surface as
  `PermissionRequestCustomTool`, so unifying them onto the native hook is a
  possible later simplification — see open questions).

Net effect: `on_permission_request` becomes the second producer feeding the
existing `WidgetBridge`, and the per-agent `{tool: auto|ask|deny}` config maps
onto native decision kinds (`auto`→approve, `ask`→present widget, `deny`→reject).

---

## Priorities (grounded gap list)

Ordered by leverage. Items marked **[build]** are proposed for this week; others
are captured here but may slip.

### Widget robustness (bites first in real use)

1. **Remember grants / "allow all" [build]. ✅ DONE (built-in tools).** An
   `ask`→allow can now stick, so a batch of calls isn't a prompt storm.
   - **Landed (built-in tools, native path):** the permission + diff widgets show
     a **third, scope-labelled** option whose text states exactly what persists
     (no generic "allow for session"). On selection the native handler returns the
     kind-specific decision; the Copilot runtime then stops re-prompting:
     - **write** → `ApproveForLocation(Write, location_key=<git root>)` — "Always
       allow writes in `<git root>`" (persisted across sessions; the SDK has no
       per-file grant, only per project location).
     - **shell** → `ApproveForSession(Commands[identifiers])` — "Approve `<cmd>`
       commands this session" (per command identifier).
     - **url** → `ApproveForSession(domain=<host>)` — "Approve calls to `<host>`
       this session" (per domain).
     - **read** → no remember option (once/deny only); reads don't advertise
       session approval and the only session grant would be *all* reads.
   - Scope flows as `{granted, scope: "once"|"remember"}`; `remember` →
     kind-specific decision, `once` → `ApproveOnce`. Only offered when the request
     exposes a sensible grant (`_remember_option`). Live-verified: url shows
     "Approve calls to example.com this session", shell shows the command label;
     both complete and the runtime remembers.
   - **Custom path (our tools) — DEPRECATED.** The per-turn remember on the
     `WidgetBridge` was an AI-introduced feature that was never required; it is
     **removed from scope**. Custom tools stay once/deny for now; a custom-tool
     remember mechanism can be revisited later if actually needed.

2. **Widget timeout — DROPPED.** ~~A pending widget must not hang a turn
   forever.~~ Product decision: **no timeouts.** A widget waits indefinitely for
   the user; queued widgets (item 5) simply wait their turn. No `WidgetTimeout`,
   no countdown, no auto-expiry. (A turn can still be ended explicitly via
   Stop/Esc, which cancels pending widgets as today.)

3. **Tab-switch / reload resilience.** ~~`ChatPane` is keyed on conversation id, so
   switching tabs mid-widget unmounts it → aborts the SSE fetch.~~
   - ✅ **Tab-switch: DONE in W43** — opened panes now stay mounted (hidden when
     not selected), so switching tabs no longer aborts an in-flight turn/widget;
     the Esc listener is scoped to the visible pane and tab status is tracked
     per-conversation. Also ✅ **resolved-widget replay** shipped (read-only
     summary cards in the transcript).
   - ❌ **Reload: explicitly descoped** — in-flight turns/widgets are *not*
     expected to survive a full page reload (product decision). The server-side
     turn-replay / detach-from-request work is **not** planned.

4. **Single-process assumption (document).** `pending_widgets` is an in-memory
   global; `respond` works only because uvicorn runs one event loop. Multiple
   workers would break cross-request resolution. Document the constraint now;
   a shared store (Redis pub/sub or DB-backed future) is a scaling-time task.

5. **Parallel tool calls [build].** Tool calls must be **async and run
   concurrently** — a tool only blocks when it is waiting on a widget, never on
   other tool calls. The SDK already dispatches batched tool calls as
   independent `asyncio` tasks (verified in `copilot/session.py`
   `_handle_broadcast_event` → one `create_task` per `ExternalToolRequestedData`,
   no client-side lock), and our handlers are `async` and offload sync I/O via
   `asyncio.to_thread`, so this already works end-to-end today.
   - **Concurrent execution within an agent:** a single agent can fire N tool
     calls at once (e.g. 6 `read_file`) and they execute in parallel.
   - **Concurrent execution across agents:** each agent/conversation runs its own
     turn + `WidgetBridge`, so agents run their tool calls independently and
     simultaneously; one agent's pending widget never blocks another's tools.
   - **Widgets are the *only* blocking point.** When a tool needs human input it
     awaits a widget; that `await` suspends only that one tool call.
   - **One widget at a time *per agent* (per-pane FIFO queue) — frontend only.**
     Each agent's pane shows **one** widget at a time. If that agent's tool calls
     request multiple widgets concurrently, the extras **queue per pane** and
     appear **one by one** in FIFO order — the next shows only after the current
     is answered/cancelled. Different agents (different panes) are independent and
     may each show their own widget at the same time; there is **no** global
     cross-agent queue.
     - **Implementation is frontend-only.** The backend already emits each
       `widget` event and awaits its own future immediately (all futures pending
       at once is fine). `ChatPane` just needs to turn its single
       `pendingWidget` slot into a FIFO array: enqueue incoming `widget` events,
       render only the head, dequeue on answer, then show the next. No backend /
       `WidgetBridge` / `PendingWidgets` change required.
     - **Fixes a current bug:** today `setPendingWidget(ev.payload)` *overwrites*
       an in-flight widget, so a second concurrent widget clobbers the first
       (whose future then hangs). The per-pane queue replaces last-wins with
       proper one-at-a-time ordering.
     - **No timeouts.** Queued widgets simply wait their turn; nothing expires.

### Widget kinds — the arsenal needs these

6. **Diff-review widget [build]. ✅ DONE.** For edit/write tools: show a unified
   diff (path + before/after), Allow / Deny (/ "Allow for this turn").
   - **Built-in writes give this for free:** `PermissionRequestWrite` already
     carries `file_name`, a ready `diff` string, and `new_file_contents`. The
     async `on_permission_request` maps that straight into a `widget_id="diff"`
     payload; the answer becomes `ApproveOnce`/`ApproveForSession`/`Reject`. No
     tool-side diff computation needed.
   - For our own future custom edit tools, same widget, payload `{path, diff}`.
   - **Landed:** `DiffWidget.tsx` (registry id `diff`) renders the unified diff
     with add/del/hunk coloring + keyboard Allow/Deny. Backend
     `native_permissions` maps `PermissionRequestWrite` → `"write"` key →
     `widget_id="diff"` with `{tool, file_name, diff, summary}`. `edit` and
     `create` are enabled (`ENABLED_BUILTIN_TOOLS`) and both surface as `write`
     (indistinguishable at the permission layer, like the reads). `write`
     defaults to `ask`. Live-verified: create + edit both route through the diff
     widget carrying a real git diff; "Allow left" "Deny→Reject" works.
     Remember-grant ("Allow for this turn") still pending (item 1).

7. **Choice widget [build]. ✅ DONE.** Presents N options; response is the
   chosen value. Keyboard-navigable like the permission widget.
   - **Used the built-in, not a custom tool.** `ask_user` is a *native* SDK tool
     whose elicitation request carries `{question, choices, allowFreeform}`. When
     `choices` is non-empty we render the `choice` widget. (A first pass added a
     custom `ask_choice` tool, but per "if it's built-in, use the built-in one"
     we route the native `ask_user` instead — one tool covers both kinds.)
   - **Landed:** `ChoiceWidget.tsx` (registry id `choice`) — question + option
     buttons, ↑/↓ + Enter. Backend `user_input.build_user_input_handler` maps the
     native `on_user_input_request` → choice widget → `{answer, wasFreeform}`.
     Live-verified end-to-end.

8. **Free-text question widget. ✅ DONE.** A text input → returns the user's
   string. Same built-in `ask_user` path: when it offers no `choices`, we render
   the `question` widget.
   - **Landed:** `QuestionWidget.tsx` (registry id `question`) — text input,
     Enter to submit (empty blocked), Esc cancels. `ask_user` enabled in
     `ENABLED_BUILTIN_TOOLS`; the handler returns `wasFreeform=True` for a typed
     answer. Live-verified: choice + free-text both round-trip through one
     `ask_user` call. **Note:** `ask_user` is SDK-reserved — a custom tool of
     that name is shadowed by the built-in's elicitation path (which errors with
     "user was unable to respond" if unhandled), so wiring the native handler is
     the only correct approach.

### Permissions UX

9. **Permission config UI [build].** Surface `persona.permissions` in
   `PersonaPanel`: a small table of `{tool → auto|ask|deny}` with selects, saved
   via the existing persona-patch endpoint. Today it can only be set by editing
   manifest YAML.

10. **Grammar growth (later).** Flat per-tool is fixed for now; path/scope
    scoping (e.g. `delete` auto under the project dir, ask elsewhere) and
    capability classes are future work.

### The arsenal itself

11. **Filesystem / bash / edit / web tools [build, phased] — ENABLE, don't rebuild. ✅ DONE (sans remember-grants).**
    Per the SDK discovery, these are **built-in**; the work is configuration +
    the native permission bridge, not reimplementation.
    - **Landed:** `ENABLED_BUILTIN_TOOLS` now enables read (`view`/`grep`/`glob`),
      write (`edit`/`create`), shell (`bash`), and web (`web_fetch`/`web_search`),
      plus `ask_user`. Each is gated by **capability** through the native
      `on_permission_request` hook: `read`→permission widget, `write`→diff widget,
      `shell`→permission widget (yes/no on `full_command_text`), `url`→permission
      widget (yes/no on the URL). All four default to `ask` in
      `DEFAULT_PERMISSIONS`. Live-verified: `bash` surfaces `Run \`echo …\``;
      `web_fetch` surfaces `Fetch https://…`, both through the permission widget.
    - **Remember-grants not yet wired** — shell/url are plain `ApproveOnce` /
      `Reject` for now (item 1 adds "Allow for this turn/session"). Per product
      decision shell should likely *never* be remembered (always ask).

12. **Children get tools.** `default-child` has an empty `allowed_tools`, so
    spawned workers can't act. Give children a sensible default tool set once the
    arsenal exists.

### Manifest tuning

13. **Tune the default manifests [build].** Set explicit `permissions` on
    `default-parent` / `default-child`, sharpen the system prompts for the new
    tools, and give children a working tool set. Consider a couple of extra
    personas (e.g. a read-only "reviewer", a scoped "editor").

### Testing / quality

14. **Frontend tests.** No component tests exist; the Playwright example needs
    the live agent. Add lightweight widget-registry / PermissionWidget unit tests
    (Vitest) and make at least one Playwright path mockable (stub the SSE stream)
    so CI doesn't require a live Copilot session.

---

## Proposed build set for the week

A tight, shippable slice (everything marked **[build]** above, phased):

0. **SDK permission bridge + tool scoping (new, foundational):** replace
   `on_permission_request=approve_all` with an async handler that maps the
   `{auto|ask|deny}` config → native decisions and routes `ask` to the widget
   overlay; set an explicit `available_tools` allowlist. This unblocks items 1,
   6, and 11 and closes the silent-auto-approve gap. *(SDK discovery §.)*
1. **Permission hardening:** remember-grant ("Allow for this turn/session", via
   native `ApproveForSession` for built-ins) + **per-pane widget FIFO queue
   (one widget at a time per agent; frontend-only; no timeouts). Parallel
   async tool calls already work (SDK-verified).** *(Items 1, 5.)*
2. **Widget kinds:** diff (from native `PermissionRequestWrite.diff`) + choice +
   question widgets. *(Items 6, 7, 8.)* ✅ **DONE** — diff via the write
   permission hook; choice + question via the built-in `ask_user` elicitation
   (`on_user_input_request`), not custom tools.
3. **Permission UI** in PersonaPanel. *(Item 9.)*
4. **Arsenal phase 1:** enable built-in read-only fs tools + `write_file`/edit
   behind the diff widget; `bash` deferred to phase 2. *(Item 11, partial.)*
5. **Manifest tuning** for the above. *(Item 13.)*

Deferred to a later week: full turn replay (3, full), multi-worker widget store
(4), permission grammar growth (10), `bash` (11 phase 2), broader test suite
(14).

---

## Open questions

- **Unify on the native hook?** Our custom tools surface as
  `PermissionRequestCustomTool`, so in principle `gate_tools` could be retired in
  favor of a single `on_permission_request` handler for *both* built-in and
  custom tools. Worth it, or keep the two paths (custom = `gate_tools`, built-in
  = native hook) for W44 and revisit? (Lean: keep both this week, unify later.)
- **Remember scope:** native `ApproveForSession`/`ApproveForLocation` (built-ins)
  vs. our per-turn bridge set (custom) — do we expose both as one "Allow for this
  turn/session" option, and should either persist back to the manifest as `auto`?
- **Diff source of truth:** built-in writes hand us `diff` directly; our own
  future edit tools send a unified diff string. Widget just renders — confirmed.
- **Tool name mapping (RESOLVED by live enumeration):** a live session registers
  the read-type built-ins as `view` (read file), `grep`, `glob` (lowercase), plus
  `edit`/`create`, `bash`, `web_fetch`/`web_search`, and the orchestration set.
  **Important permission finding:** `view`, `grep`, and `glob` are
  *indistinguishable at the permission layer* — each surfaces as a
  `PermissionRequestRead` (kind `read`) carrying only a `path`, never the tool
  name. So reads are gated by a **single `read` capability key**, not one key per
  tool; `DEFAULT_PERMISSIONS["read"]` governs all three. Per-tool read config is
  not possible via the native hook. (Write will map Shell/`bash`→"bash",
  Write/`edit`→"edit" similarly, by request kind.)
- **Response schema validation:** still opaque per `widget_id`, or validate
  responses against a per-widget schema now that there are several kinds?
- **Serialized widgets (DECIDED):** widgets are queued **per agent/pane** (a
  frontend FIFO in `ChatPane`) and shown one at a time; concurrent widgets from
  the same agent wait and appear one by one. Different agents (different panes)
  are independent and may each show a widget simultaneously — **no global
  cross-agent queue**. Non-widget tool calls are never serialized and run in
  parallel. No timeouts. Stacked UI is out of scope.
- **bash safety:** sandbox/allowlist, timeout, output capture, and whether it
  ever gets a remember-grant (lean: never — always `ApproveOnce` or `Reject`).
- **Children tools:** inherit Papa's permission config + `available_tools`, or
  get their own?
