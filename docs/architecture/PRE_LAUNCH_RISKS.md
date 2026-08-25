# Pre-launch risks — concurrency, UI, Windows Alembic

Companion to [`RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md).  
Statuses: **verified locally** | **verified only in CI** | **not verified**.

Update the Status column after each run. Do not treat a skipped pytest as a pass.

## How to run the gates

From repo root, **project venv** (not Windows Store Python) and Docker for Postgres:

```bash
cd backend
python -m pytest tests/unit/test_wallet_repository.py tests/stress/test_wallet_isolation.py tests/stress/test_deal_idempotency.py tests/integration/test_oauth_refresh_race.py -q --tb=short
cd ../frontend
npx playwright test e2e/wallet-isolation.spec.ts e2e/byok-vault-validation.spec.ts --project=chromium
```

CI job `Concurrency gates (wallet / CRM / OAuth)` fails if Alembic or Docker is missing (`CI=true` converts skip → fail).

## Windows Store Python + Alembic

| Item | Detail |
|---|---|
| Symptom | `from alembic.config import Config` fails or real-DB tests skip |
| Cause A | Microsoft Store Python stub (`WindowsApps\PythonSoftwareFoundation.*`) is not a venv |
| Cause B | Folder `backend/alembic/` shadows the PyPI `alembic` package when cwd is `backend/` |
| Local fix | `python -m venv backend/.venv` then `backend/.venv/Scripts/pip install -r backend/requirements.txt`. Confirm: `.venv/Scripts/python -c "import sys; print(sys.executable); import alembic.config"` |
| CI / Docker | `actions/setup-python` + pip; production image `python:3.11-slim` |
| Tests | In-process `alembic.command.upgrade`; `env.py` / `conftest.py` put `site-packages` first |

## Risk register

| ID | Risk | Proof | Status |
|---|---|---|---|
| R1 | Concurrent token debit overdraws an org or blocks another tenant | `tests/stress/test_wallet_isolation.py`: 50 parallel debits on org A (balance 10) → **10** ledger rows, `balance_tokens == 0`, `status=blocked`; org B 20/20 succeed; `balance_tokens >= 0` | **verified locally** (2026-08-24, `backend/.venv` + Docker testcontainers). CI job `Concurrency gates` must not skip. |
| R2 | Parallel inbound messages create duplicate deals / extra amoCRM HTTP | `tests/stress/test_deal_idempotency.py`: 20× `upsert_idempotent` → 1 insert; 20× `handle_new_message_for_crm` → 1 `CrmDeal` and `AmoCRMAdapter.create_lead` **await_count == 1** | **verified locally** (2026-08-24) |
| R3 | Two Celery OAuth refresh workers both hit amoCRM | `tests/integration/test_oauth_refresh_race.py`: two `_refresh_expiring_oauth_tokens()`; `pg_try_advisory_lock` per `credential_id`; **one** `_amocrm_token_request` | **verified locally** (2026-08-24) |
| R4 | BYOK validation error not visible | Playwright `e2e/byok-vault-validation.spec.ts`: invalid key → `byok-error`, no `byok-item` | **verified locally** (2026-08-24, Chromium). Also in CI e2e job after this change. |
| R5 | Blocked wallet not shown on dashboard / wallet page | Playwright `e2e/wallet-isolation.spec.ts`: `/dashboard` `wallet-blocked-banner`; `/dashboard/wallet` `wallet-page-blocked-banner` | **verified locally** (2026-08-24) |
| R6 | Wallet balance poll never fires | Same spec: second `GET /api/v1/wallet` after ~10s | **verified locally** (2026-08-24) |
| R7 | Playground hides wallet-blocked copy | Same spec: `playground-error` after send | **verified locally** (2026-08-24) |

## Notes

- Wallet `SELECT … FOR UPDATE` is **per `organization_wallets` row**, not a global lock. Org B latency bound in the stress test is 750ms (Windows Docker); the spec’s 200ms is a production SLO, not this laptop.
- Advisory lock helper **fails closed** (`try_advisory_lock` returns `False` on DB error) so a lock failure cannot become a double HTTP refresh.
- Playwright seeds `mpai_access_token` as a JWT with `exp` (middleware) and persist key `ai-bot-platform-store`.
