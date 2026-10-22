import { useEffect, useState } from 'react';
import { updatePersona, type PersonaPatch } from '../api/client';
import {
  CONTENT_TOOLS,
  type Conversation,
  type ContentTool,
} from '../api/types';
import { useToasts } from '../state/toasts';

interface PersonaPanelProps {
  conversation: Conversation;
  onUpdated: (c: Conversation) => void;
}

export function PersonaPanel({ conversation, onUpdated }: PersonaPanelProps) {
  const { notify, error } = useToasts();
  const p = conversation.persona;

  const [systemPrompt, setSystemPrompt] = useState(p.system_prompt);
  const [model, setModel] = useState(p.model ?? '');
  const [description, setDescription] = useState(p.description);
  const [permissionMode, setPermissionMode] = useState(p.permission_mode);
  const [maxTurns, setMaxTurns] = useState(
    p.max_turns == null ? '' : String(p.max_turns),
  );
  const [tools, setTools] = useState<ContentTool[]>(p.allowed_tools);
  const [saving, setSaving] = useState(false);

  // Reset local form when the selected conversation (or its persona) changes.
  useEffect(() => {
    setSystemPrompt(p.system_prompt);
    setModel(p.model ?? '');
    setDescription(p.description);
    setPermissionMode(p.permission_mode);
    setMaxTurns(p.max_turns == null ? '' : String(p.max_turns));
    setTools(p.allowed_tools);
  }, [
    conversation.id,
    p.system_prompt,
    p.model,
    p.description,
    p.permission_mode,
    p.max_turns,
    p.allowed_tools,
  ]);

  const toggleTool = (t: ContentTool) => {
    setTools((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  };

  const save = async () => {
    const patch: PersonaPatch = {
      system_prompt: systemPrompt,
      model: model.trim() === '' ? null : model.trim(),
      description,
      permission_mode: permissionMode,
      allowed_tools: tools,
      max_turns: maxTurns.trim() === '' ? null : Number(maxTurns),
    };
    if (patch.max_turns != null && Number.isNaN(patch.max_turns)) {
      error('Max turns must be a number or empty.');
      return;
    }
    setSaving(true);
    try {
      const updated = await updatePersona(conversation.id, patch);
      onUpdated(updated);
      notify('Persona saved (applies from next turn).');
    } catch (e) {
      error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="side">
      <div className="side-head">
        <h3>Persona</h3>
      </div>
      <div className="side-body">
        <div className="meta-line">
          <b>Manifest:</b> {conversation.manifest_name}
        </div>
        <div className="meta-line">
          <b>Role:</b> {p.role}
        </div>
        <div className="meta-line">
          <b>Directory:</b>{' '}
          {conversation.directory ? (
            <code>{conversation.directory}</code>
          ) : (
            <span className="text-dim">not set</span>
          )}
        </div>
        {conversation.task && (
          <div className="meta-line">
            <b>Task:</b> {conversation.task}
          </div>
        )}

        <div className="field" style={{ marginTop: 12 }}>
          <label>Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        <div className="field">
          <label>System prompt</label>
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            style={{ minHeight: 120 }}
          />
        </div>

        <div className="field">
          <label>Model (empty = server default)</label>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="claude-sonnet-5"
          />
        </div>

        <div className="field">
          <label>Allowed tools</label>
          {CONTENT_TOOLS.map((t) => (
            <div className="checkbox-row" key={t}>
              <input
                type="checkbox"
                id={`tool-${t}`}
                checked={tools.includes(t)}
                onChange={() => toggleTool(t)}
              />
              <label htmlFor={`tool-${t}`}>{t}</label>
            </div>
          ))}
          {p.role === 'parent' && (
            <div className="hint">spawn_child is auto-added for parents.</div>
          )}
        </div>

        <div className="field">
          <label>Max turns (empty = unlimited)</label>
          <input
            value={maxTurns}
            onChange={(e) => setMaxTurns(e.target.value)}
            placeholder="unlimited"
          />
        </div>

        <div className="field">
          <label>Permission mode</label>
          <input
            value={permissionMode}
            onChange={(e) => setPermissionMode(e.target.value)}
          />
        </div>

        <button
          className="btn primary"
          style={{ width: '100%' }}
          onClick={save}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save persona'}
        </button>
        <div className="hint">Changes apply from the next turn.</div>
      </div>
    </div>
  );
}
