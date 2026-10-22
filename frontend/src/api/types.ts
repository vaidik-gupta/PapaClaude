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
  directory: string | null;
  manifest_name: string;
  task: string | null;
  persona: PersonaSnapshot;
}

export interface DirListing {
  path: string;
  parent: string | null;
  home: string;
  entries: string[];
}

export type EventType =
  | 'assistant_text'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'system'
  | 'result'
  | 'error'
  | 'widget'
  | 'widget_response';

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
  input_tokens?: number | null;
  output_tokens?: number | null;
  context_used?: number | null;
  context_window?: number | null;
  model?: string | null;
}
export interface ErrorPayload {
  message: string;
}
export interface WidgetPayload {
  instance_id: string;
  widget_id: string;
  args: Record<string, unknown>;
}
export interface WidgetResponsePayload {
  instance_id: string;
  status: 'answered' | 'cancelled';
  value?: Record<string, unknown>;
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
  | (EventBase & { type: 'error'; payload: ErrorPayload })
  | (EventBase & { type: 'widget'; payload: WidgetPayload })
  | (EventBase & { type: 'widget_response'; payload: WidgetResponsePayload });

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

// ---- Resources (content tree) ----

export type ResourceEngine = 'dynamodb' | 's3' | 'mongodb';

export const RESOURCE_ENGINES: ResourceEngine[] = ['dynamodb', 's3', 'mongodb'];

export type NodeKind =
  | 'engine'
  | 'group'
  | 'table'
  | 'bucket'
  | 'database'
  | 'collection'
  | 'item'
  | 'object'
  | 'document';

// The data-leaf kind per engine (lowest granularity; holds a payload).
export const DATA_KINDS: NodeKind[] = ['item', 'object', 'document'];

export interface ResourceNode {
  name: string;
  engine: ResourceEngine;
  kind: NodeKind;
  owner: string | null;
  permission: 'system' | 'owner';
  metadata: Record<string, unknown>;
  layer: number;
  children: ResourceNode[];
}

export interface ContentTreeDto {
  username: string;
  roots: ResourceNode[];
}

export interface DataResponse {
  path: string[];
  data: Record<string, unknown> | null;
}

export interface NodeResponse {
  path: string[];
  node: ResourceNode;
}
