# MP.AI commercial release checklist

Source spec: `docs/architecture/mpai-commercial-release-spec.md`  
Concurrency / UI / Windows Python: [`PRE_LAUNCH_RISKS.md`](./PRE_LAUNCH_RISKS.md)

## Migrations

Run from `backend/`:

```bash
alembic upgrade head
```

| Revision | Purpose |
|---|---|
| `057_organization_wallets` | Token columns on `organization_wallets` + `wallet_transactions` ledger + grace backfill |
| `058_bot_low_balance_message` | `bots.low_balance_message` |
| `059_operator_notifications` | `operator_notification_channels` + `clients.conversation_status` |

`downgrade()` is implemented on each revision.

### Windows Store Python + Alembic package shadow

Two separate failures that both look like "tests passed" because pytest **skips** real-DB fixtures:

1. **Store stub:** `WindowsApps\PythonSoftwareFoundation.*` is not the venv. Create `backend/.venv` (`python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`) or use the backend Docker image.
2. **Name clash:** folder `backend/alembic/` (revision scripts) is a namespace that shadows the PyPI `alembic` package when cwd/pythonpath is `backend/`. `env.py` and `tests/conftest.py` insert `site-packages` first. CI uses a real venv via `actions/setup-python`.

Tests apply migrations **in-process** (`alembic.command.upgrade`), not via a child interpreter.

## New HTTP endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/wallet` | Token balance, status, last 20 ledger rows |
| GET | `/api/v1/wallet/usage-by-bot?days=7\|30` | Spend grouped by `bot_id` |
| GET | `/api/v1/credentials` | Vault list (no secrets) |
| POST | `/api/v1/credentials` | `validate_before_save` pings OpenAI `/v1/models` or Telegram `getMe` |
| POST | `/api/v1/credentials/{id}/validate` | Re-ping existing secret |
| POST | `/api/v1/playground/chat` | `dry_run=true` skips `debit_atomic` |

Existing credit wallet remains at `GET /api/v1/billing/wallet`.

## Frontend

- `/dashboard/wallet` — polls every 10s, blocked CTA
- `/dashboard/byok-vault` — inline validation errors
- `/dashboard/playground` — dry-run chat + RAG chunks + token estimate

## Invariants

1. `SELECT … FOR UPDATE` is taken only on that organization's `organization_wallets` row. PostgreSQL row locks are per tuple, so org B cannot wait on org A's wallet lock.
2. LLM is not called when the read-only pre-check fails (`check_wallet_before_generation`).
3. Token debit runs after a successful completion, idempotent on `{conversation_id}:{usage_log_id}`.
4. Payment top-up credits tokens with the same payment reference (`payment:{provider}:{id}`).
5. `ai_orchestrator` stays channel-agnostic; `MessageFormatter` runs in `outbound_router`.
6. CRM upsert/create failures never drop the messenger reply.

## Tests (one command)

From repo root, with Docker available for Postgres testcontainers. **Do not treat skipped tests as verified.**

```bash
cd backend && python -m pytest tests/unit/test_message_formatter.py tests/unit/test_wallet_repository.py tests/stress/test_wallet_isolation.py tests/stress/test_deal_idempotency.py tests/integration/test_oauth_refresh_race.py tests/test_error_correlation.py tests/test_byok_architecture.py -q
cd ../frontend && npx playwright test e2e/wallet-isolation.spec.ts e2e/byok-vault-validation.spec.ts e2e/saas-v1-flow.spec.ts
```

Record outcomes in [`PRE_LAUNCH_RISKS.md`](./PRE_LAUNCH_RISKS.md) (`verified locally` vs `verified only in CI`).

Channel matrix CLI:

```bash
python backend/scripts/verify_channel_readiness.py
```

## Ops leftovers

- TLS, live Stripe, Locust, counsel review of legal copy
- `ENABLE_MONITORING=1` + Prometheus scrape of `wallet_blocked_events_total`, `oauth_refresh_total`, `webhook_events_total`
- Previous tagged image kept for rollback
