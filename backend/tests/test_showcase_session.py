from types import SimpleNamespace

from app.models.core_models import MessageSender
from app.services.ai_orchestrator import AIOrchestrator
from app.services.showcase_session import (
    apply_case_to_prompt,
    file_matches_case,
    match_case_selection,
    parse_case_routes,
    retrieval_query,
    resolve_showcase_case,
    select_product_rule_chunks,
    strip_unrequested_case_closer,
)

PROMPT = """
MODE 0: MAIN MENU (If {{current_case}} is empty, equals "none", or "main_menu")
* Selected ASAR (or option "1", or text "asar", "асар") ➔ Trigger function `activate_asar_travel_bot`
* Selected KART (or option "2", or text "kart", "карт", "подология") ➔ Trigger function `activate_kart_podology_bot`
* Selected Refresh (or option "5", or text "refresh", "рефреш", "клиника") ➔ Trigger function `activate_refresh_clinic_bot`
MODE 2: CASE "REFRESH CLINIC" (If {{current_case}} == "refresh")
MODE 3: CASE "ASAR TRANS TRAVEL" (If {{current_case}} == "asar")
MODE 4: CASE "KART" (If {{current_case}} == "kart")
OUTPUT THE POST-TEST FEEDBACK AND MENU (Verbatim in Russian):
"Режим тестирования текущего кейса успешно завершен."
"""


def test_router_maps_menu_numbers_to_case_ids() -> None:
    routes = parse_case_routes(PROMPT)
    assert [(route.option, route.case_id) for route in routes] == [
        ("1", "asar"),
        ("2", "kart"),
        ("5", "refresh"),
    ]


def test_podology_choice_stays_kart_until_exit() -> None:
    routes = parse_case_routes(PROMPT)
    assert match_case_selection("2", routes) == "kart"
    assert match_case_selection("подология", routes) == "kart"
    assert resolve_showcase_case(PROMPT, "запишите на вторник", "kart", []) == "kart"
    assert resolve_showcase_case(PROMPT, "выйти", "kart", []) == "main_menu"
    assert "{{current_case}}" not in apply_case_to_prompt(PROMPT, "kart")
    assert 'current_case}} == "kart"' not in apply_case_to_prompt(PROMPT, "kart")
    assert '== "kart"' in apply_case_to_prompt(PROMPT, "kart")


def test_history_recovers_the_case_the_user_already_picked() -> None:
    history = [
        {"role": "assistant", "content": "Выберите кейс"},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "Я Ева, центр подологии"},
        {"role": "user", "content": "болит ноготь"},
    ]
    assert resolve_showcase_case(PROMPT, "сколько стоит удаление", None, history) == "kart"


def test_persona_reply_keeps_podology_when_the_user_never_sent_a_number() -> None:
    history = [
        {"role": "user", "content": "хочу удалить вросший ноготь"},
        {
            "role": "assistant",
            "content": "Здравствуйте! Я Ева, администратор Центра подологии KART.",
        },
    ]
    assert resolve_showcase_case(PROMPT, "сколько стоит", None, history) == "kart"


def test_knowledge_file_stays_inside_the_selected_case() -> None:
    routes = {route.case_id: route.aliases for route in parse_case_routes(PROMPT)}
    assert file_matches_case("KARTMP.txt", "kart", routes["kart"])
    assert not file_matches_case("RefreshMP.txt", "kart", routes["kart"])
    assert file_matches_case("RefreshMP.txt", "refresh", routes["refresh"])
    assert file_matches_case("АСАРMP.txt", "asar", routes["asar"])


def test_product_formulas_stay_in_context_when_the_reply_is_only_a_color() -> None:
    chunks = [
        "Прайс: евроштакетник глянец 450, сайдинг глянец 650.",
        "Если Евроштакетник: последовательно запросить длину забора и тип зашивки.",
        "Формула 1: Евроштакетник. GAP 0.13. Цена глянец 450 за метр планки.",
        "Формула 3: Металлический сайдинг. Площадь умножить на 1000.",
    ]
    selected = select_product_rule_chunks(chunks)
    assert chunks[0] not in selected
    assert "Формула 1" in selected[1]
    assert "сайдинг" in selected[2].casefold()
    query = retrieval_query(
        "Глянец",
        [
            {"role": "user", "content": "Хочу сайдинг"},
            {"role": "assistant", "content": "Какое покрытие?"},
        ],
    )
    assert "Хочу сайдинг" in query
    assert query.endswith("Глянец")


def test_case_closer_and_copied_replies_leave_the_model_history() -> None:
    closer = (
        "Режим тестирования текущего кейса успешно завершен. "
        "Как вам работа нашего ИИ-бота?"
    )
    repeated = (
        "Здравствуйте! Я Ева, администратор Центра подологии KART. "
        "С чем я могу вам помочь? Какие симптомы или проблемы с ногами вас беспокоят?"
    )
    rows = [
        SimpleNamespace(sender=MessageSender.CLIENT, message_text="2", payload={}),
        SimpleNamespace(
            sender=MessageSender.BOT,
            message_text=repeated,
            payload={"node_type": "ai_agent"},
        ),
        SimpleNamespace(
            sender=MessageSender.CLIENT,
            message_text="ноготь",
            payload={},
        ),
        SimpleNamespace(
            sender=MessageSender.BOT,
            message_text=repeated,
            payload={"node_type": "ai_agent"},
        ),
        SimpleNamespace(
            sender=MessageSender.BOT,
            message_text=closer,
            payload={"node_type": "ai_agent"},
        ),
    ]
    history = AIOrchestrator._history_without_scripted_replies(rows)
    assert [item["content"] for item in history] == ["2", repeated, "ноготь"]
    assert strip_unrequested_case_closer(f"Записала на вторник.\n\n{closer}") == "Записала на вторник."
