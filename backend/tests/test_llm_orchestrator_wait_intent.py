"""Wait-intent routing for photo vs calc force paths."""

from __future__ import annotations

from app.services.llm_orchestrator import LLMOrchestrator


def test_classify_calc_wait_not_photo() -> None:
    text = (
        "Теперь я выполню расчет для вашего заказа:\n"
        "- Высота штакетника: 3 метра\n"
        "Пожалуйста, подождите немного."
    )
    assert LLMOrchestrator._classify_wait_intent(text) == "calc"


def test_classify_photo_wait() -> None:
    text = "Я отправлю вам фотографии евроштакетника. Пожалуйста, подождите немного."
    assert LLMOrchestrator._classify_wait_intent(text) == "photo"


def test_classify_both_photo_and_calc() -> None:
    text = (
        "Вот фотографии с матовым покрытием. "
        "Теперь я выполню расчет. Пожалуйста, подождите немного."
    )
    assert LLMOrchestrator._classify_wait_intent(text) == "both"


def test_height_correction_suppresses_media_resend() -> None:
    messages = [{"role": "user", "content": "Высота 3,5"}]
    assert LLMOrchestrator._user_turn_suppresses_media_resend(messages) is True


def test_calc_request_suppresses_media_resend() -> None:
    messages = [{"role": "user", "content": "Отправите расчет?"}]
    assert LLMOrchestrator._user_turn_suppresses_media_resend(messages) is True


def test_photo_request_allows_media() -> None:
    messages = [{"role": "user", "content": "А отправьте пожалуйста фотки цветов"}]
    assert LLMOrchestrator._user_turn_suppresses_media_resend(messages) is False


def test_calc_result_detection() -> None:
    assert LLMOrchestrator._text_has_calc_result(
        "Предварительная стоимость производства: 2691500 ₸"
    )
    assert not LLMOrchestrator._text_has_calc_result("Пожалуйста, подождите немного.")


def test_media_tool_detection_from_description() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "send_colors",
            "description": (
                "Send color samples. Call this function in the SAME turn whenever "
                "the user asks for photos, files, samples, or visual examples."
            ),
        },
    }
    assert LLMOrchestrator._is_media_tool(tool) is True
    assert LLMOrchestrator._is_calc_tool(tool) is False
