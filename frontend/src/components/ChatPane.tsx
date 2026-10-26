import { useEffect, useMemo, useRef, useState } from 'react';
import { getConversation, respondWidget, streamTurn } from '../api/client';
import type {
  Conversation,
  ConversationDetail,
  ConvEvent,
  ResultPayload,
  WidgetPayload,
} from '../api/types';
import { useToasts } from '../state/toasts';
import { resolveWidget } from '../widgets/registry';
import { renderEvents, type ChatBlock } from './ChatEvents';

interface ChatPaneProps {
  conversation: Conversation;
  // Called when a spawn_child tool_result is observed on this stream, so the
  // parent can refetch children and reveal the new tab.
  onSpawnChild: () => void;
  // Reports whether this pane is currently streaming a turn (for tab status).
  onStreamingChange?: (streaming: boolean) => void;
  // Reports whether a widget is awaiting the user's response (for tab status).
  onWidgetPendingChange?: (pending: boolean) => void;
  // When true, the pane stays mounted (keeping its turn/stream alive) but is
  // visually hidden — used so switching tabs does not abort an in-flight turn.
  hidden?: boolean;
}

interface ChatMetrics {
  cost: number;
  inputTokens: number;
  outputTokens: number;
  contextUsed: number | null;
  contextWindow: number | null;
  model: string | null;
}

