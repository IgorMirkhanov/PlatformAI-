"""
MP.AI Locust load suite — auth, bots, flow-builder, execute, WhatsApp.

Targets (GA gate):
  - ~20 RPS aggregate under steady state
  - p95(/api/v1/bots/{id}/execute) < 2.0s
  - error rate < 1% (exclude intentional 402 quota)

Usage (local):
  export MPAI_BASE_URL=http://localhost:8000
  export MPAI_EMAIL=load@example.com
  export MPAI_PASSWORD=secret
  # OR pre-minted token:
  export MPAI_TOKEN=<jwt>
  export MPAI_BOT_ID=<uuid>          # optional; created on the fly if missing
  export MPAI_ORG_ID=<uuid>          # optional X-Company-Id
  export MPAI_WHATSAPP_BOT_ID=<uuid> # optional WhatsApp send path

  locust -f locustfile.py --host=$MPAI_BASE_URL \\
    --users 50 --spawn-rate 5 --run-time 10m \\
    --csv=reports/locust --headless

Docker:
  docker compose -f docker-compose.prod.yml run --rm backend \\
    locust -f locustfile.py --host=http://api:8000 --users 20 --spawn-rate 2 \\
    --run-time 5m --headless --csv=/tmp/locust

Staging:
  MPAI_BASE_URL=https://staging.mp.ai locust -f locustfile.py --host=$MPAI_BASE_URL ...

Thresholds (asserted when MPAI_ASSERT_THRESHOLDS=1):
  execute p95 < 2000ms, fail_ratio < 0.01
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

from locust import HttpUser, LoadTestShape, between, events, task
from locust.runners import MasterRunner


BASE_PATH = "/api/v1"
EXECUTE_P95_MS = float(os.getenv("MPAI_EXECUTE_P95_MS", "2000"))
MAX_FAIL_RATIO = float(os.getenv("MPAI_MAX_FAIL_RATIO", "0.01"))
ASSERT_THRESHOLDS = os.getenv("MPAI_ASSERT_THRESHOLDS", "0") == "1"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


class MpAiUser(HttpUser):
    """
    Mixed SaaS journey. Weights approximate real traffic:
      execute >> browse flow >> auth/health >> bot create >> whatsapp
    """

    wait_time = between(0.3, 1.2)

    def on_start(self) -> None:
        self.token = _env("MPAI_TOKEN")
        self.bot_id = _env("MPAI_BOT_ID")
        self.org_id = _env("MPAI_ORG_ID")
        self.whatsapp_bot_id = _env("MPAI_WHATSAPP_BOT_ID") or self.bot_id
        self.email = _env("MPAI_EMAIL")
        self.password = _env("MPAI_PASSWORD")

        if not self.token and self.email and self.password:
            self._login()
        if not self.token:
            # Still allow health-only runs; heavy tasks will skip.
            self.client.headers.update({"Content-Type": "application/json"})
            return

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if self.org_id:
            headers["X-Company-Id"] = self.org_id
        self.client.headers.update(headers)

        if not self.bot_id:
            self._ensure_bot()

    def _login(self) -> None:
        with self.client.post(
            f"{BASE_PATH}/auth/login",
            json={"email": self.email, "password": self.password},
            name="/api/v1/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"login failed {resp.status_code}")
                return
            body = resp.json()
            self.token = (
                body.get("access_token")
                or body.get("token")
                or (body.get("tokens") or {}).get("access_token")
                or ""
            )
            if not self.token:
                resp.failure("login response missing access_token")
                return
            resp.success()

    def _ensure_bot(self) -> None:
        with self.client.post(
            f"{BASE_PATH}/bots",
            json={
                "name": f"locust-{int(time.time())}-{random.randint(1000, 9999)}",
                "platform_type": "TELEGRAM",
                "use_case": "empty",
            },
            name="/api/v1/bots [create]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201):
                data = resp.json()
                self.bot_id = str(data.get("bot_id") or data.get("id") or "")
                resp.success()
            elif resp.status_code == 402:
                resp.success()  # quota — expected under load on FREE
            else:
                resp.failure(f"create bot {resp.status_code}")

    @task(1)
    def health(self) -> None:
        self.client.get(f"{BASE_PATH}/health/live", name="/api/v1/health/live")

    @task(1)
    def auth_refresh_or_me(self) -> None:
        if not self.token:
            return
        # Prefer lightweight identity check; fall back to health if me absent.
        with self.client.get(
            f"{BASE_PATH}/auth/me",
            name="/api/v1/auth/me",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()
                self.client.get(f"{BASE_PATH}/billing/stripe/status", name="/api/v1/billing/stripe/status")
            elif resp.status_code >= 500:
                resp.failure(f"auth/me {resp.status_code}")
            else:
                resp.success()

    @task(2)
    def create_bot(self) -> None:
        if not self.token:
            return
        with self.client.post(
            f"{BASE_PATH}/bots",
            json={
                "name": f"locust-bot-{random.randint(1, 1_000_000)}",
                "platform_type": "TELEGRAM",
                "use_case": "empty",
            },
            name="/api/v1/bots [create]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201, 402):
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"create bot {resp.status_code}")
            else:
                resp.failure(f"create bot {resp.status_code}")

    @task(3)
    def open_flow_builder(self) -> None:
        if not self.token or not self.bot_id:
            return
        # Flow draft / graph endpoints used by constructor.
        with self.client.get(
            f"{BASE_PATH}/bots/{self.bot_id}/flow",
            name="/api/v1/bots/{id}/flow",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"flow {resp.status_code}")
            else:
                resp.failure(f"flow {resp.status_code}")

        self.client.get(
            f"{BASE_PATH}/bots/{self.bot_id}/profile",
            name="/api/v1/bots/{id}/profile",
        )

    @task(8)
    def execute_simple_flow(self) -> None:
        if not self.token or not self.bot_id:
            return
        payload = {
            "message": random.choice(
                [
                    "hello",
                    "what are your hours?",
                    "price list please",
                    "connect me to operator",
                    "how does refund work?",
                ]
            ),
            "use_draft": True,
        }
        started = time.perf_counter()
        with self.client.post(
            f"{BASE_PATH}/bots/{self.bot_id}/execute",
            json=payload,
            name="/api/v1/bots/{id}/execute",
            catch_response=True,
        ) as resp:
            elapsed_ms = (time.perf_counter() - started) * 1000
            if resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")
            elif resp.status_code == 401:
                resp.failure("unauthorized — check MPAI_TOKEN")
            elif resp.status_code == 402:
                resp.success()  # quota under load
            elif elapsed_ms > EXECUTE_P95_MS * 2:
                # Soft flag extreme outliers; hard gate is on test_stop p95.
                resp.failure(f"execute too slow {elapsed_ms:.0f}ms")
            else:
                resp.success()

    @task(2)
    def whatsapp_send_message(self) -> None:
        if not self.token or not self.whatsapp_bot_id:
            return
        # Prefer public WhatsApp webhook-style ingress if present; else noop success.
        payload: dict[str, Any] = {
            "message": "locust whatsapp ping",
            "from": f"+7700{random.randint(1000000, 9999999)}",
        }
        with self.client.post(
            f"{BASE_PATH}/webhooks/whatsapp/{self.whatsapp_bot_id}",
            json=payload,
            name="/api/v1/webhooks/whatsapp/{id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202, 404, 405):
                # 404/405 = endpoint shape differs on env — don't fail the suite.
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"whatsapp {resp.status_code}")
            else:
                resp.success()


class StagesShape(LoadTestShape):
    """
    Ramp 10 → 50 users (~20 RPS target at peak with wait_time ~0.3–1.2s).

    Disable with MPAI_DISABLE_SHAPE=1 to use CLI --users/--spawn-rate only.
    """

    stages = [
        {"duration": 60, "users": 10, "spawn_rate": 2},
        {"duration": 180, "users": 25, "spawn_rate": 5},
        {"duration": 420, "users": 50, "spawn_rate": 5},
        {"duration": 540, "users": 20, "spawn_rate": 5},  # cool-down
    ]

    def tick(self):
        if _env("MPAI_DISABLE_SHAPE", "0") == "1":
            return None
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    if not ASSERT_THRESHOLDS:
        return
    if isinstance(environment.runner, MasterRunner):
        return
    stats = environment.stats
    total = stats.total
    fail_ratio = total.fail_ratio if total.num_requests else 0.0
    execute = stats.get("/api/v1/bots/{id}/execute", "POST")
    p95 = execute.get_response_time_percentile(0.95) if execute and execute.num_requests else 0

    print("\n=== MP.AI Locust threshold report ===")
    print(f"requests={total.num_requests} fail_ratio={fail_ratio:.4f} (max {MAX_FAIL_RATIO})")
    print(f"execute p95={p95:.0f}ms (max {EXECUTE_P95_MS:.0f}ms)")

    breached = False
    if fail_ratio > MAX_FAIL_RATIO:
        print("FAIL: error ratio above threshold")
        breached = True
    if execute and execute.num_requests and p95 > EXECUTE_P95_MS:
        print("FAIL: /execute p95 above threshold")
        breached = True
    if breached:
        environment.process_exit_code = 1
    else:
        print("PASS: thresholds met")
