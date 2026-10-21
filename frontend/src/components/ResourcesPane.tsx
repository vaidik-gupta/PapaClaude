import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addResource,
  deleteResource,
  getResourceData,
  getResourceTree,
  reloadResourceTree,
  requestDB,
} from '../api/client';
import {
  DATA_KINDS,
  type ContentTreeDto,
  type ResourceEngine,
  type ResourceNode,
} from '../api/types';
import { useToasts } from '../state/toasts';
import { Modal } from './Modal';

// The layer at which each engine's nodes become data leaves (hold a payload).
const DATA_LAYER: Record<ResourceEngine, number> = {
  dynamodb: 3,
  s3: 3,
  mongodb: 4,
};

const isDataNode = (node: ResourceNode) => DATA_KINDS.includes(node.kind);

// Can this node hold children (i.e. is it a container below the data layer)?
const canHaveChildren = (node: ResourceNode) =>
  !isDataNode(node) && node.layer < DATA_LAYER[node.engine];

// Will a child added under this node be a data leaf?
const childIsData = (node: ResourceNode) =>
  node.layer + 1 === DATA_LAYER[node.engine];

interface AddTarget {
  node: ResourceNode;
  path: string[];
  asData: boolean;
  // When set, create a layer-1 instance via POST /resources/db instead.
  asDB: boolean;
}

