"""MP.AI — System Readiness Check.

Validates all critical infrastructure components before platform launch:
  Block A — PostgreSQL (connection + Alembic version)
  Block B — Redis    (ping + read/write/delete round-trip)
  Block C — LLM Providers (API key presence + live ping completion)

Exit codes:
  0 — PostgreSQL AND Redis are reachable (platform can start).
  1 — At least one *critical* component (DB or Redis) is down.

Usage:
    python scripts/check_system_readiness.py          # from backend/
    python backend/scripts/check_system_readiness.py  # from repo root
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# ---------------------------------------------------------------------------
# Colour helpers (ANSI, disabled on Windows legacy console that doesn't support it)
# ---------------------------------------------------------------------------
import os as _os

_NO_COLOR = not sys.stdout.isatty() or _os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


GREEN = "32;1"
YELLOW = "33;1"
RED = "31;1"
CYAN = "36;1"
BOLD = "1"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    detail: str | None = None
    elapsed_ms: float = 0.0
    critical: bool = False  # FAIL on a critical check ⇒ exit code 1

    def is_ok(self) -> bool:
        return self.status is Status.OK

    def __str__(self) -> str:
        tag = {
            Status.OK: _c(GREEN, "[OK]  "),
            Status.WARN: _c(YELLOW, "[WARN]"),
            Status.FAIL: _c(RED, "[FAIL]"),
        }[self.status]
        timing = f"  ({self.elapsed_ms:.0f} ms)" if self.elapsed_ms else ""
        line = f"  {tag}  {self.name}: {self.message}{timing}"
        if self.detail:
            line += f"\n         {_c(BOLD, 'Detail:')} {self.detail}"
        return line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timer() -> float:
    return time.perf_counter() * 1000  # ms


# ---------------------------------------------------------------------------
# Block A — PostgreSQL
# ---------------------------------------------------------------------------

async def _check_db_connection() -> CheckResult:
    t0 = _timer()
    try:
        from sqlalchemy import text
        from app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return CheckResult(
            name="PostgreSQL connection",
            status=Status.OK,
            message="Reachable (SELECT 1 succeeded)",
            elapsed_ms=_timer() - t0,
            critical=True,
        )
    except Exception as exc:
        return CheckResult(
            name="PostgreSQL connection",
            status=Status.FAIL,
            message="Cannot connect to PostgreSQL",
            detail=str(exc),
            elapsed_ms=_timer() - t0,
            critical=True,
        )


async def _check_alembic_version() -> CheckResult:
    t0 = _timer()
    try:
        from sqlalchemy import text
        from app.core.database import engine

        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).fetchall()

        if not rows:
            return CheckResult(
                name="Alembic version",
                status=Status.WARN,
                message="Table exists but is empty — run 'alembic upgrade head'",
                elapsed_ms=_timer() - t0,
            )

        version = rows[0][0]
        return CheckResult(
            name="Alembic version",
            status=Status.OK,
            message=f"Current revision: {version}",
            elapsed_ms=_timer() - t0,
        )
    except Exception as exc:
        errmsg = str(exc)
        # Table does not exist → migrations were never run.
        if "alembic_version" in errmsg.lower() or "does not exist" in errmsg.lower():
            return CheckResult(
                name="Alembic version",
                status=Status.WARN,
                message="alembic_version table not found — run 'alembic upgrade head'",
                elapsed_ms=_timer() - t0,
            )
        return CheckResult(
            name="Alembic version",
            status=Status.FAIL,
            message="Failed to read alembic_version",
            detail=errmsg,
            elapsed_ms=_timer() - t0,
            critical=True,
        )


async def check_block_a() -> list[CheckResult]:
    conn_result = await _check_db_connection()
    results = [conn_result]
    if conn_result.is_ok():
        results.append(await _check_alembic_version())
    else:
        results.append(
            CheckResult(
                name="Alembic version",
                status=Status.FAIL,
                message="Skipped — DB connection failed",
                critical=False,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Block B — Redis
# ---------------------------------------------------------------------------

async def _get_redis_client():
    """Return an async Redis client from settings.REDIS_URL."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        raise ImportError(
            "Package 'redis' (>=4.2) with asyncio support is not installed. "
            "Run: pip install redis[asyncio]"
        )
    from app.core.config import settings

    return aioredis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


