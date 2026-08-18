"""LLM domain models."""

from __future__ import annotations

from app.models.llm.knowledge import KnowledgeBase, KnowledgeDocument
from app.models.llm.prompt_template import PromptTemplate

__all__ = ["KnowledgeBase", "KnowledgeDocument", "PromptTemplate"]
