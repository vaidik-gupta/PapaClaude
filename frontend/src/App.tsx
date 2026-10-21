import { useCallback, useEffect, useState } from 'react';
import { clearCredentials, getCredentials } from './api/auth';
import { deleteConversation, listChildren, listProjects } from './api/client';
import type { Conversation } from './api/types';
import { AddChildDialog } from './components/AddChildDialog';
import { ChatPane } from './components/ChatPane';
import { Login } from './components/Login';
import { ManifestLibrary } from './components/ManifestLibrary';
import { NewProjectDialog } from './components/NewProjectDialog';
import { PersonaPanel } from './components/PersonaPanel';
import { ResourcesPane } from './components/ResourcesPane';
import { useToasts } from './state/toasts';

function tabLabel(c: Conversation): string {
  return c.title || (c.role === 'parent' ? 'Project' : 'Child') + ` ${c.id.slice(0, 6)}`;
}

export function App() {
  const { error, notify } = useToasts();
  const [authed, setAuthed] = useState(() => getCredentials() != null);

  const [projects, setProjects] = useState<Conversation[]>([]);
  const [selectedPapaId, setSelectedPapaId] = useState<string | null>(null);
  const [children, setChildren] = useState<Conversation[]>([]);
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);

  const [showNewProject, setShowNewProject] = useState(false);
  const [showAddChild, setShowAddChild] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [view, setView] = useState<'chat' | 'resources'>('chat');

  const loadProjects = useCallback(
    async (selectId?: string) => {
      try {
        const ps = await listProjects();
        setProjects(ps);
        if (selectId) {
          setSelectedPapaId(selectId);
          setSelectedConvId(selectId);
        } else if (!selectedPapaId && ps.length > 0) {
          setSelectedPapaId(ps[0].id);
          setSelectedConvId(ps[0].id);
        }
      } catch (e) {
        error(`Failed to load projects: ${(e as Error).message}`);
      }
    },
    [error, selectedPapaId],
  );

  const loadChildren = useCallback(
    async (papaId: string) => {
      try {
        const cs = await listChildren(papaId);
        setChildren(cs);
      } catch (e) {
        error(`Failed to load children: ${(e as Error).message}`);
      }
    },
    [error],
  );

  useEffect(() => {
    if (authed) loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  useEffect(() => {
    if (selectedPapaId) loadChildren(selectedPapaId);
    else setChildren([]);
  }, [selectedPapaId, loadChildren]);

  if (!authed) {
    return <Login onLoggedIn={() => setAuthed(true)} />;
  }

  const allConvs: Conversation[] = [
    ...projects.filter((p) => p.id === selectedPapaId),
    ...children,
  ];
  const selectedConv =
    allConvs.find((c) => c.id === selectedConvId) ??
    projects.find((p) => p.id === selectedConvId) ??
    null;

  const creds = getCredentials();

  const onConversationUpdated = (updated: Conversation) => {
    setProjects((ps) => ps.map((p) => (p.id === updated.id ? updated : p)));
    setChildren((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
  };

  const handleDelete = async (conv: Conversation) => {
    const isPapa = conv.role === 'parent';
    const label = tabLabel(conv);
    const message = isPapa
      ? `Delete project "${label}" and all of its children? This cannot be undone.`
      : `Delete child "${label}"? This cannot be undone.`;
    if (!window.confirm(message)) return;
    try {
      await deleteConversation(conv.id);
      notify(`Deleted ${label}.`);
      if (isPapa) {
        const remaining = projects.filter((p) => p.id !== conv.id);
        setProjects(remaining);
        if (selectedPapaId === conv.id) {
          const next = remaining[0]?.id ?? null;
          setSelectedPapaId(next);
          setSelectedConvId(next);
        }
      } else {
        setChildren((cs) => cs.filter((c) => c.id !== conv.id));
        if (selectedConvId === conv.id) {
          setSelectedConvId(selectedPapaId);
        }
      }
    } catch (e) {
      error(`Delete failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="app">
      <div className="topbar">
        <span className="brand">PapaClaude</span>
        <nav className="nav">
          <button
            className={view === 'chat' ? 'navbtn active' : 'navbtn'}
            onClick={() => setView('chat')}
          >
            Chat
          </button>
          <button
            className={view === 'resources' ? 'navbtn active' : 'navbtn'}
            onClick={() => setView('resources')}
          >
            Resources
          </button>
        </nav>
        <div className="spacer" />
        <button className="btn small" onClick={() => setShowLibrary(true)}>
          Manifest Library
        </button>
        <span className="user">{creds?.userName}</span>
        <button
          className="btn small"
          onClick={() => {
            clearCredentials();
            setAuthed(false);
          }}
        >
          Sign out
        </button>
      </div>

      {/* Top-level tabs: Papas / projects */}
      {view === 'chat' && (
      <>
      <div className="tabrow">
        {projects.map((p) => (
          <button
            key={p.id}
            className={
              p.id === selectedPapaId ? 'tab active' : 'tab'
            }
            onClick={() => {
              setSelectedPapaId(p.id);
              setSelectedConvId(p.id);
            }}
          >
            {tabLabel(p)}
            <span
              className="tab-close"
              role="button"
              aria-label={`Delete ${tabLabel(p)}`}
              title="Delete project"
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(p);
              }}
            >
              ×
            </span>
          </button>
        ))}
        <button className="btn small" onClick={() => setShowNewProject(true)}>
          + New Project
        </button>
      </div>

      {/* Second-level tabs: Papa + its children */}
      {selectedPapaId && (
        <div className="tabrow sub">
          {projects
            .filter((p) => p.id === selectedPapaId)
            .map((p) => (
              <button
                key={p.id}
                className={p.id === selectedConvId ? 'tab active' : 'tab'}
                onClick={() => setSelectedConvId(p.id)}
              >
                {tabLabel(p)}
                <span className="role-badge">papa</span>
              </button>
            ))}
          {children.map((c) => (
            <button
              key={c.id}
              className={c.id === selectedConvId ? 'tab active' : 'tab'}
              onClick={() => setSelectedConvId(c.id)}
            >
              {tabLabel(c)}
              <span className="role-badge">child</span>
              <span
                className="tab-close"
                role="button"
                aria-label={`Delete ${tabLabel(c)}`}
                title="Delete child"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(c);
                }}
              >
                ×
              </span>
            </button>
          ))}
          <button className="btn small" onClick={() => setShowAddChild(true)}>
            + Add Child
          </button>
        </div>
      )}

      <div className="body">
        {selectedConv ? (
          <>
            <ChatPane
              key={selectedConv.id}
              conversation={selectedConv}
              onSpawnChild={() => {
                if (selectedPapaId) loadChildren(selectedPapaId);
              }}
            />
            <PersonaPanel
              key={`persona-${selectedConv.id}`}
              conversation={selectedConv}
              onUpdated={onConversationUpdated}
            />
          </>
        ) : (
          <div className="empty">
            {projects.length === 0
              ? 'No projects yet. Create one with "+ New Project".'
              : 'Select a conversation.'}
          </div>
        )}
      </div>
      </>
      )}

      {view === 'resources' && <ResourcesPane />}

      {showNewProject && (
        <NewProjectDialog
          onClose={() => setShowNewProject(false)}
          onCreated={(c) => {
            setShowNewProject(false);
            loadProjects(c.id);
          }}
        />
      )}
      {showAddChild && selectedPapaId && (
        <AddChildDialog
          papaId={selectedPapaId}
          onClose={() => setShowAddChild(false)}
          onCreated={(c) => {
            setShowAddChild(false);
            if (selectedPapaId) loadChildren(selectedPapaId);
            setSelectedConvId(c.id);
          }}
        />
      )}
      {showLibrary && (
        <ManifestLibrary onClose={() => setShowLibrary(false)} />
      )}
    </div>
  );
}
