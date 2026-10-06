import uuid

from app.services.conversation_routing import prompt_reply_graph, uses_custom_scenario


def test_starter_welcome_card_is_not_a_custom_scenario() -> None:
    graph = {
        "nodes": [
            {
                "id": "welcome_node",
                "type": "text_message",
                "data": {
                    "text": "Здравствуйте! Я ассистент техподдержки.",
                    "buttons": [],
                },
            }
        ],
        "edges": [],
    }
    assert uses_custom_scenario(graph) is False
    assert uses_custom_scenario({}) is False
    assert uses_custom_scenario(None) is False


def test_buttons_or_edges_keep_the_scenario() -> None:
    menu = {
        "nodes": [
            {
                "id": "welcome_node",
                "type": "text_message",
                "data": {
                    "text": "Выберите раздел",
                    "buttons": [{"id": "sales", "text": "Продажи"}],
                },
            }
        ],
        "edges": [],
    }
    linked = {
        "nodes": [
            {"id": "a", "type": "text_message", "data": {"text": "Привет"}},
            {"id": "b", "type": "ai_agent", "data": {"prompt_context": "Отвечай кратко"}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"}],
    }
    assert uses_custom_scenario(menu) is True
    assert uses_custom_scenario(linked) is True


def test_prompt_reply_graph_is_an_ai_node_without_fixed_temperature() -> None:
    bot_id = uuid.uuid4()
    graph = prompt_reply_graph(bot_id)
    assert uses_custom_scenario(graph) is True
    node = graph["nodes"][0]
    assert node["type"] == "ai_agent"
    assert node["data"]["knowledge_base_id"] == str(bot_id)
    assert "temperature" not in node["data"]
    assert graph["edges"] == []
