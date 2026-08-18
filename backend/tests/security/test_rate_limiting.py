"""Integration tests for SlowAPI rate limiting (HTTP 429)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter, rate_limit_key_crm_public, rate_limit_key_org


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", None) or 60
    try:
        retry_after_int = max(1, int(retry_after))
    except (TypeError, ValueError):
        retry_after_int = 60
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Слишком много запросов. Подождите немного и попробуйте снова.",
            "code": "RATE_LIMIT_EXCEEDED",
            "retry_after": retry_after_int,
        },
        headers={"Retry-After": str(retry_after_int)},
    )


def _build_public_leads_app(*, limit: str = "5/minute") -> FastAPI:
    """
    Standalone app mirroring production public CRM lead ingress rate limiting.

    Uses the shared SlowAPI ``limiter`` with a lower threshold so tests stay fast.
    """
    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = True
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.post("/api/v1/crm/public/leads")
    @limiter.limit(limit, key_func=rate_limit_key_crm_public)
    async def create_inbound_lead(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "accepted": True}, status_code=201)

    return app


@pytest.fixture(autouse=True)
def _reset_limiter_storage() -> None:
    """Isolate rate-limit counters between tests."""
    storage = getattr(limiter, "_storage", None)
    if storage is not None and hasattr(storage, "reset"):
        storage.reset()
    limiter.enabled = True
    yield
    if storage is not None and hasattr(storage, "reset"):
        storage.reset()


def _crm_key(org_label: str) -> dict[str, str]:
    return {"X-CRM-API-Key": f"mpai_crm_test_{org_label}"}


@pytest.mark.asyncio
async def test_public_leads_rate_limit_returns_429() -> None:
    app = _build_public_leads_app(limit="5/minute")
    transport = ASGITransport(app=app)

    statuses: list[int] = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(8):
            resp = await client.post(
                "/api/v1/crm/public/leads",
                json={"first_name": "Flood"},
                headers={**_crm_key("org-a"), "X-Forwarded-For": "198.51.100.20"},
            )
            statuses.append(resp.status_code)

    assert statuses.count(201) >= 1
    assert 429 in statuses

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "Flood"},
            headers=_crm_key("org-a"),
        )
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "detail" in body
    assert "Retry-After" in blocked.headers


@pytest.mark.asyncio
async def test_public_leads_within_limit_succeeds() -> None:
    app = _build_public_leads_app(limit="10/minute")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(5):
            resp = await client.post(
                "/api/v1/crm/public/leads",
                json={"first_name": f"Ok{i}"},
                headers={**_crm_key("org-ok"), "X-Forwarded-For": "203.0.113.55"},
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_api_key() -> None:
    """Org A exhaustion must not block Org B (different CRM API key buckets)."""
    app = _build_public_leads_app(limit="3/minute")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(4):
            await client.post(
                "/api/v1/crm/public/leads",
                json={"first_name": "A"},
                headers=_crm_key("org-a"),
            )
        blocked_a = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "A"},
            headers=_crm_key("org-a"),
        )
        ok_b = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "B"},
            headers=_crm_key("org-b"),
        )

    assert blocked_a.status_code == 429
    assert ok_b.status_code == 201


@pytest.mark.asyncio
async def test_rate_limit_org_key_ignores_spoofed_query_param() -> None:
    """?organization_id= must not create a shared org bucket for unauthenticated callers."""
    victim_org = str(uuid.uuid4())
    attacker_org = str(uuid.uuid4())

    def _anon_request(*, org_query: str, peer: str) -> Request:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/probe",
            "raw_path": b"/probe",
            "query_string": f"organization_id={org_query}".encode(),
            "headers": [],
            "client": (peer, 50000),
            "server": ("test", 80),
        }
        return Request(scope)

    # Spoofed query must be ignored — key stays IP-scoped, not org-scoped.
    key_a = rate_limit_key_org(_anon_request(org_query=victim_org, peer="203.0.113.99"))
    key_b = rate_limit_key_org(_anon_request(org_query=attacker_org, peer="203.0.113.99"))
    key_c = rate_limit_key_org(_anon_request(org_query=victim_org, peer="198.51.100.44"))

    assert key_a.startswith("ip:")
    assert key_b.startswith("ip:")
    assert key_a == key_b
    assert key_a != key_c
    assert victim_org not in key_a
    assert attacker_org not in key_b

    # HTTP path: same spoofed org + same peer exhausts IP bucket only.
    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = True
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/probe")
    @limiter.limit("2/minute", key_func=rate_limit_key_org)
    async def probe(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        statuses: list[int] = []
        for _ in range(3):
            resp = await client.get(f"/probe?organization_id={victim_org}")
            statuses.append(resp.status_code)

    assert statuses.count(200) == 2
    assert statuses.count(429) == 1
