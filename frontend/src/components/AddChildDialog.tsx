import { useEffect, useState } from 'react';
import { createChild, listManifests } from '../api/client';
import type { Conversation, Manifest } from '../api/types';
import { useToasts } from '../state/toasts';
import { Modal } from './Modal';

interface Props {
  papaId: string;
  onClose: () => void;
  onCreated: (c: Conversation) => void;
}

export function AddChildDialog({ papaId, onClose, onCreated }: Props) {
  const { error } = useToasts();
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [manifestName, setManifestName] = useState('');
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listManifests('child')
      .then((ms) => {
        setManifests(ms);
        const def = ms.find((m) => m.name === 'default-child') ?? ms[0];
        if (def) setManifestName(def.name);
      })
      .catch((e: Error) => error(`Failed to load manifests: ${e.message}`));
  }, [error]);

  const create = async () => {
    if (!manifestName) return;
    setBusy(true);
    try {
      const conv = await createChild(papaId, {
        manifest_name: manifestName,
        title: title.trim() || undefined,
      });
      onCreated(conv);
    } catch (e) {
      error(`Create failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Add Child"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={create}
            disabled={busy || !manifestName}
          >
            {busy ? 'Creating…' : 'Create'}
          </button>
        </>
      }
    >
      <div className="field">
        <label>Child manifest</label>
        <select
          value={manifestName}
          onChange={(e) => setManifestName(e.target.value)}
        >
          {manifests.length === 0 && <option value="">No manifests</option>}
          {manifests.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Title (optional)</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Child task"
        />
      </div>
      <div className="hint">A UI-created child starts with no context.</div>
    </Modal>
  );
}
