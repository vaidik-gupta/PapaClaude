"""Widget plumbing — the one primitive any tool uses to involve the human.

A *widget* is opaque to the backend: a tool presents it as `widget_id + args`
and blocks until the user responds; the frontend owns an `id -> React component`
registry. Two pieces cooperate, because the *emit* side is per-turn but the
*resolve* side is a separate HTTP request:

- `WidgetBridge` (per-turn): bound into the tool handlers, it emits a `widget`
  event onto the live turn stream and awaits the user's reply.
- `PendingWidgets` (process-global): maps an instance id -> Future so the
  `/respond` endpoint (a different coroutine) can resolve a future it did not
  create. Resolution is validated against the owning conversation.

Cancellation (Stop/Esc/stream teardown) cancels the pending future, so
`present_widget` raises `WidgetCancelled` and the tool aborts cleanly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4

from app.conversations.schema import EventType
from app.logging_config import get_logger

logger = get_logger(__name__)


class WidgetCancelled(Exception):
    """Raised inside a tool when its pending widget is cancelled (Stop/Esc)."""


@dataclass
class _Pending:
    conversation_id: str
    future: asyncio.Future


class PendingWidgets:
    """Process-global registry of in-flight widget futures, keyed by instance id."""

    def __init__(self) -> None:
        self._items: dict[str, _Pending] = {}

    def register(self, instance_id: str, conversation_id: str) -> asyncio.Future:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._items[instance_id] = _Pending(conversation_id, future)
        return future

    def resolve(self, instance_id: str, conversation_id: str, value: dict) -> bool:
        """Resolve a pending widget for the given conversation. Returns False if
        there is no matching pending widget (unknown/foreign/instance)."""
        pending = self._items.get(instance_id)
        if pending is None or pending.conversation_id != conversation_id:
            return False
        if not pending.future.done():
            pending.future.set_result(value)
        return True

    def cancel(self, instance_id: str) -> None:
        pending = self._items.get(instance_id)
        if pending is not None and not pending.future.done():
            pending.future.cancel()

    def discard(self, instance_id: str) -> None:
        self._items.pop(instance_id, None)


# The one shared registry the respond endpoint and every turn use.
pending_widgets = PendingWidgets()

# Emits a (type, payload) pair onto the turn's event stream.
Emit = Callable[[EventType, dict], None]


@dataclass
class WidgetBridge:
    """Per-turn channel letting a tool present a widget and await the reply."""

    emit: Emit
    conversation_id: str
    registry: PendingWidgets = pending_widgets
    _live: set[str] = field(default_factory=set)

    async def present_widget(self, widget_id: str, args: dict) -> dict:
        """Emit a widget to the UI and block until the user responds.

        Returns the user's response dict. Raises WidgetCancelled if the turn is
        stopped (or the widget is otherwise cancelled) before a response.
        """
        instance_id = uuid4().hex
        future = self.registry.register(instance_id, self.conversation_id)
        self._live.add(instance_id)
        self.emit(
            EventType.WIDGET,
            {"instance_id": instance_id, "widget_id": widget_id, "args": args},
        )
        try:
            value = await future
        except asyncio.CancelledError as exc:
            self.emit(
                EventType.WIDGET_RESPONSE,
                {"instance_id": instance_id, "status": "cancelled"},
            )
            raise WidgetCancelled(widget_id) from exc
        finally:
            self.registry.discard(instance_id)
            self._live.discard(instance_id)
        self.emit(
            EventType.WIDGET_RESPONSE,
            {"instance_id": instance_id, "status": "answered", "value": value},
        )
        return value

    def cancel_all(self) -> None:
        """Cancel any still-pending widgets (called on turn teardown)."""
        for instance_id in list(self._live):
            self.registry.cancel(instance_id)
