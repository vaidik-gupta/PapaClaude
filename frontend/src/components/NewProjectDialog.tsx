import { useEffect, useState } from 'react';
import { createProject, listManifests } from '../api/client';
import type { Conversation, Manifest } from '../api/types';
import { useToasts } from '../state/toasts';
import { DirectoryPicker } from './DirectoryPicker';
import { Modal } from './Modal';

interface Props {
  onClose: () => void;
  onCreated: (c: Conversation) => void;
}

export function NewProjectDialog({ onClose, onCreated }: Props) {
  const { error } = useToasts();
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [manifestName, setManifestName] = useState('');
  const [title, setTitle] = useState('');
  const [directory, setDirectory] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listManifests('parent')
      .then((ms) => {
        setManifests(ms);
        const def = ms.find((m) => m.name === 'default-parent') ?? ms[0];
        if (def) setManifestName(def.name);
      })
      .catch((e: Error) => error(`Failed to load manifests: ${e.message}`));
  }, [error]);

  const create = async () => {
    if (!directory) return;
    setBusy(true);
    try {
      const conv = await createProject({
        manifest_name: manifestName || undefined,
        title: title.trim() || undefined,
        directory,
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
      title="New Project"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={create}
            disabled={busy || !manifestName || !directory}
          >
            {busy ? 'Creating…' : 'Create'}
          </button>
        </>
      }
    >
      <div className="field">
        <label>Parent manifest</label>
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
          placeholder="My project"
        />
      </div>
      <div className="field">
        <label>Working directory</label>
        <DirectoryPicker value={directory} onChange={setDirectory} />
      </div>
    </Modal>
  );
}
