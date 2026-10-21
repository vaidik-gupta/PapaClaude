import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';

interface Toast {
  id: number;
  message: string;
  kind: 'info' | 'error';
}

interface ToastCtx {
  notify: (message: string, kind?: 'info' | 'error') => void;
  error: (message: string) => void;
}

const Ctx = createContext<ToastCtx | null>(null);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, kind: 'info' | 'error' = 'info') => {
      const id = nextId++;
      setToasts((t) => [...t, { id, message, kind }]);
      window.setTimeout(() => remove(id), 5000);
    },
    [remove],
  );

  const error = useCallback((message: string) => notify(message, 'error'), [
    notify,
  ]);

  return (
    <Ctx.Provider value={{ notify, error }}>
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={t.kind === 'error' ? 'toast error' : 'toast'}
            onClick={() => remove(t.id)}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToasts(): ToastCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useToasts must be used within ToastProvider');
  return ctx;
}
