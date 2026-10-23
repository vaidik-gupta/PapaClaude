import type {
  ConvEvent,
  ResultPayload,
  ToolResultPayload,
  ToolUsePayload,
  WidgetResponsePayload,
} from '../api/types';
import { WidgetSummary } from '../widgets/WidgetSummary';

// A user prompt rendered as its own bubble (turns carry the prompt).
export interface UserBubble {
  kind: 'user';
  key: string;
  text: string;
}

interface EventStream {
  kind: 'events';
  key: string;
  events: ConvEvent[];
}

export type ChatBlock = UserBubble | EventStream;

function stringify(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ToolCard({
  use,
  result,
}: {
  use: ToolUsePayload;
  result?: ToolResultPayload;
}) {
  return (
    <div className="tool-card">
      <div className="tool-head">
        <span className="tool-tag">tool</span>
        <span className="tool-name">{use.name}</span>
      </div>
      <details>
        <summary>Input</summary>
        <pre>{stringify(use.input)}</pre>
      </details>
      {result && (
        <details className={result.is_error ? 'result error' : 'result'} open>
          <summary>{result.is_error ? 'Result (error)' : 'Result'}</summary>
          <pre>{stringify(result.content)}</pre>
        </details>
      )}
    </div>
  );
}

function ResultFooter({ payload }: { payload: ResultPayload }) {
  return (
    <div className="turn-footer">
      {payload.stop_reason ? `finish: ${payload.stop_reason}` : 'done'}
      {' · '}
      {payload.num_turns} turn{payload.num_turns === 1 ? '' : 's'}
      {' · '}
      {payload.total_cost_req} request
      {payload.total_cost_req === 1 ? '' : 's'}
    </div>
  );
}

// Render a flat event list into chat blocks, attaching each tool_result to its
// matching tool_use card (match on tool_use_id === tool_use.id).
export function renderEvents(events: ConvEvent[]) {
  const resultsByUseId = new Map<string, ToolResultPayload>();
  const responsesByInstanceId = new Map<string, WidgetResponsePayload>();
  for (const ev of events) {
    if (ev.type === 'tool_result') {
      resultsByUseId.set(ev.payload.tool_use_id, ev.payload);
    } else if (ev.type === 'widget_response') {
      responsesByInstanceId.set(ev.payload.instance_id, ev.payload);
    }
  }

  const nodes: JSX.Element[] = [];
  for (const ev of events) {
    switch (ev.type) {
      case 'assistant_text':
        if (ev.payload.text)
          nodes.push(
            <div className="msg-assistant" key={ev.id}>
              {ev.payload.text}
            </div>,
          );
        break;
      case 'thinking':
        nodes.push(
          <details className="thinking" key={ev.id}>
            <summary>Thinking</summary>
            <pre>{ev.payload.thinking}</pre>
          </details>,
        );
        break;
      case 'tool_use':
        nodes.push(
          <ToolCard
            key={ev.id}
            use={ev.payload}
            result={resultsByUseId.get(ev.payload.id)}
          />,
        );
        break;
      case 'tool_result':
        // Rendered inside its matching tool_use card; skip standalone.
        break;
      case 'widget':
        // A resolved widget replayed from history: read-only summary paired
        // with its recorded response (generic card unless the widget defines
        // its own summary component).
        nodes.push(
          <WidgetSummary
            key={ev.id}
            widgetId={ev.payload.widget_id}
            args={ev.payload.args}
            response={responsesByInstanceId.get(ev.payload.instance_id) ?? null}
          />,
        );
        break;
      case 'widget_response':
        // Rendered inside its matching widget summary; skip standalone.
        break;
      case 'system':
        break;
      case 'result':
        nodes.push(<ResultFooter key={ev.id} payload={ev.payload} />);
        break;
      case 'error':
        nodes.push(
          <div className="error-line" key={ev.id}>
            {ev.payload.message}
          </div>,
        );
        break;
    }
  }
  return nodes;
}
