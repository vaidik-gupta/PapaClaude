import { useEffect, useRef, useState } from 'react';
import { getConversation, streamTurn } from '../api/client';
import type {
  Conversation,
  ConversationDetail,
  ConvEvent,
} from '../api/types';
import { useToasts } from '../state/toasts';
import { renderEvents, type ChatBlock } from './ChatEvents';

interface ChatPaneProps {
  conversation: Conversation;
  // Called when a spawn_child tool_result is observed on this stream, so the
  // parent can refetch children and reveal the new tab.
  onSpawnChild: () => void;
}

export function ChatPane({ conversation, onSpawnChild }: ChatPaneProps) {
  const { error } = useToasts();
  const convId = conversation.id;

  const [blocks, setBlocks] = useState<ChatBlock[]>([]);
  const [loading, setLoading] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [streaming, setStreaming] = useState(false);
  // Live events for the in-flight turn.
  const [liveEvents, setLiveEvents] = useState<ConvEvent[]>([]);
  const [livePrompt, setLivePrompt] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<{ cancel: () => void } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setBlocks([]);
    setLiveEvents([]);
    setLivePrompt(null);
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

  const send = () => {
    const text = prompt.trim();
    if (!text || streaming) return;
    setPrompt('');
    setLivePrompt(text);
    setLiveEvents([]);
    setStreaming(true);

    const collected: ConvEvent[] = [];
    let sawSpawnChild = false;

    streamRef.current = streamTurn(
      convId,
      text,
      (ev) => {
        collected.push(ev);
        setLiveEvents((prev) => [...prev, ev]);
        // Detect a spawn_child tool_result to refresh children.
        if (
          ev.type === 'tool_result' &&
          collected.some(
            (e) =>
              e.type === 'tool_use' &&
              e.payload.name === 'spawn_child' &&
              e.payload.id === ev.payload.tool_use_id,
          )
        ) {
          sawSpawnChild = true;
        }
      },
      (err) => {
        error(`Turn error: ${err.message}`);
        finishTurn(text, collected);
        if (sawSpawnChild) onSpawnChild();
      },
      () => {
        finishTurn(text, collected);
        if (sawSpawnChild) onSpawnChild();
      },
    );
  };

  const finishTurn = (userText: string, events: ConvEvent[]) => {
    setStreaming(false);
    streamRef.current = null;
    setLivePrompt(null);
    setLiveEvents([]);
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

  return (
    <div className="main">
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
      <div className="composer">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Send a message (Enter to send, Shift+Enter for newline)"
          disabled={streaming}
        />
        <button
          className="btn primary"
          onClick={send}
          disabled={streaming || !prompt.trim()}
        >
          {streaming ? 'Streaming…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
