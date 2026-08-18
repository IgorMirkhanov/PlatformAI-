# Getting started — MP.AI

## What you need

- Staging/production URL from your admin, **or** local:
  - Backend: `http://localhost:8000`
  - Frontend: `http://localhost:3000`
- An account (register) or bootstrap superadmin (`admin@mp.ai` — **change immediately**)

## 5-minute path

1. Open the app → **Register** (or Login).
2. Confirm your organization name (default workspace is created automatically).
3. Create an agent / bot from the sidebar.
4. Open **Flow Builder** (`/flow-builder?botId=…`).
5. Connect Trigger → Text / LLM → Publish.
6. Use **Preview** to send a test message (sandbox WebSocket).
7. Connect Telegram or WhatsApp under Channels.

## Auth tips

- Access tokens are JWT; refresh tokens rotate via `POST /api/v1/auth/refresh`.
- Multi-org: send `X-Tenant-ID: <organization uuid>` or use the workspace switcher.
- Password reset: `POST /api/v1/auth/forgot-password` (email is stubbed to logs in v1).

## Next

- [Create your first bot](./creating-first-bot.md)
- [Flow builder & execution](../FLOW_BUILDER_RUNTIME.md)
- [Production launch checklist](../PRODUCTION_LAUNCH_CHECKLIST.md)
