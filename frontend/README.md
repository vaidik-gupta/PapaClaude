# PapaClaude Frontend

Dark-themed React + TypeScript + Vite UI for the PapaClaude persona/project system.
Built against `.claude/API_CONTRACT.md` (v1).

## Run

```bash
npm install
npm run dev      # dev server on http://localhost:5173
```

The dev server proxies `/conversations` and `/manifests` to the backend at
`http://localhost:8000`, so **the FastAPI backend must be running on :8000**.

Sign in with the local default credentials `admin` / `admin` (stored in
`localStorage` and sent as `X-User-Name` / `X-User-Key` on every request,
including the SSE turn stream).

## Build

```bash
npm run build    # tsc -b && vite build
```

## What's here

- `src/api/types.ts` — types mirrored from the contract.
- `src/api/auth.ts` — credential storage + auth headers.
- `src/api/client.ts` — typed API client for all endpoints, including
  `streamTurn()` which consumes the `POST /conversations/{id}/turns`
  `text/event-stream` via `fetch()` + `ReadableStream` (EventSource can't send
  auth headers).
- `src/components/` — Login, two-level tabs (in `App.tsx`), ChatPane (streaming
  chat with tool cards / thinking / result footer), PersonaPanel (live persona
  edit), NewProjectDialog, AddChildDialog, ManifestLibrary (CRUD).

## Notes

- When a `spawn_child` `tool_result` arrives on a Papa's stream, its children
  are refetched so the new child tab appears automatically.
- Persona edits apply from the conversation's next turn.
- The app is resilient to backend outages: fetch failures surface as toasts and
  empty states rather than crashing.
