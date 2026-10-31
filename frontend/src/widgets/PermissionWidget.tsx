import { useEffect, useMemo, useRef, useState } from 'react';

import type { WidgetProps } from './registry';

// A permission request raised by a gated tool (e.g. `delete`) or a built-in
// read/shell/url tool. The user must Allow or Deny before the tool proceeds;
// Esc/Stop cancels the whole turn. When the backend attaches a `remember`
// descriptor, a third option offers a clearly-labelled persistent grant (e.g.
// "Approve calls to example.com this session").
//
// Fully keyboard-operable: the widget grabs focus on mount; ←/→/↑/↓ move the
// selection, Enter confirms it. Deny is selected by default (safer).

export function PermissionWidget({ args, onRespond }: WidgetProps) {
  const tool = typeof args.tool === 'string' ? args.tool : 'tool';
  const summary = typeof args.summary === 'string' ? args.summary : null;
  const toolArgs = args.args as Record<string, unknown> | undefined;
  const remember = args.remember as { label?: string } | undefined;
  const rememberLabel =
    typeof remember?.label === 'string' ? remember.label : null;

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
      className="widget widget--permission"
      role="group"
      aria-label={`Permission required for ${tool}`}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="widget__title">
        Permission required: <code>{tool}</code>
      </div>
      {summary && <p className="widget__summary">{summary}</p>}
      {toolArgs && (
        <pre className="widget__args">{JSON.stringify(toolArgs, null, 2)}</pre>
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
