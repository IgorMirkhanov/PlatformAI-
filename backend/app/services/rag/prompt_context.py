"""Shared RAG system-prompt blocks for live chat and flow LLM nodes."""

from __future__ import annotations

ANTI_HALLUCINATION_INSTRUCTION = (
    "Строго запрещено выдумывать факты, цены, даты, условия или детали, которых нет "
    "в приведённом контексте базы знаний. Если ответа нет в контексте — честно скажи, "
    "что информации в базе знаний нет, и предложи уточнить вопрос или связаться с оператором."
)

NO_RAG_CONTEXT_INSTRUCTION = (
    "Релевантные фрагменты базы знаний не найдены (или их релевантность слишком низкая). "
    "Не выдумывай факты о продукте или компании — отвечай общими формулировками или "
    "предложи связаться с оператором."
)


def build_rag_system_addon(chunks: list[str]) -> str:
    """Format retrieved chunks for injection into the system prompt."""
    cleaned = [chunk.strip() for chunk in chunks if chunk and str(chunk).strip()]
    if not cleaned:
        return NO_RAG_CONTEXT_INSTRUCTION

    body = "\n\n".join(f"- {chunk}" for chunk in cleaned)
    return f"Контекст из базы знаний:\n{body}\n\n{ANTI_HALLUCINATION_INSTRUCTION}"
