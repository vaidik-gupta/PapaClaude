import type { WidgetResponsePayload } from '../api/types';
import { resolveWidgetSummary } from './registry';

interface Props {
  widgetId: string;
  args: Record<string, unknown>;
  response: WidgetResponsePayload | null;
}

// Human-readable outcome label for a resolved widget. `permission` and `diff`
// widgets carry a `granted` boolean (and a `scope`); everything else falls back
// to the status / raw value.
function outcomeLabel(
  widgetId: string,
  response: WidgetResponsePayload | null,
): { text: string; tone: 'ok' | 'deny' | 'muted' } {
  if (!response || response.status === 'cancelled') {
    return { text: 'Cancelled', tone: 'muted' };
  }
  const value = response.value ?? {};
  if (widgetId === 'permission' || widgetId === 'diff') {
    if (!value.granted) return { text: 'Denied', tone: 'deny' };
    return value.scope === 'remember'
      ? { text: 'Allowed (remembered)', tone: 'ok' }
      : { text: 'Allowed', tone: 'ok' };
  }
  if (typeof value.value === 'string') {
    return { text: value.value, tone: 'ok' };
  }
  return { text: 'Answered', tone: 'ok' };
}

// Generic read-only card for a resolved widget: id + outcome badge. Used for
// every widget that does not register its own `summary` component.
function GenericWidgetSummary({ widgetId, args, response }: Props) {
  const tool = typeof args.tool === 'string' ? args.tool : null;
  const { text, tone } = outcomeLabel(widgetId, response);
  return (
    <div className="widget-summary">
      <span className="widget-summary__tag">{widgetId}</span>
      {tool && <code className="widget-summary__tool">{tool}</code>}
      <span className={`widget-summary__outcome ${tone}`}>{text}</span>
    </div>
  );
}

// Dispatcher: render a widget's own read-only summary if it registered one,
// otherwise the generic card. This is what the transcript uses to replay a
// resolved widget.
export function WidgetSummary({ widgetId, args, response }: Props) {
  const Custom = resolveWidgetSummary(widgetId);
  if (Custom) return <Custom args={args} response={response} />;
  return (
    <GenericWidgetSummary widgetId={widgetId} args={args} response={response} />
  );
}
