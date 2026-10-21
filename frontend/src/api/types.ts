// Types mirrored directly from .claude/API_CONTRACT.md (v1).

export type Role = 'parent' | 'child';

export type ContentTool =
  | 'inspect_tree'
  | 'list_data'
  | 'get_data'
  | 'add'
  | 'delete';

export const CONTENT_TOOLS: ContentTool[] = [
  'inspect_tree',
  'list_data',
  'get_data',
  'add',
  'delete',
];

export interface Manifest {
  name: string;
  role: Role;
  description: string;
  system_prompt: string;
  model: string | null; // null => settings.copilot_model
  allowed_tools: ContentTool[];
  max_turns: number | null;
  permission_mode: string; // informational for now, e.g. "auto"
}

// PersonaSnapshot has the same shape as Manifest (bound onto a conversation).
export type PersonaSnapshot = Manifest;

export interface Conversation {
  id: string;
  owner: string;
  title: string | null;
  sdk_session_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  role: Role;
  parent_id: string | null;
  manifest_name: string;
  task: string | null;
  persona: PersonaSnapshot;
}

export type EventType =
  | 'assistant_text'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'system'
  | 'result'
  | 'error';

export interface AssistantTextPayload {
  text: string;
}
export interface ThinkingPayload {
  thinking: string;
}
export interface ToolUsePayload {
  id: string;
  name: string;
  input: unknown;
}
export interface ToolResultPayload {
  tool_use_id: string;
  content: unknown;
  is_error: boolean;
}
export interface ResultPayload {
  session_id: string;
  stop_reason: string;
  num_turns: number;
  total_cost_req: number;
  is_error: boolean;
  text: string;
}
export interface ErrorPayload {
  message: string;
}

// Generic event envelope from the contract.
export interface EventBase {
  id: string;
  conversation_id: string;
  turn_id: string;
  index: number;
  type: EventType;
  ts: string;
}

// Discriminated union on `type`, carrying the typed payload.
export type ConvEvent =
  | (EventBase & { type: 'assistant_text'; payload: AssistantTextPayload })
  | (EventBase & { type: 'thinking'; payload: ThinkingPayload })
  | (EventBase & { type: 'tool_use'; payload: ToolUsePayload })
  | (EventBase & { type: 'tool_result'; payload: ToolResultPayload })
  | (EventBase & { type: 'system'; payload: Record<string, unknown> })
  | (EventBase & { type: 'result'; payload: ResultPayload })
  | (EventBase & { type: 'error'; payload: ErrorPayload });

export interface Turn {
  turn: {
    id: string;
    conversation_id: string;
    prompt?: string;
    created_at?: string;
    [k: string]: unknown;
  };
  events: ConvEvent[];
}

export interface ConversationDetail {
  conversation: Conversation;
  turns: Turn[];
}

export interface Credentials {
  userName: string;
  userKey: string;
}

// spawn_child tool_result content shape.
export interface SpawnChildResult {
  child_id: string;
  title: string | null;
  manifest_name: string;
}
