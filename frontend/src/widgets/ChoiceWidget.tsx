import { useEffect, useRef, useState } from 'react';

import type { WidgetProps } from './registry';

// A choice request raised by the built-in `ask_user` tool (with choices): the
// agent needs the user to pick one of N options. The chosen string is returned
// as the answer. Esc/Stop cancels the whole turn.
//
// Fully keyboard-operable: grabs focus on mount; ↑/↓/←/→ move the selection,
// Enter confirms. First option is selected by default.
export function ChoiceWidget({ args, onRespond }: WidgetProps) {
  const question =
    typeof args.question === 'string' ? args.question : 'Choose an option';
  const options = Array.isArray(args.options)
    ? (args.options as unknown[]).map((o) => String(o))
    : [];

  const [selected, setSelected] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  // Grab focus on mount so keys work without a click.
  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  const count = options.length;
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (count === 0) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((i) => (i - 1 + count) % count);
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((i) => (i + 1) % count);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      onRespond({ value: options[selected] });
    }
    // Esc intentionally bubbles: ChatPane cancels the whole turn.
  };

  return (
    <div
      ref={rootRef}
      className="widget widget--choice"
      role="group"
      aria-label="Choose an option"
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="widget__title">{question}</div>
      <div className="widget__choices">
        {options.map((opt, i) => (
          <button
            key={`${i}-${opt}`}
            type="button"
            className={`btn ${i === selected ? 'is-selected' : ''}`}
            aria-pressed={i === selected}
            onMouseEnter={() => setSelected(i)}
            onClick={() => onRespond({ value: opt })}
          >
            {opt}
          </button>
        ))}
      </div>
      <p className="widget__hint">
        ↑/↓ to choose · Enter to confirm · Esc to cancel
      </p>
    </div>
  );
}
