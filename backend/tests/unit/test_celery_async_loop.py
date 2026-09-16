"""Celery asyncio helper must reuse one loop instead of asyncio.run+dispose."""

from __future__ import annotations

import asyncio

from app.db.session import reset_celery_async_state, run_celery_async


def test_run_celery_async_reuses_the_same_loop() -> None:
    reset_celery_async_state()
    loop_ids: list[int] = []

    async def _mark() -> int:
        loop_id = id(asyncio.get_running_loop())
        loop_ids.append(loop_id)
        return loop_id

    first = run_celery_async(_mark())
    second = run_celery_async(_mark())
    assert first == second
    assert loop_ids == [first, second]
    reset_celery_async_state()


def test_run_celery_async_survives_closed_loop_reset() -> None:
    reset_celery_async_state()

    async def _ok() -> str:
        return "ok"

    assert run_celery_async(_ok()) == "ok"
    reset_celery_async_state()
    assert run_celery_async(_ok()) == "ok"
    reset_celery_async_state()
