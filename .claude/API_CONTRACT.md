# PapaClaude — Persona/Project API Contract (v1)

Single source of truth for the **backend** (FastAPI, `app/`) and **frontend**
(React+TS, `frontend/`) agents. Build against this exactly. If you must deviate,
stop and flag it — do not silently diverge.

Base URL (local): `http://localhost:8000`

## Concepts
- A **Papa** is a `role="parent"` Conversation. **"New project" = create a Papa.**
- A **Child** is a `role="child"` Conversation with `parent_id` pointing at its Papa.
- A **Manifest** is a persona template stored as a **YAML file on disk** in `.manifests/`.
- On conversation creation the manifest is **snapshotted** onto the conversation
  (`persona`). Editing a manifest file never mutates existing conversations.
- Papa and its children **share the same working dir** and the same owner → same
  content tree. Children do NOT get a separate cwd.

## Auth
Every request (including the SSE turn stream) sends headers:
```
X-User-Name: <username>
X-User-Key:  <key>
```
Local default creds: `admin` / `admin`.
> SSE note: the turn endpoint is a **POST with headers**, so the frontend MUST
> consume it via `fetch()` + `ReadableStream` (NOT `EventSource`, which is GET-only
> and cannot set headers).

---

## 1. Manifest (persona) library — YAML on disk

### Schema (`Manifest`)
```jsonc
{
  "name": "default-parent",          // unique; == filename stem
  "role": "parent",                  // "parent" | "child"
  "description": "…",
  "system_prompt": "…",
  "model": "claude-sonnet-5",        // null => settings.copilot_model
  "allowed_tools": ["inspect_tree", "list_data", "get_data", "add", "delete"],
  "max_turns": null,                 // int | null
  "permission_mode": "auto"          // informational for now
}
```
- Content tool names: `inspect_tree, list_data, get_data, add, delete`.
- For a **parent**, the runtime auto-adds `spawn_child` to the bound tools (do NOT
  require it in `allowed_tools`).
- Shipped defaults (seeded as real YAML files): `default-parent.yaml`
  (all content tools), `default-child.yaml` (`allowed_tools: []`).

### Endpoints
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/manifests?role=parent\|child` | — | `Manifest[]` |
| GET | `/manifests/{name}` | — | `Manifest` (404 if missing) |
| POST | `/manifests` | `Manifest` | `Manifest` (409 if name exists) |
| PUT | `/manifests/{name}` | `Manifest` (full) | `Manifest` |
| DELETE | `/manifests/{name}` | — | 204 (409 if it's a shipped default) |

---

## 2. Conversation model (extended)

`Conversation` gains:
```jsonc
{
  // …existing: id, owner, title, sdk_session_id, status, created_at, updated_at
  "role": "parent",                  // "parent" | "child"  (default "parent")
  "parent_id": null,                 // str | null (set on children)
  "manifest_name": "default-parent", // source manifest
  "task": null,                      // str | null: context string from spawn_child;
                                     //   null when the child was created via UI button
  "persona": { /* PersonaSnapshot: same shape as Manifest */ }
}
```

`GET /conversations/{id}` continues to return
`{ conversation, turns: [{ turn, events }] }` — now with the persona fields on
`conversation`.

### Project (Papa) endpoints
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/conversations` | `{ title?, manifest_name? }` | `Conversation` (role=parent) |
| GET | `/conversations?role=parent` | — | `Conversation[]` (default role=parent) |
| GET | `/conversations/{id}` | — | `ConversationDetail` |

- `manifest_name` defaults to `default-parent`; must resolve to a `role=parent`
  manifest (400 otherwise).

### Children endpoints
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/conversations/{id}/children` | — | `Conversation[]` |
| POST | `/conversations/{id}/children` | `{ manifest_name, title? }` | `Conversation` (role=child) |

- UI-created child gets **no context**: `task=null`. Manifest must be `role=child`.

### Live persona edit (both Papa & child)
| Method | Path | Body | Returns |
|---|---|---|---|
| PUT | `/conversations/{id}/persona` | partial: `{ system_prompt?, model?, allowed_tools?, max_turns?, permission_mode?, description? }` | `Conversation` |

- Patches the **bound snapshot**; takes effect from the conversation's **next turn**.
- `name`/`role` are immutable on a snapshot (ignore if sent).

---

## 3. Turns & events (SSE) — unchanged shape, works for Papa AND child

`POST /conversations/{id}/turns` body `{ "prompt": "…" }` → `text/event-stream`.
Each frame: `event: <type>\n data: <Event JSON>\n\n`.

`Event`:
```jsonc
{ "id","conversation_id","turn_id","index","type","payload","ts" }
```
`type` ∈ `assistant_text | thinking | tool_use | tool_result | system | result | error`.

Payloads:
- `assistant_text`: `{ "text" }`
- `thinking`: `{ "thinking" }`
- `tool_use`: `{ "id", "name", "input" }`
- `tool_result`: `{ "tool_use_id", "content", "is_error" }`
- `result` (terminal): `{ "session_id","stop_reason","num_turns","total_cost_req","is_error","text" }`
- `error`: `{ "message" }`

Frontend renders `tool_use`/`tool_result` as chat-style **tool cards** (tool name +
collapsible input + result), assistant text as bubbles, thinking as collapsible.

### spawn_child (parent-only tool)
Exposed to Papa's model as:
```
spawn_child(manifest_name: str, context: str, title?: str)
```
- `manifest_name`: a `role=child` manifest in the library.
- `context`: a plain string Papa generates → stored as the child's `task` and
  seeded into the child session (only channel for now).
- Result JSON (surfaced in the `tool_result` event `content`):
  `{ "child_id", "title", "manifest_name" }`.
- **Frontend behavior:** when a `tool_result` for a `spawn_child` `tool_use`
  arrives, refetch `GET /conversations/{papaId}/children` to reveal the new child tab.

---

## 4. Frontend UX (React + TS, dark theme)
- **Top-level tabs** = Papas/projects (`GET /conversations?role=parent`).
  A **"New Project"** action creates a Papa (pick a parent manifest).
- **Second-level tabs** (within the selected Papa) = the Papa itself + its children
  (`GET /conversations/{papaId}/children`). An **"Add Child"** action creates a
  child (pick a child manifest; no context).
- **Chat pane** per selected conversation: load history from
  `GET /conversations/{id}`, then stream new turns via the SSE POST. Render events
  like a modern chat app (streaming text, tool cards, thinking).
- **Persona panel**: view + live-edit the selected conversation's bound persona
  (`PUT …/persona`), and a **Manifest Library** manager (CRUD `/manifests`).

## Out of scope for v1 (deferred)
- `ask_papa` / additional child→Papa channels (only the `context` string for now).
- ContextEngine assembly. Child gets only its manifest + (if spawned by tool) the
  `context` string.
