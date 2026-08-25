"""Pre-launch E2E checklist for Integration Hub (Bitrix24 / amoCRM / Wazzup).

Use after code review items 1–5 are closed. Kaspi Pay and WhatsApp Cloud API stay deferred.

## 0. Redirect URI (do this first)

1. Set `WEBHOOK_BASE_URL=https://api.mp.ai` (no trailing slash).
2. `GET /api/v1/integrations/hub/oauth-redirect-uris` (auth required) and copy:
   - Bitrix24: `https://api.mp.ai/api/v1/integrations/bitrix24/callback`
   - amoCRM: `https://api.mp.ai/api/v1/integrations/amocrm/callback`
3. Register those URLs **character-for-character** in partners.bitrix24.com and amoCRM developer cabinet.
4. Confirm hub OAuth ignores a mismatched `AMOCRM_REDIRECT_URI` (warning in logs, canonical wins).

## 1. Outbound Redis lock TTL

1. Connect Bitrix24 or amoCRM on a test workspace.
2. Trigger many outbound agent actions (create contact × N) while watching Redis:
   `KEYS ihub:out:lock:*` and `TTL ihub:out:lock:{connection_id}` — TTL must be > 0 (default 90s).
3. Kill the Celery worker mid-job (`kill -9`). Within TTL the lock must disappear and a new outbound job must run.
4. Confirm no permanent stall of outbound for that `connection_id`.

## 2. Webhook DLQ / retries

1. Temporarily break normalize (or point a test webhook at a bad payload that raises).
2. Enqueue `process_hub_webhook_event` and watch `integration_webhook_events.status`:
   - retries: `received` → `processing` → back to `received` with `error` set
   - after `HUB_WEBHOOK_MAX_RETRIES` (default 8): status = `dead_letter`, Celery stops retrying
3. Happy path still ends in `processed`.
4. Duplicate `external_event_id` stays `duplicate` and never re-dispatches AI.

## 3. Billing usage bridge

1. Send a real Wazzup inbound message to a connected agent.
2. Assert rows in both:
   - `integration_usage_events` (`metric=wazzup_webhook`)
   - `usage_events` (`metric_type=MESSAGE_IN`, `meta.source=integration_hub`)
3. Trigger an outbound hub adapter action; expect `hub_adapter_ok` → `CRM_CALL` in `usage_events`.
4. Bitrix/amoCRM inbound webhooks similarly emit `CRM_CALL`.

## 4. Tenant isolation

1. Create connections in workspace A and workspace B.
2. As user A: `DELETE /api/v1/integrations/hub/connections/{B_connection_id}` → 404.
3. As user A: list connections — only A's rows (`organization_id` filter).
4. Webhook URL for B's connection must not mutate A's data (UUID path is the boundary; optional: forge event with wrong `organization_id` → `dead_letter` / `workspace_mismatch`).

## 5. Full product cycles (manual)

### Bitrix24
1. Mass-market app in partners.bitrix24.com with canonical redirect_uri.
2. Card → Подключить → OAuth popup → status `connected`, metadata shows portal.
3. Inbound CRM webhook → event `processed`.
4. Agent creates contact/deal via hub queue.
5. Отключить → status `revoked` (or disconnected), tokens cleared.

### amoCRM
1. Same OAuth popup with subdomain.
2. Concurrent refresh: two workers refresh same connection — only one token write (advisory lock).
3. Disconnect/revoke path as above.

### Wazzup
1. API key → testConnection → save.
2. Webhook registered after connect.
3. Inbound customer message → agent reply (no self-echo on outbound).
4. Disconnect clears connection.

## Exit criteria

- [ ] Redirect URIs verified in both partner cabinets
- [ ] Lock TTL survives worker kill
- [ ] Poison webhook lands in `dead_letter`, not infinite retry
- [ ] Hub traffic visible in `usage_events`
- [ ] Cross-tenant connection id returns 404
- [ ] Connect → traffic → disconnect works for Bitrix24, amoCRM, Wazzup
