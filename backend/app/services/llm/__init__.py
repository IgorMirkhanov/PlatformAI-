"""LLM service package — gateway adapters + legacy completion types."""

from app.services.llm.base import (
    BaseLLMProvider,
    InsufficientCreditsForLLMError,
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState
from app.services.llm.factory import LLMProviderFactory, get_llm_provider, get_llm_gateway
from app.services.llm.gateway import LLMGateway, LLMGatewayError, ResilientLLMGateway
from app.services.llm.pricing import (
    calculate_cost,
    estimate_request_credits,
    normalize_model_name,
    resolve_provider_for_model,
    supported_models,
)
from app.services.llm.prompt_service import (
    PromptTemplateService,
    PromptVariableMissingError,
    prompt_template_service,
)
from app.services.llm.rag_service import RAGService, rag_service
from app.services.llm.types import LLMCompletion, LLMFailureKind, TransientLLMError

__all__ = [
    "BaseLLMProvider",
    "CircuitBreaker",
    "CircuitState",
    "InsufficientCreditsForLLMError",
    "LLMAuthenticationError",
    "LLMCompletion",
    "LLMFailureKind",
    "LLMGateway",
    "LLMGatewayError",
    "LLMInvalidResponseError",
    "LLMProviderError",
    "LLMProviderFactory",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMTimeoutError",
    "PromptTemplateService",
    "PromptVariableMissingError",
    "RAGService",
    "ResilientLLMGateway",
    "TransientLLMError",
    "calculate_cost",
    "estimate_request_credits",
    "get_llm_gateway",
    "get_llm_provider",
    "normalize_model_name",
    "prompt_template_service",
    "rag_service",
    "resolve_provider_for_model",
    "supported_models",
]