export function ResourcesPane() {
  const { notify, error } = useToasts();
  const [tree, setTree] = useState<ContentTreeDto | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addTarget, setAddTarget] = useState<AddTarget | null>(null);
  const [viewer, setViewer] = useState<{ path: string[]; text: string } | null>(
    null,
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setTree(await getResourceTree());
    } catch (e) {
      error(`Failed to load resources: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [error]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const reload = async () => {
    setBusy(true);
    try {
      setTree(await reloadResourceTree());
      notify('Reloaded from storage.');
    } catch (e) {
      error(`Reload failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const viewData = async (path: string[]) => {
    try {
      const res = await getResourceData(path);
      setViewer({
        path,
        text:
          res.data == null
            ? '(no payload stored)'
            : JSON.stringify(res.data, null, 2),
      });
    } catch (e) {
      error(`Read failed: ${(e as Error).message}`);
    }
  };

  const remove = async (node: ResourceNode, path: string[]) => {
    const what = isDataNode(node) ? 'datum' : 'resource';
    if (
      !window.confirm(
        `Delete ${what} "${node.name}" and everything under it? This cannot be undone.`,
      )
    )
      return;
    try {
      await deleteResource(path);
      notify(`Deleted ${node.name}.`);
      refresh();
    } catch (e) {
      error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const submitAdd = async (name: string, json: Record<string, unknown>) => {
    if (!addTarget) return;
    const { node, path, asData, asDB } = addTarget;
    setBusy(true);
    try {
      if (asDB) {
        await requestDB({
          engine: node.engine,
          name,
          metadata: json,
        });
      } else {
        await addResource({
          parent_path: path,
          name,
          metadata: asData ? {} : json,
          data: asData ? json : null,
        });
      }
      notify(`Added ${name}.`);
      setExpanded((prev) => new Set(prev).add(path.join('/')));
      setAddTarget(null);
      refresh();
    } catch (e) {
      error(`Add failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const openAdd = (node: ResourceNode, path: string[]) => {
    const asDB = node.kind === 'engine';
    setAddTarget({
      node,
      path,
      asData: !asDB && childIsData(node),
      asDB,
    });
  };

  const renderNode = (node: ResourceNode, parentPath: string[]) => {
    const path = [...parentPath, node.name];
    const key = path.join('/');
    const hasChildren = node.children.length > 0;
    const open = expanded.has(key);
    const dataLeaf = isDataNode(node);
    const isEngine = node.kind === 'engine';

    return (
      <div className="res-node" key={key}>
        <div className="res-row" style={{ paddingLeft: node.layer * 16 }}>
          {hasChildren ? (
            <button
              className="res-caret"
              onClick={() => toggle(key)}
              aria-label={open ? 'Collapse' : 'Expand'}
            >
              {open ? '▾' : '▸'}
            </button>
          ) : (
            <span className="res-caret placeholder" />
          )}
          <span className="res-name">{node.name}</span>
          <span className="res-kind">{node.kind}</span>
          <div className="res-actions">
            {isEngine && (
              <button className="btn small" onClick={() => openAdd(node, path)}>
                + Request DB
              </button>
            )}
            {!isEngine && canHaveChildren(node) && (
              <button className="btn small" onClick={() => openAdd(node, path)}>
                + Add {childIsData(node) ? 'datum' : 'resource'}
              </button>
            )}
            {dataLeaf && (
              <button className="btn small" onClick={() => viewData(path)}>
                View
              </button>
            )}
            {!isEngine && (
              <button
                className="btn small danger"
                onClick={() => remove(node, path)}
              >
                Delete
              </button>
            )}
          </div>
        </div>
        {hasChildren && open && (
          <div className="res-children">
            {node.children.map((c) => renderNode(c, path))}
          </div>
        )}
      </div>
    );
  };

  const empty = useMemo(
    () =>
      tree != null &&
      tree.roots.every((r) => r.children.length === 0),
    [tree],
  );

  return (
    <div className="resources">
      <div className="resources-head">
        <h3>Resources</h3>
        <div className="spacer" />
        <button className="btn small" onClick={reload} disabled={busy}>
          Reload from storage
        </button>
      </div>
      <div className="resources-body">
        {loading && <div className="empty">Loading…</div>}
        {!loading && tree && (
          <>
            {empty && (
              <div className="hint" style={{ marginBottom: 12 }}>
                No resources yet. Use “+ Request DB” on an engine to start.
              </div>
            )}
            {tree.roots.map((root) => renderNode(root, []))}
          </>
        )}
      </div>

      {addTarget && (
        <AddResourceDialog
          target={addTarget}
          busy={busy}
          onClose={() => setAddTarget(null)}
          onSubmit={submitAdd}
        />
      )}
      {viewer && (
        <Modal
          title={`Data · ${viewer.path.join(' / ')}`}
          wide
          onClose={() => setViewer(null)}
        >
          <pre className="data-view">{viewer.text}</pre>
        </Modal>
      )}
    </div>
  );
}

interface AddDialogProps {
  target: AddTarget;
  busy: boolean;
  onClose: () => void;
  onSubmit: (name: string, json: Record<string, unknown>) => void;
}

function AddResourceDialog({ target, busy, onClose, onSubmit }: AddDialogProps) {
  const { error } = useToasts();
  const { node, asData, asDB } = target;
  const [name, setName] = useState('');
  const [json, setJson] = useState('');

  const jsonRequired = asData;
  const jsonLabel = asData
    ? 'Data payload (JSON object, required)'
    : 'Metadata (JSON object, optional)';

  const title = asDB
    ? `Request DB under ${node.name}`
    : asData
      ? `Add datum under ${node.name}`
      : `Add resource under ${node.name}`;

  const submit = () => {
    if (!name.trim()) {
      error('Name is required.');
      return;
    }
    let parsed: Record<string, unknown> = {};
    const text = json.trim();
    if (text === '') {
      if (jsonRequired) {
        error('A JSON data payload is required at the data level.');
        return;
      }
    } else {
      try {
        const value = JSON.parse(text);
        if (value == null || typeof value !== 'object' || Array.isArray(value)) {
          error('JSON must be an object.');
          return;
        }
        parsed = value as Record<string, unknown>;
      } catch (e) {
        error(`Invalid JSON: ${(e as Error).message}`);
        return;
      }
    }
    onSubmit(name.trim(), parsed);
  };

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Create'}
          </button>
        </>
      }
    >
      <div className="field">
        <label>Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="name"
          autoFocus
        />
      </div>
      <div className="field">
        <label>{jsonLabel}</label>
        <textarea
          value={json}
          onChange={(e) => setJson(e.target.value)}
          style={{ minHeight: 120, fontFamily: 'monospace' }}
          placeholder={asData ? '{\n  "field": "value"\n}' : '{}'}
        />
      </div>
    </Modal>
  );
}