async def _check_redis_ping() -> CheckResult:
    t0 = _timer()
    try:
        client = await _get_redis_client()
        pong = await client.ping()
        await client.aclose()
        if pong:
            return CheckResult(
                name="Redis ping",
                status=Status.OK,
                message="PONG received",
                elapsed_ms=_timer() - t0,
                critical=True,
            )
        return CheckResult(
            name="Redis ping",
            status=Status.FAIL,
            message="PING returned falsy value",
            elapsed_ms=_timer() - t0,
            critical=True,
        )
    except Exception as exc:
        return CheckResult(
            name="Redis ping",
            status=Status.FAIL,
            message="Cannot connect to Redis",
            detail=str(exc),
            elapsed_ms=_timer() - t0,
            critical=True,
        )


async def _check_redis_rw() -> CheckResult:
    t0 = _timer()
    test_key = f"mpai:readiness:{uuid.uuid4().hex}"
    test_val = "ready"
    try:
        client = await _get_redis_client()
        await client.set(test_key, test_val, ex=10)
        got = await client.get(test_key)
        await client.delete(test_key)
        await client.aclose()

        if got == test_val:
            return CheckResult(
                name="Redis read/write",
                status=Status.OK,
                message="Set → Get → Delete round-trip succeeded",
                elapsed_ms=_timer() - t0,
            )
        return CheckResult(
            name="Redis read/write",
            status=Status.FAIL,
            message=f"Value mismatch: expected {test_val!r}, got {got!r}",
            elapsed_ms=_timer() - t0,
        )
    except Exception as exc:
        return CheckResult(
            name="Redis read/write",
            status=Status.FAIL,
            message="Read/write test failed",
            detail=str(exc),
            elapsed_ms=_timer() - t0,
        )


