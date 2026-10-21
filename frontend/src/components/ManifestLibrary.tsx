import { useEffect, useState } from 'react';
import {
  createManifest,
  deleteManifest,
  listManifests,
  updateManifest,
} from '../api/client';
import {
  CONTENT_TOOLS,
  type ContentTool,
  type Manifest,
  type Role,
} from '../api/types';
import { useToasts } from '../state/toasts';
import { Modal } from './Modal';

const blankManifest = (): Manifest => ({
  name: '',
  role: 'parent',
  description: '',
  system_prompt: '',
  model: null,
  allowed_tools: [],
  max_turns: null,
  permission_mode: 'auto',
});

interface Props {
  onClose: () => void;
}

export function ManifestLibrary({ onClose }: Props) {
  const { notify, error } = useToasts();
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Manifest | null>(null);
  const [isNew, setIsNew] = useState(false);

  const refresh = () => {
    setLoading(true);
    listManifests()
      .then(setManifests)
      .catch((e: Error) => error(`Failed to load manifests: ${e.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startNew = () => {
    setEditing(blankManifest());
    setIsNew(true);
  };
  const startEdit = (m: Manifest) => {
    setEditing({ ...m });
    setIsNew(false);
  };

  const remove = async (name: string) => {
    try {
      await deleteManifest(name);
      notify(`Deleted ${name}.`);
      refresh();
    } catch (e) {
      error(`Delete failed: ${(e as Error).message}`);
    }
  };

  if (editing) {
    return (
      <ManifestEditor
        manifest={editing}
        isNew={isNew}
        onCancel={() => setEditing(null)}
        onClose={onClose}
        onSaved={() => {
          setEditing(null);
          refresh();
        }}
      />
    );
  }

  return (
    <Modal
      title="Manifest Library"
      wide
      onClose={onClose}
      footer={
        <button className="btn primary" onClick={startNew}>
          New manifest
        </button>
      }
    >
      {loading && <div className="empty">Loading…</div>}
      {!loading && manifests.length === 0 && (
        <div className="empty">No manifests.</div>
      )}
      <div className="manifest-list">
        {manifests.map((m) => (
          <div className="manifest-item" key={m.name}>
            <span className="name">{m.name}</span>
            <span className="role-badge">{m.role}</span>
            <span className="desc">{m.description}</span>
            <div className="row-actions">
              <button className="btn small" onClick={() => startEdit(m)}>
                Edit
              </button>
              <button
                className="btn small danger"
                onClick={() => remove(m.name)}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}

interface EditorProps {
  manifest: Manifest;
  isNew: boolean;
  onCancel: () => void;
  onClose: () => void;
  onSaved: () => void;
}

function ManifestEditor({
  manifest,
  isNew,
  onCancel,
  onSaved,
}: EditorProps) {
  const { notify, error } = useToasts();
  const [m, setM] = useState<Manifest>(manifest);
  const [maxTurns, setMaxTurns] = useState(
    manifest.max_turns == null ? '' : String(manifest.max_turns),
  );
  const [model, setModel] = useState(manifest.model ?? '');
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof Manifest>(k: K, v: Manifest[K]) =>
    setM((prev) => ({ ...prev, [k]: v }));

  const toggleTool = (t: ContentTool) =>
    setM((prev) => ({
      ...prev,
      allowed_tools: prev.allowed_tools.includes(t)
        ? prev.allowed_tools.filter((x) => x !== t)
        : [...prev.allowed_tools, t],
    }));

  const save = async () => {
    if (!m.name.trim()) {
      error('Name is required.');
      return;
    }
    const parsedTurns = maxTurns.trim() === '' ? null : Number(maxTurns);
    if (parsedTurns != null && Number.isNaN(parsedTurns)) {
      error('Max turns must be a number or empty.');
      return;
    }
    const payload: Manifest = {
      ...m,
      model: model.trim() === '' ? null : model.trim(),
      max_turns: parsedTurns,
    };
    setBusy(true);
    try {
      if (isNew) {
        await createManifest(payload);
        notify(`Created ${payload.name}.`);
      } else {
        await updateManifest(payload.name, payload);
        notify(`Updated ${payload.name}.`);
      }
      onSaved();
    } catch (e) {
      error(`Save failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={isNew ? 'New Manifest' : `Edit ${manifest.name}`}
      wide
      onClose={onCancel}
      footer={
        <>
          <button className="btn" onClick={onCancel}>
            Back
          </button>
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className="field">
        <label>Name (unique; == filename stem)</label>
        <input
          value={m.name}
          onChange={(e) => set('name', e.target.value)}
          disabled={!isNew}
        />
      </div>
      <div className="field">
        <label>Role</label>
        <select
          value={m.role}
          onChange={(e) => set('role', e.target.value as Role)}
          disabled={!isNew}
        >
          <option value="parent">parent</option>
          <option value="child">child</option>
        </select>
      </div>
      <div className="field">
        <label>Description</label>
        <input
          value={m.description}
          onChange={(e) => set('description', e.target.value)}
        />
      </div>
      <div className="field">
        <label>System prompt</label>
        <textarea
          value={m.system_prompt}
          onChange={(e) => set('system_prompt', e.target.value)}
          style={{ minHeight: 120 }}
        />
      </div>
      <div className="field">
        <label>Model (empty = server default)</label>
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="field">
        <label>Allowed tools</label>
        {CONTENT_TOOLS.map((t) => (
          <div className="checkbox-row" key={t}>
            <input
              type="checkbox"
              id={`m-tool-${t}`}
              checked={m.allowed_tools.includes(t)}
              onChange={() => toggleTool(t)}
            />
            <label htmlFor={`m-tool-${t}`}>{t}</label>
          </div>
        ))}
      </div>
      <div className="field">
        <label>Max turns (empty = null)</label>
        <input value={maxTurns} onChange={(e) => setMaxTurns(e.target.value)} />
      </div>
      <div className="field">
        <label>Permission mode</label>
        <input
          value={m.permission_mode}
          onChange={(e) => set('permission_mode', e.target.value)}
        />
      </div>
    </Modal>
  );
}
