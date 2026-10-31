import { useEffect, useMemo, useRef, useState } from 'react';

import type { WidgetProps } from './registry';

// A write permission request raised by a gated write tool (`edit`/`create`).
// Unlike the compact permission card, this renders the *proposed change* as a
// unified diff so the user can review it before approving. The user must Allow
// or Deny before the write proceeds; Esc/Stop cancels the whole turn.
//
// Fully keyboard-operable: grabs focus on mount; ←/→/↑/↓ move the selection,
// Enter confirms. Deny is selected by default (safer for a mutating action).
// When the backend attaches a `remember` descriptor, a third option offers a
// clearly-labelled persistent grant (e.g. "Always allow writes in <git root>").

// Classify a unified-diff line for syntax coloring.
function lineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'diff-line diff-line--meta';
  if (line.startsWith('@@')) return 'diff-line diff-line--hunk';
  if (line.startsWith('+')) return 'diff-line diff-line--add';
  if (line.startsWith('-')) return 'diff-line diff-line--del';
  return 'diff-line';
}

export function DiffWidget({ args, onRespond }: WidgetProps) {
  const tool = typeof args.tool === 'string' ? args.tool : 'write';
  const fileName = typeof args.file_name === 'string' ? args.file_name : null;
  const summary = typeof args.summary === 'string' ? args.summary : null;
  const diff = typeof args.diff === 'string' ? args.diff : '';
  const remember = args.remember as { label?: string } | undefined;
  const rememberLabel =
    typeof remember?.label === 'string' ? remember.label : null;

  const lines = useMemo(() => diff.split('\n'), [diff]);

  const options = useMemo(
    () => [
      { label: 'Deny', value: { granted: false }, variant: '' },
      {
        label: rememberLabel ? 'Allow once' : 'Allow',
        value: { granted: true, scope: 'once' },
        variant: 'danger',
      },
      ...(rememberLabel
        ? [
            {
              label: rememberLabel,
              value: { granted: true, scope: 'remember' },
              variant: 'danger',
            },
          ]
        : []),
    ],
    [rememberLabel],
  );

  const [selected, setSelected] = useState(0); // default: Deny
  const rootRef = useRef<HTMLDivElement>(null);

  // Grab focus on mount so keys work without a click.
  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((i) => (i + 1) % options.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      onRespond({ ...options[selected].value });
    }
    // Esc intentionally bubbles: ChatPane cancels the whole turn.
  };

  return (
    <div
      ref={rootRef}
      className="widget widget--diff"
      role="group"
      aria-label={`Write permission required for ${fileName ?? tool}`}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="widget__title">
        Write change: {fileName ? <code>{fileName}</code> : <code>{tool}</code>}
      </div>
      {summary && <p className="widget__summary">{summary}</p>}
      {diff ? (
        <pre className="widget__diff" aria-label="Proposed change">
          {lines.map((line, i) => (
            <span key={i} className={lineClass(line)}>
              {line + '\n'}
            </span>
          ))}
        </pre>
      ) : (
        <p className="widget__summary">(No diff provided.)</p>
      )}
      <div className="widget__actions">
        {options.map((opt, i) => (
          <button
            key={opt.label}
            type="button"
            className={`btn ${opt.variant} ${i === selected ? 'is-selected' : ''}`}
            aria-pressed={i === selected}
            onMouseEnter={() => setSelected(i)}
            onClick={() => onRespond({ ...opt.value })}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <p className="widget__hint">
        ←/→ to choose · Enter to confirm · Esc to cancel
      </p>
    </div>
  );
}
