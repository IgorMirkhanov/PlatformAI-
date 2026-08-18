from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.sandbox_schemas import (
    ExecutionTrace,
    LLMMetricsTrace,
    RAGChunkTrace,
    TraceNodeStep,
    TraceTransition,
)


class ExecutionTraceBuilder:
    """Accumulates ordered runtime diagnostics for sandbox simulations."""

    def __init__(self) -> None:
        self._nodes: list[TraceNodeStep] = []
        self._transitions: list[TraceTransition] = []
        self._rag: list[RAGChunkTrace] = []
        self._llm: LLMMetricsTrace | None = None
        self._errors: list[str] = []
        self._current_node_id: str | None = None
        self._open_started_at: dict[str, datetime] = {}

    def record_node(
        self,
        node_id: str,
        node_type: str,
        *,
        label: str | None = None,
        status: str = "OK",
    ) -> None:
        now = datetime.now(UTC)
        self._current_node_id = node_id
        if self._nodes and self._nodes[-1].node_id == node_id:
            # Complete duration on re-entry / finalize.
            prev = self._nodes[-1]
            started = prev.started_at or self._open_started_at.get(node_id) or now
            duration = max(0.0, (now - started).total_seconds() * 1000.0)
            self._nodes[-1] = prev.model_copy(
                update={
                    "status": status or prev.status,
                    "finished_at": now,
                    "duration_ms": round(duration, 3),
                    "label": label or prev.label,
                }
            )
            return

        started = now
        self._open_started_at[node_id] = started
        self._nodes.append(
            TraceNodeStep(
                node_id=node_id,
                node_type=node_type,
                label=label,
                status=status,
                started_at=started,
                finished_at=now,
                duration_ms=0.0,
            ),
        )

    def finalize_open_nodes(self, *, status: str = "OK") -> None:
        """Mark any open steps as finished (used at end of a sandbox turn)."""
        now = datetime.now(UTC)
        updated: list[TraceNodeStep] = []
        for step in self._nodes:
            if step.finished_at is None or step.duration_ms is None:
                started = step.started_at or now
                duration = max(0.0, (now - started).total_seconds() * 1000.0)
                updated.append(
                    step.model_copy(
                        update={
                            "status": status if step.status == "OK" else step.status,
                            "finished_at": now,
                            "duration_ms": round(duration, 3),
                        }
                    )
                )
            else:
                updated.append(step)
        self._nodes = updated

    def record_transition(
        self,
        from_node_id: str,
        to_node_id: str,
        *,
        via_handle: str | None = None,
        edge_id: str | None = None,
    ) -> None:
        if not from_node_id or not to_node_id or from_node_id == to_node_id:
            return
        self._transitions.append(
            TraceTransition(
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                via_handle=via_handle,
                edge_id=edge_id,
            ),
        )

    def record_rag_chunks(self, chunks: list[RAGChunkTrace]) -> None:
        self._rag = chunks

    def record_llm_metrics(self, metrics: LLMMetricsTrace) -> None:
        self._llm = metrics

    def record_error(self, message: str) -> None:
        if message and message not in self._errors:
            self._errors.append(message)
            if self._nodes:
                last = self._nodes[-1]
                self._nodes[-1] = last.model_copy(update={"status": "ERROR"})

    def set_current_node(self, node_id: str | None) -> None:
        self._current_node_id = node_id

    def to_model(self) -> ExecutionTrace:
        self.finalize_open_nodes()
        return ExecutionTrace(
            nodes_triggered=list(self._nodes),
            transitions=list(self._transitions),
            rag_context=list(self._rag),
            llm_metrics=self._llm,
            errors=list(self._errors),
            simulation=True,
            current_node_id=self._current_node_id,
        )