async def check_block_b() -> list[CheckResult]:
    ping = await _check_redis_ping()
    results = [ping]
    if ping.is_ok():
        results.append(await _check_redis_rw())
    else:
        results.append(
            CheckResult(
                name="Redis read/write",
                status=Status.FAIL,
                message="Skipped — Redis ping failed",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Block C — LLM Providers
# ---------------------------------------------------------------------------

# Provider metadata: (display_name, settings_attr, factory_provider_id, model_override)
_PROVIDER_SPECS: list[tuple[str, str, str, str | None]] = [
    ("OpenAI",    "OPENAI_API_KEY",    "openai",    "gpt-4o-mini"),
    ("Anthropic", "ANTHROPIC_API_KEY", "anthropic", None),
    ("Gemini",    "GEMINI_API_KEY",    "gemini",    None),
    ("DeepSeek",  "DEEPSEEK_API_KEY",  "deepseek",  None),
    ("GLM/Zhipu", "GLM_API_KEY",       "glm",       None),
    ("Qwen",      "QWEN_API_KEY",      "qwen",      None),
]

_PING_PROMPT = [{"role": "user", "content": "Reply with the single word: pong"}]


async def _check_provider(
    display: str,
    settings_attr: str,
    factory_id: str,
    model_override: str | None,
) -> CheckResult:
    from app.core.config import settings

    api_key: str | None = getattr(settings, settings_attr, None)

    # --- no key configured -----------------------------------------------
    if not api_key:
        return CheckResult(
            name=f"LLM [{display}]",
            status=Status.WARN,
            message=f"{settings_attr} not set — provider skipped",
        )

    # --- check circuit breaker state -------------------------------------
    try:
        import app.services.llm.providers  # noqa: F401 — register adapters
        from app.services.llm.factory import LLMProviderFactory
        from app.services.llm.gateway import ResilientLLMGateway
        from app.services.llm.circuit_breaker import CircuitState

        provider = LLMProviderFactory.create(factory_id)
        # Construct a single-provider gateway to inspect its breaker.
        gw = ResilientLLMGateway([provider])
        breaker = gw.breaker_for(provider)
        cb_state = breaker.state
        cb_failures = breaker.failure_count
    except Exception as exc:
        return CheckResult(
            name=f"LLM [{display}]",
            status=Status.FAIL,
            message="Provider instantiation failed",
            detail=str(exc),
        )

    if cb_state is CircuitState.OPEN:
        return CheckResult(
            name=f"LLM [{display}]",
            status=Status.FAIL,
            message=f"Circuit breaker OPEN (failures={cb_failures}) — provider is tripped",
        )

    cb_info = f"breaker={cb_state.value}, failures={cb_failures}"

    # --- live ping -------------------------------------------------------
    t0 = _timer()
    try:
        response = await provider.complete(
            messages=_PING_PROMPT,
            max_tokens=5,
            temperature=0.0,
        )
        elapsed = _timer() - t0
        snippet = (response.content or "").strip()[:60]
        return CheckResult(
            name=f"LLM [{display}]",
            status=Status.OK,
            message=f"Ping OK — model={response.model_name!r} reply={snippet!r}",
            detail=cb_info,
            elapsed_ms=elapsed,
        )
    except Exception as exc:
        errmsg = str(exc)
        # Auth / bad key errors are clearly FAIL; rate limits are WARN.
        from app.services.llm.base import LLMAuthenticationError, LLMRateLimitError

        if isinstance(exc, LLMAuthenticationError):
            status = Status.FAIL
            msg = "Authentication failed — check your API key"
        elif isinstance(exc, LLMRateLimitError):
            status = Status.WARN
            msg = "Rate limited (key is valid but quota hit)"
        else:
            status = Status.FAIL
            msg = "Completion request failed"

        return CheckResult(
            name=f"LLM [{display}]",
            status=status,
            message=msg,
            detail=f"{errmsg}  |  {cb_info}",
            elapsed_ms=_timer() - t0,
        )


async def check_block_c() -> list[CheckResult]:
    tasks = [
        _check_provider(display, attr, fid, model)
        for display, attr, fid, model in _PROVIDER_SPECS
    ]
    return list(await asyncio.gather(*tasks))


# ---------------------------------------------------------------------------
# Runner + report
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    width = 60
    print(f"\n{_c(CYAN, '─' * width)}")
    print(f"{_c(CYAN, f'  {title}')}")
    print(_c(CYAN, "─" * width))


async def run_all() -> list[CheckResult]:
    all_results: list[CheckResult] = []

    _section("Block A — PostgreSQL")
    block_a = await check_block_a()
    for r in block_a:
        print(r)
    all_results.extend(block_a)

    _section("Block B — Redis")
    block_b = await check_block_b()
    for r in block_b:
        print(r)
    all_results.extend(block_b)

    _section("Block C — LLM Providers")
    block_c = await check_block_c()
    for r in block_c:
        print(r)
    all_results.extend(block_c)

    return all_results


def _print_summary(results: list[CheckResult]) -> bool:
    """Print summary table. Returns True if critical infrastructure is OK."""
    _section("Summary")

    ok_count = sum(1 for r in results if r.status is Status.OK)
    warn_count = sum(1 for r in results if r.status is Status.WARN)
    fail_count = sum(1 for r in results if r.status is Status.FAIL)

    for r in results:
        tag = {
            Status.OK: _c(GREEN, "OK  "),
            Status.WARN: _c(YELLOW, "WARN"),
            Status.FAIL: _c(RED, "FAIL"),
        }[r.status]
        print(f"  {tag}  {r.name}")

    print()
    print(
        f"  Total: {_c(GREEN, str(ok_count))} OK  "
        f"{_c(YELLOW, str(warn_count))} WARN  "
        f"{_c(RED, str(fail_count))} FAIL"
    )

    critical_fails = [r for r in results if r.status is Status.FAIL and r.critical]
    can_launch = len(critical_fails) == 0

    print()
    if can_launch:
        print(f"  {_c(GREEN, 'Ready to launch: YES ✓')}")
    else:
        print(f"  {_c(RED, 'Ready to launch: NO ✗')}")
        print(f"  {_c(RED, 'Critical failures:')}")
        for r in critical_fails:
            print(f"    • {r.name}: {r.message}")

    print()
    return can_launch


async def _main() -> None:
    print(f"\n{_c(BOLD, '═══════════════════════════════════════════════════════════')}")
    print(f"{_c(BOLD, '     MP.AI — System Readiness Check')}")
    print(f"{_c(BOLD, '═══════════════════════════════════════════════════════════')}")

    try:
        results = await run_all()
    except Exception:
        print(f"\n{_c(RED, '[FATAL] Unexpected error during checks:')}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Always dispose DB engine to allow clean shutdown.
        try:
            from app.core.database import engine
            await engine.dispose()
        except Exception:
            pass

    can_launch = _print_summary(results)
    sys.exit(0 if can_launch else 1)


if __name__ == "__main__":
    asyncio.run(_main())
