import { useEffect, useState } from 'react';
import { listDirs } from '../api/client';
import type { DirListing } from '../api/types';

interface Props {
  value: string | null;
  onChange: (path: string) => void;
}

/**
 * Browse server-side directories to choose an agent's working directory.
 * Starts at the user's home; the currently-open folder is the selected value.
 */
export function DirectoryPicker({ value, onChange }: Props) {
  const [listing, setListing] = useState<DirListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const browse = async (path?: string) => {
    setLoading(true);
    setErr(null);
    try {
      const l = await listDirs(path);
      setListing(l);
      onChange(l.path);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    browse(value ?? undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="dirpicker">
      <div className="dirpicker-path" title={value ?? ''}>
        {value ?? '…'}
      </div>
      {err && <div className="dirpicker-err">{err}</div>}
      <div className="dirpicker-list">
        {listing?.parent && (
          <button
            type="button"
            className="dirpicker-item up"
            onClick={() => browse(listing.parent!)}
            disabled={loading}
          >
            ↑ ..
          </button>
        )}
        {listing?.entries.length === 0 && (
          <div className="dirpicker-empty">No sub-folders</div>
        )}
        {listing?.entries.map((name) => (
          <button
            type="button"
            key={name}
            className="dirpicker-item"
            onClick={() => browse(`${listing.path}/${name}`)}
            disabled={loading}
          >
            📁 {name}
          </button>
        ))}
      </div>
    </div>
  );
}
