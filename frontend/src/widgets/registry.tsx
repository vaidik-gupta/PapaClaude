import type { ComponentType } from 'react';

import { PermissionWidget } from './PermissionWidget';

// Props every widget component receives. `args` is the opaque payload the
// backend tool sent; `onRespond` resolves the widget with a value dict that is
// POSTed back to the awaiting tool.
export interface WidgetProps {
  args: Record<string, unknown>;
  onRespond: (value: Record<string, unknown>) => void;
}

// id -> component. The backend knows a widget only by id + args; the frontend
// owns the actual React component. Unknown ids render a fallback.
const REGISTRY: Record<string, ComponentType<WidgetProps>> = {
  permission: PermissionWidget,
};

export function resolveWidget(
  widgetId: string,
): ComponentType<WidgetProps> | undefined {
  return REGISTRY[widgetId];
}
