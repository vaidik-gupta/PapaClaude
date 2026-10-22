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

1. **Remember grants / "allow all" [build].** An `ask`→allow should be able to
   stick, so a batch of calls isn't a prompt storm.
   - **Native path (built-in tools):** return `PermissionDecisionApproveForSession`
     from `on_permission_request` when the widget's "Allow for this turn/session"
     option is chosen — the SDK then stops re-prompting for that tool/location.
     `PermissionDecisionApproveForLocation` gives per-path grants for free.
   - **Custom path (our tools):** lean rule unchanged — remember an allow
     **per-tool for the rest of the turn** on the `WidgetBridge`; destructive
     tools (`delete`) still always ask unless "Allow for this turn" is chosen.
   - Add an **"Allow for this turn"** option to the permission widget (keyboard:
     a third selectable option) — one UI, mapped to the right mechanism per path.

2. **Widget timeout [build].** A pending widget must not hang a turn forever.
   - `present_widget(..., timeout=DEFAULT_WIDGET_TIMEOUT)`; on expiry emit
     `widget_response status=timeout`, raise `WidgetTimeout` (a sibling of
     `WidgetCancelled`), the tool returns a failure `ToolResult`.
   - Default ~120s; make it a constant. Frontend shows a countdown or a muted
     "expires soon" hint (nice-to-have).

3. **Tab-switch / reload resilience.** `ChatPane` is keyed on conversation id, so
   switching tabs mid-widget unmounts it → aborts the SSE fetch → backend
   `cancel_all` ends the turn; a reload loses the in-flight turn entirely.
   - Minimum: **warn** before switching away from a streaming tab, or keep the
     stream alive when a pane is backgrounded.
   - Full fix (later): server-side **turn replay** — persist in-flight turn
     events and a pending-widget marker so a reconnecting client can resume.

4. **Single-process assumption (document).** `pending_widgets` is an in-memory
   global; `respond` works only because uvicorn runs one event loop. Multiple
   workers would break cross-request resolution. Document the constraint now;
   a shared store (Redis pub/sub or DB-backed future) is a scaling-time task.

5. **Parallel tool calls.** Today only one widget blocks at a time; if the model
   batches tool calls that each want a widget, behavior is undefined.
   - Decide: **serialize** (queue widgets, present one at a time) vs. allow
     multiple stacked widgets. Lean: serialize this week (a FIFO on the bridge),
     stacked UI later.

### Widget kinds — the arsenal needs these

6. **Diff-review widget [build].** For edit/write tools: show a unified diff
   (path + before/after), Allow / Deny (/ "Allow for this turn").
   - **Built-in writes give this for free:** `PermissionRequestWrite` already
     carries `file_name`, a ready `diff` string, and `new_file_contents`. The
     async `on_permission_request` maps that straight into a `widget_id="diff"`
     payload; the answer becomes `ApproveOnce`/`ApproveForSession`/`Reject`. No
     tool-side diff computation needed.
   - For our own future custom edit tools, same widget, payload `{path, diff}`.

7. **Choice widget [build].** A thin wrapper tool (`ask_choice`) presenting N
   options; response is the chosen value. Keyboard-navigable like the permission
   widget. This is W43's "Pattern 2 — thin interaction tool."

8. **Free-text question widget.** `ask_user(question)` → a text input widget →
   returns the user's string. Lowest effort; pairs with choice.

### Permissions UX

9. **Permission config UI [build].** Surface `persona.permissions` in
   `PersonaPanel`: a small table of `{tool → auto|ask|deny}` with selects, saved
   via the existing persona-patch endpoint. Today it can only be set by editing
   manifest YAML.

10. **Grammar growth (later).** Flat per-tool is fixed for now; path/scope
    scoping (e.g. `delete` auto under the project dir, ask elsewhere) and
    capability classes are future work.

### The arsenal itself

11. **Filesystem / bash / edit tools [build, phased] — ENABLE, don't rebuild.**
    Per the SDK discovery, these are **built-in**; the work is configuration +
    the native permission bridge, not reimplementation.
    - **Enable + scope:** set `available_tools` (a `ToolSet`) on `create_session`
      so the agent gets built-in `view`/`read_file`, `grep`, `Glob`,
      `write_file`/edit, and (phase 2) `shell`/`bash`, all rooted at the agent's
      `working_directory` (the W43 directory attachment).
    - **Replace blanket approval:** swap `on_permission_request=approve_all` for
      an **async handler** that maps the per-agent `{tool: auto|ask|deny}` config
      → `ApproveOnce` / present-widget / `Reject`, feeding the W43 `WidgetBridge`.
    - **Proposed defaults** in `DEFAULT_PERMISSIONS` (native tool names):
      `read_file`/`view`, `grep`, `Glob` → `auto`; `write_file`/edit → `ask`
      (diff widget); `shell`/`bash` → `ask` (always; never remembered);
      `change_directory` → `ask`.
    - Phase 1: read-only + `write_file`/edit behind the diff widget. Phase 2:
      `bash` with explicit per-call confirmation and no remembering.

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
   native `ApproveForSession` for built-ins) + widget timeout +
   serialize-widgets. *(Items 1, 2, 5.)*
2. **Widget kinds:** diff (from native `PermissionRequestWrite.diff`) + choice +
   question widgets. *(Items 6, 7, 8.)*
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
- **Tool name mapping:** confirm the exact runtime tool names
  (`view` vs `read_file`, `shell` vs `bash`, `Glob` casing) by enumerating a live
  session's registered tools before writing `DEFAULT_PERMISSIONS` keys.
- **Response schema validation:** still opaque per `widget_id`, or validate
  responses against a per-widget schema now that there are several kinds?
- **Serialized vs. stacked widgets** when tool calls are parallel (native hook
  gives each request a `tool_call_id`, which makes correlation tractable).
- **bash safety:** sandbox/allowlist, timeout, output capture, and whether it
  ever gets a remember-grant (lean: never — always `ApproveOnce` or `Reject`).
- **Children tools:** inherit Papa's permission config + `available_tools`, or
  get their own?
