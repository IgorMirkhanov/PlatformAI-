"""LLM Gateway HTTP endpoints."""

from app.api.endpoints.llm.prompts import router as prompts_router
from app.api.endpoints.llm.rag import router as knowledge_router

__all__ = ["knowledge_router", "prompts_router"]
