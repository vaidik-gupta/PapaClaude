"""Bridge the Copilot SDK's built-in `ask_user` tool onto our widget overlay.

`ask_user` is a *native* interaction tool: when the agent calls it, the SDK
dispatches a `userInput.request` to the registered `on_user_input_request`
handler and waits for the answer, rather than running a custom tool of ours.
Since it already exists and is the SDK's canonical "ask the human" primitive, we
use it directly instead of reimplementing choice/question tools.

The request carries `{question, choices, allowFreeform}` and expects a
`{answer, wasFreeform}` response. We route it to the turn's `WidgetBridge`:

    choices present -> the `choice` widget (pick one of N)
    no choices      -> the `question` widget (free-text input)

A dismissed widget (turn cancelled) surfaces as an empty answer, which the SDK
reports back to the model as "no answer".
"""

from __future__ import annotations

from app.agent.widgets import WidgetBridge, WidgetCancelled
from app.logging_config import get_logger

logger = get_logger(__name__)


def build_user_input_handler(bridge: WidgetBridge | None):
    """Build the async `on_user_input_request` handler for one turn.

    Captures the turn's widget bridge so the built-in `ask_user` tool can present
    a choice/question widget and block on the user's answer. With no bridge
    (non-turn paths) there is no stream to surface a widget on, so an empty
    answer is returned.
    """

    async def handler(request, invocation):  # noqa: ANN001 — SDK-typed dicts
        question = request.get("question") or "Please answer"
        choices = list(request.get("choices") or [])
        allow_freeform = request.get("allowFreeform", True)

        if bridge is None:
            return {"answer": "", "wasFreeform": allow_freeform}

        if choices:
            widget_id, args = "choice", {"question": question, "options": choices}
        else:
            widget_id, args = "question", {"question": question}

        try:
            reply = await bridge.present_widget(widget_id, args)
        except WidgetCancelled:
            return {"answer": "", "wasFreeform": allow_freeform}

        answer = reply.get("value") or ""
        # Picking one of the offered choices is not a freeform answer.
        was_freeform = not (bool(choices) and answer in choices)
        return {"answer": answer, "wasFreeform": was_freeform}

    return handler