function summarizeMetrics(events: ConvEvent[]): ChatMetrics | null {
  const results = events
    .filter((e): e is Extract<ConvEvent, { type: 'result' }> => e.type === 'result')
    .map((e) => e.payload as ResultPayload);
  if (results.length === 0) return null;

  let cost = 0;
  let inputTokens = 0;
  let outputTokens = 0;
  let contextUsed: number | null = null;
  let contextWindow: number | null = null;
  let model: string | null = null;

  for (const r of results) {
    if (typeof r.total_cost_req === 'number') cost += r.total_cost_req;
    if (typeof r.input_tokens === 'number') inputTokens += r.input_tokens;
    if (typeof r.output_tokens === 'number') outputTokens += r.output_tokens;
    // Latest turn carrying a context window drives the fill gauge.
    if (r.context_window != null) {
      contextWindow = r.context_window;
      contextUsed = r.context_used ?? contextUsed;
    }
    if (r.model) model = r.model;
  }
  return { cost, inputTokens, outputTokens, contextUsed, contextWindow, model };
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

export function ChatPane({
  conversation,
  onSpawnChild,
  onStreamingChange,
  onWidgetPendingChange,
  hidden = false,
}: ChatPaneProps) {
  const { error } = useToasts();
  const convId = conversation.id;

  const [blocks, setBlocks] = useState<ChatBlock[]>([]);
  const [loading, setLoading] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [streaming, setStreaming] = useState(false);
  // Live events for the in-flight turn.
  const [liveEvents, setLiveEvents] = useState<ConvEvent[]>([]);
  const [livePrompt, setLivePrompt] = useState<string | null>(null);
  // Per-pane FIFO queue of widgets awaiting the user. Only the head (index 0)
  // is shown; the rest wait their turn and appear one by one as each resolves.
  // One widget at a time *per agent* — other panes queue independently.
  const [widgetQueue, setWidgetQueue] = useState<WidgetPayload[]>([]);
  // The widget currently shown (head of the queue), or null if none pending.
  const pendingWidget = widgetQueue[0] ?? null;

  const scrollRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<{ cancel: () => void } | null>(null);
  // Mutable mirrors so stop() can finalize the in-flight turn after cancel.
  const collectedRef = useRef<ConvEvent[]>([]);
  const promptRef = useRef('');
  const sawSpawnChildRef = useRef(false);

  const metrics = useMemo(() => {
    const all: ConvEvent[] = [];
    for (const b of blocks) if (b.kind === 'events') all.push(...b.events);
    all.push(...liveEvents);
    return summarizeMetrics(all);
  }, [blocks, liveEvents]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setBlocks([]);
    setLiveEvents([]);
    setLivePrompt(null);
    setWidgetQueue([]);
    getConversation(convId)
      .then((detail: ConversationDetail) => {
        if (cancelled) return;
        const next: ChatBlock[] = [];
        detail.turns.forEach((t, i) => {
          const p = typeof t.turn.prompt === 'string' ? t.turn.prompt : '';
          if (p)
            next.push({ kind: 'user', key: `${t.turn.id ?? i}-p`, text: p });
          next.push({
            kind: 'events',
            key: `${t.turn.id ?? i}-e`,
            events: t.events,
          });
        });
        setBlocks(next);
      })
      .catch((e: Error) => {
        if (!cancelled) error(`Failed to load conversation: ${e.message}`);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
      streamRef.current?.cancel();
      streamRef.current = null;
    };
  }, [convId, error]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [blocks, liveEvents]);

  // Report streaming state up (for tab status) and clear it on unmount.
  useEffect(() => {
    onStreamingChange?.(streaming);
  }, [streaming, onStreamingChange]);
  useEffect(() => {
    return () => onStreamingChange?.(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Report "needs you" state up (any pending widget) and clear it on unmount.
  useEffect(() => {
    onWidgetPendingChange?.(widgetQueue.length > 0);
  }, [widgetQueue.length, onWidgetPendingChange]);
  useEffect(() => {
    return () => onWidgetPendingChange?.(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc cancels the in-flight turn from anywhere while streaming. Only the
  // visible pane listens, so a hidden (backgrounded) streaming pane isn't
  // stopped by an Esc meant for the pane the user is looking at.
  useEffect(() => {
    if (!streaming || hidden) return;
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        stop();
      }
    };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming, hidden]);

  const send = () => {
    const text = prompt.trim();
    if (!text || streaming) return;
    setPrompt('');
    setLivePrompt(text);
    setLiveEvents([]);
    setWidgetQueue([]);
    setStreaming(true);

    collectedRef.current = [];
    promptRef.current = text;
    sawSpawnChildRef.current = false;

    streamRef.current = streamTurn(
      convId,
      text,
      (ev) => {
        collectedRef.current.push(ev);
        setLiveEvents((prev) => [...prev, ev]);
        // A tool is asking for input: queue its widget (shown one at a time).
        if (ev.type === 'widget') {
          // Enqueue; shows immediately if the queue was empty, otherwise it
          // waits behind the widgets already pending in this pane.
          setWidgetQueue((q) => [...q, ev.payload]);
        } else if (ev.type === 'widget_response') {
          // Resolved (answered/cancelled) — drop it; the next queued widget
          // (if any) becomes the head and is shown.
          setWidgetQueue((q) =>
            q.filter((w) => w.instance_id !== ev.payload.instance_id),
          );
        }
        // Detect a spawn_child tool_result to refresh children.
        if (
          ev.type === 'tool_result' &&
          collectedRef.current.some(
            (e) =>
              e.type === 'tool_use' &&
              e.payload.name === 'spawn_child' &&
              e.payload.id === ev.payload.tool_use_id,
          )
        ) {
          sawSpawnChildRef.current = true;
        }
      },
      (err) => {
        error(`Turn error: ${err.message}`);
        finishTurn(promptRef.current, collectedRef.current);
        if (sawSpawnChildRef.current) onSpawnChild();
      },
      () => {
        finishTurn(promptRef.current, collectedRef.current);
        if (sawSpawnChildRef.current) onSpawnChild();
      },
    );
  };

  // Cancel the in-flight stream and commit whatever was collected. The abort
  // suppresses onError/onDone, so finalize here explicitly.
  const stop = () => {
    if (!streaming) return;
    streamRef.current?.cancel();
    streamRef.current = null;
    finishTurn(promptRef.current, collectedRef.current);
    if (sawSpawnChildRef.current) onSpawnChild();
  };

  const finishTurn = (userText: string, events: ConvEvent[]) => {
    setStreaming(false);
    streamRef.current = null;
    setLivePrompt(null);
    setLiveEvents([]);
    setWidgetQueue([]);
    setBlocks((prev) => [
      ...prev,
      { kind: 'user', key: `live-${Date.now()}-p`, text: userText },
      { kind: 'events', key: `live-${Date.now()}-e`, events },
    ]);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // Answer the current (head) widget: POST the value; the awaiting tool unblocks
  // and the turn continues on the same SSE stream (which emits widget_response).
  // Dequeue the head so the next queued widget (if any) shows immediately.
  const answerWidget = (value: Record<string, unknown>) => {
    const w = pendingWidget;
    if (!w) return;
    setWidgetQueue((q) => q.filter((x) => x.instance_id !== w.instance_id));
    respondWidget(convId, w.instance_id, value).catch((e: Error) =>
      error(`Failed to respond: ${e.message}`),
    );
  };

  const WidgetComponent = pendingWidget
    ? resolveWidget(pendingWidget.widget_id)
    : undefined;

  return (
    <div className="main" style={hidden ? { display: 'none' } : undefined}>
      <div className="chat" ref={scrollRef}>
        {loading && <div className="empty">Loading…</div>}
        {!loading && blocks.length === 0 && !livePrompt && (
          <div className="empty">
            No messages yet. Send a prompt to start this{' '}
            {conversation.role === 'parent' ? 'project' : 'child'}.
          </div>
        )}
        {blocks.map((b) =>
          b.kind === 'user' ? (
            <div className="msg-user" key={b.key}>
              {b.text}
            </div>
          ) : (
            <div key={b.key} style={{ display: 'contents' }}>
              {renderEvents(b.events)}
            </div>
          ),
        )}
        {livePrompt && <div className="msg-user">{livePrompt}</div>}
        {liveEvents.length > 0 && (
          <div style={{ display: 'contents' }}>{renderEvents(liveEvents)}</div>
        )}
      </div>
      <div className="composer-wrap">
        {pendingWidget && (
          <div className="widget-overlay">
            {WidgetComponent ? (
              <WidgetComponent
                key={pendingWidget.instance_id}
                args={pendingWidget.args}
                onRespond={answerWidget}
              />
            ) : (
              <div className="widget widget--unknown">
                Unknown widget “{pendingWidget.widget_id}”. Press Esc to cancel.
              </div>
            )}
            {widgetQueue.length > 1 && (
              <div className="widget-queue-hint">
                +{widgetQueue.length - 1} more waiting
              </div>
            )}
          </div>
        )}
        {metrics && (
          <div className="metrics-bar">
            {metrics.contextWindow != null && metrics.contextUsed != null && (
              <span
                className="metric"
                title={`Context: ${metrics.contextUsed.toLocaleString()} / ${metrics.contextWindow.toLocaleString()} tokens`}
              >
                Context{' '}
                {Math.min(
                  100,
                  Math.round((metrics.contextUsed / metrics.contextWindow) * 100),
                )}
                % · {fmtTokens(metrics.contextUsed)}/{fmtTokens(metrics.contextWindow)}
              </span>
            )}
            {(metrics.inputTokens > 0 || metrics.outputTokens > 0) && (
              <span className="metric" title="Tokens processed (in / out)">
                ↑{fmtTokens(metrics.inputTokens)} ↓{fmtTokens(metrics.outputTokens)}
              </span>
            )}
            {metrics.cost > 0 && (
              <span className="metric" title="Copilot premium requests">
                {Number(metrics.cost.toFixed(2))} req
                {metrics.cost === 1 ? '' : 's'}
              </span>
            )}
            {metrics.model && (
              <span className="metric dim" title="Model">
                {metrics.model}
              </span>
            )}
          </div>
        )}
        <div className="composer">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Send a message (Enter to send, Shift+Enter for newline)"
            disabled={streaming}
          />
          {streaming ? (
            <button
              className="btn danger"
              onClick={stop}
              title="Stop (Esc)"
            >
              Stop
            </button>
          ) : (
            <button
              className="btn primary"
              onClick={send}
              disabled={!prompt.trim()}
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
