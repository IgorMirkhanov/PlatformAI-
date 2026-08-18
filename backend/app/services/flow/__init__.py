"""Flow Builder engine package — Redis sessions + loop-protected executor."""

from app.services.flow.engine import (
    FlowEngineError,
    FlowExecutionEngine,
    FlowExecutionLoopError,
    FlowExecutionResult,
    FlowSessionManager,
    FlowSessionState,
)
from app.services.flow.executor import execute_flow, load_flow_graph
from app.services.flow.nodes import (
    ApiRequestNodeHandler,
    ConditionNodeHandler,
    CrmActionNodeHandler,
    LLMNodeHandler,
    NodeHandlerRegistry,
    TriggerNodeHandler,
    build_default_node_registry,
)

__all__ = [
    "ApiRequestNodeHandler",
    "ConditionNodeHandler",
    "CrmActionNodeHandler",
    "FlowEngineError",
    "FlowExecutionEngine",
    "FlowExecutionLoopError",
    "FlowExecutionResult",
    "FlowSessionManager",
    "FlowSessionState",
    "LLMNodeHandler",
    "NodeHandlerRegistry",
    "TriggerNodeHandler",
    "build_default_node_registry",
    "execute_flow",
    "load_flow_graph",
]
