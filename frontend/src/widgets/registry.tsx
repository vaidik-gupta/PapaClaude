import type { ComponentType } from 'react';

import type { WidgetResponsePayload } from '../api/types';
import { ChoiceWidget } from './ChoiceWidget';
import { DiffWidget } from './DiffWidget';
import { PermissionWidget } from './PermissionWidget';
import { QuestionWidget } from './QuestionWidget';

// Props every live (interactive) widget component receives. `args` is the
// opaque payload the backend tool sent; `onRespond` resolves the widget with a
// value dict that is POSTed back to the awaiting tool.
export interface WidgetProps {
  args: Record<string, unknown>;
  onRespond: (value: Record<string, unknown>) => void;
}

// Props a read-only, post-answer summary component receives when a resolved
// widget is replayed in the transcript. `response` is the recorded outcome
// (null if, somehow, none was persisted).
export interface WidgetSummaryProps {
  args: Record<string, unknown>;
  response: WidgetResponsePayload | null;
}

// A registry entry. `component` is required (the live overlay); `summary` is an
// optional richer read-only view. When `summary` is absent, the transcript
// falls back to a generic summary card, so most widgets need only `component`.
export interface WidgetDef {
  component: ComponentType<WidgetProps>;
  summary?: ComponentType<WidgetSummaryProps>;
}

// id -> definition. The backend knows a widget only by id + args; the frontend
// owns the actual React components. Unknown ids render a fallback (live) or the
// generic summary card (resolved).
const REGISTRY: Record<string, WidgetDef> = {
  permission: { component: PermissionWidget },
  diff: { component: DiffWidget },
  choice: { component: ChoiceWidget },
  question: { component: QuestionWidget },
};

// The live/interactive component for a widget id (undefined => fallback card).
export function resolveWidget(
  widgetId: string,
): ComponentType<WidgetProps> | undefined {
  return REGISTRY[widgetId]?.component;
}

// The optional custom read-only summary component for a widget id. Undefined
// means "use the generic summary card".
export function resolveWidgetSummary(
  widgetId: string,
): ComponentType<WidgetSummaryProps> | undefined {
  return REGISTRY[widgetId]?.summary;
}
