import { authHeaders } from './auth';
import type {
  Conversation,
  ConversationDetail,
  ConvEvent,
  Manifest,
  Role,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { rawText?: boolean },
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...authHeaders(),
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    throw new ApiError(0, `Network error: ${(e as Error).message}`);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body === 'object' && 'detail' in body) {
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Manifests ----

export function listManifests(role?: Role): Promise<Manifest[]> {
  const q = role ? `?role=${role}` : '';
  return request<Manifest[]>(`/manifests${q}`);
}

export function getManifest(name: string): Promise<Manifest> {
  return request<Manifest>(`/manifests/${encodeURIComponent(name)}`);
}

export function createManifest(m: Manifest): Promise<Manifest> {
  return request<Manifest>('/manifests', {
    method: 'POST',
    body: JSON.stringify(m),
  });
}

export function updateManifest(name: string, m: Manifest): Promise<Manifest> {
  return request<Manifest>(`/manifests/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(m),
  });
}

export function deleteManifest(name: string): Promise<void> {
  return request<void>(`/manifests/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

// ---- Conversations (Papas / projects) ----

export function listProjects(): Promise<Conversation[]> {
  return request<Conversation[]>('/conversations?role=parent');
}

export function createProject(body: {
  title?: string;
  manifest_name?: string;
}): Promise<Conversation> {
  return request<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(
    `/conversations/${encodeURIComponent(id)}`,
  );
}

// ---- Children ----

export function listChildren(papaId: string): Promise<Conversation[]> {
  return request<Conversation[]>(
    `/conversations/${encodeURIComponent(papaId)}/children`,
  );
}

export function createChild(
  papaId: string,
  body: { manifest_name: string; title?: string },
): Promise<Conversation> {
  return request<Conversation>(
    `/conversations/${encodeURIComponent(papaId)}/children`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  );
}

// ---- Persona live edit ----

export type PersonaPatch = Partial<{
  system_prompt: string;
  model: string | null;
  allowed_tools: string[];
  max_turns: number | null;
  permission_mode: string;
  description: string;
}>;

export function updatePersona(
  convId: string,
  patch: PersonaPatch,
): Promise<Conversation> {
  return request<Conversation>(
    `/conversations/${encodeURIComponent(convId)}/persona`,
    {
      method: 'PUT',
      body: JSON.stringify(patch),
    },
  );
}

// ---- Turn stream (SSE over POST) ----
//
// EventSource cannot be used (GET-only, no custom headers). We use fetch() +
// a ReadableStream reader and parse SSE frames manually. Each frame is a block
// of lines terminated by a blank line; `event:` gives the type, `data:` (which
// may repeat) gives the JSON payload.

export interface StreamHandle {
  cancel: () => void;
}

export function streamTurn(
  convId: string,
  prompt: string,
  onEvent: (ev: ConvEvent) => void,
  onError: (err: Error) => void,
  onDone: () => void,
): StreamHandle {
  const controller = new AbortController();

  (async () => {
    let res: Response;
    try {
      res = await fetch(
        `/conversations/${encodeURIComponent(convId)}/turns`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...authHeaders(),
          },
          body: JSON.stringify({ prompt }),
          signal: controller.signal,
        },
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        onError(new Error(`Network error: ${(e as Error).message}`));
      }
      return;
    }

    if (!res.ok || !res.body) {
      onError(new ApiError(res.status, `Turn failed (${res.status})`));
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const dispatchFrame = (frame: string) => {
      const lines = frame.split('\n');
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
        // `event:` line is ignored for dispatch; the payload JSON carries `type`.
      }
      if (dataLines.length === 0) return;
      const dataStr = dataLines.join('\n');
      if (!dataStr || dataStr === '[DONE]') return;
      try {
        const ev = JSON.parse(dataStr) as ConvEvent;
        onEvent(ev);
      } catch {
        // Skip malformed frames rather than tearing down the whole stream.
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line. Handle both \n\n and \r\n\r\n.
        let sep: number;
        for (;;) {
          const idxN = buffer.indexOf('\n\n');
          const idxRN = buffer.indexOf('\r\n\r\n');
          if (idxN === -1 && idxRN === -1) break;
          let cut: number;
          if (idxRN !== -1 && (idxN === -1 || idxRN < idxN)) {
            sep = idxRN;
            cut = sep + 4;
          } else {
            sep = idxN;
            cut = sep + 2;
          }
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(cut);
          if (frame.trim()) dispatchFrame(frame);
        }
      }
      // Flush any trailing frame.
      if (buffer.trim()) dispatchFrame(buffer);
      onDone();
    } catch (e) {
      if (!controller.signal.aborted) {
        onError(new Error(`Stream error: ${(e as Error).message}`));
      }
    }
  })();

  return { cancel: () => controller.abort() };
}
