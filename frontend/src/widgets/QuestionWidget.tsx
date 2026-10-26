import { useEffect, useRef, useState } from 'react';

import type { WidgetProps } from './registry';

// A free-text question raised by the built-in `ask_user` tool (no choices): the
// agent needs a typed answer only the user can provide. The entered string is
// returned as the response value. Esc/Stop cancels the whole turn.
//
// The input grabs focus on mount; Enter submits (empty answers are blocked so
// the tool always gets a value). Esc bubbles so ChatPane can cancel the turn.
export function QuestionWidget({ args, onRespond }: WidgetProps) {
  const question =
    typeof args.question === 'string' ? args.question : 'Please answer';

  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    onRespond({ value });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
    // Esc intentionally bubbles: ChatPane cancels the whole turn.
  };

  return (
    <div
      className="widget widget--question"
      role="group"
      aria-label="Answer a question"
    >
      <div className="widget__title">{question}</div>
      <input
        ref={inputRef}
        type="text"
        className="widget__input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Your answer"
      />
      <div className="widget__actions">
        <button
          type="button"
          className="btn"
          disabled={!text.trim()}
          onClick={submit}
        >
          Submit
        </button>
      </div>
      <p className="widget__hint">Enter to submit · Esc to cancel</p>
    </div>
  );
}
