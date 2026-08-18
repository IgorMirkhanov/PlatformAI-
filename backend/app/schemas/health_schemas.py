from __future__ import annotations

from pydantic import BaseModel, Field


class DependencyHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CeleryClusterHealth(BaseModel):
    status: str
    workers_online: int = 0
    inbound_workers: list[str] = Field(default_factory=list)
    crm_workers: list[str] = Field(default_factory=list)
    detail: str | None = None


class PlatformHealthResponse(BaseModel):
    status: str
    service: str = "mp.ai-platform"
    version: str = "0.1.0"
    checks: dict[str, DependencyHealth]
    celery: CeleryClusterHealth
    ready: bool
    timestamp: str


class LivenessResponse(BaseModel):
    status: str = "alive"
    service: str = "mp.ai-platform"
