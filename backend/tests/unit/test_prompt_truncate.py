from app.services.ai_orchestrator import AIOrchestrator


def test_truncate_messages_always_keeps_latest_user(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.MAX_PROMPT_CHARS",
        2000,
        raising=False,
    )
    orch = AIOrchestrator()
    latest = "Мебель, 800кг, из Шанхая до Алматы"
    messages = [
        {"role": "system", "content": "S" * 2500},
        {"role": "user", "content": "старое"},
        {"role": "assistant", "content": "меню"},
        {"role": "user", "content": latest},
    ]
    kept = orch._truncate_messages(messages)
    assert kept[-1]["role"] == "user"
    assert latest in kept[-1]["content"]
    assert sum(len(m["content"]) for m in kept) <= 2000
