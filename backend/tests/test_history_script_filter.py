from types import SimpleNamespace

from app.models.core_models import MessageSender
from app.services.ai_orchestrator import AIOrchestrator

GREETING = "Здравствуйте! Я ассистент техподдержки."


def _row(sender: MessageSender, text: str, node_type: str | None, ai: bool | None = None):
    payload = {}
    if node_type is not None:
        payload["node_type"] = node_type
    if ai is not None:
        payload["ai_generated"] = ai
    return SimpleNamespace(sender=sender, message_text=text, payload=payload)


def test_scripted_greeting_and_its_echo_are_left_out_of_history() -> None:
    rows = [
        _row(MessageSender.CLIENT, "привет", None),
        _row(MessageSender.BOT, GREETING, "text_message", False),
        _row(MessageSender.CLIENT, "привет", None),
        _row(MessageSender.BOT, GREETING, "ai_agent", True),
        _row(MessageSender.CLIENT, "какой у вас оффер", None),
        _row(MessageSender.BOT, "Показываю витрину RKR.", "ai_agent", True),
    ]
    history = AIOrchestrator._history_without_scripted_replies(rows)
    assert [item["content"] for item in history] == [
        "привет",
        "привет",
        "какой у вас оффер",
        "Показываю витрину RKR.",
    ]
