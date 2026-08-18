# MP.AI architecture — SaaS v1 (C4)

## Level 1 — System Context

```mermaid
C4Context
title MP.AI System Context
Person(owner, "Workspace Owner", "Configures bots, billing, team")
Person(operator, "Operator", "Inbox / human handoff")
Person(enduser, "End User", "Telegram / WhatsApp")
System(mpai, "MP.AI Platform", "Multi-tenant AI bot SaaS")
System_Ext(stripe, "Stripe")
System_Ext(openai, "OpenAI / Ollama")
System_Ext(tg, "Telegram Bot API")
System_Ext(wa, "WhatsApp")
Rel(owner, mpai, "HTTPS / JWT")
Rel(operator, mpai, "HTTPS / WS")
Rel(enduser, tg, "Messages")
Rel(enduser, wa, "Messages")
Rel(mpai, tg, "Webhooks / send")
Rel(mpai, wa, "QR microservice / Cloud API")
Rel(mpai, openai, "LLM + embeddings")
Rel(mpai, stripe, "Subscriptions + meters")
```

## Level 2 — Containers

```mermaid
C4Container
title MP.AI Containers
Person(owner, "Owner")
System_Boundary(mpai, "MP.AI") {
  Container(fe, "frontend_app", "Next.js 14", "Dashboard, Flow Builder, Inbox")
  Container(api, "backend_api", "FastAPI", "Auth, tenancy, bots, execute, billing")
  Container(worker, "celery_worker", "Celery", "Inbound, CRM, RAG ingest")
  Container(wa, "whatsapp_service", "Node/Baileys", "QR sessions, send/receive")
  ContainerDb(pg, "postgres", "PostgreSQL 16", "System of record")
  ContainerDb(rd, "redis", "Redis 7", "Broker + caches")
  ContainerDb(ch, "chromadb", "Chroma", "Per-bot vectors")
  Container(nginx, "nginx", "Nginx", "TLS, rate limit, WS upgrade")
}
Rel(owner, nginx, "HTTPS")
Rel(nginx, fe, "proxy")
Rel(nginx, api, "proxy /api")
Rel(nginx, wa, "proxy /whatsapp /ws/qr")
Rel(api, pg, "SQL")
Rel(api, rd, "cache / pubsub")
Rel(api, ch, "embeddings search")
Rel(api, worker, "enqueue")
Rel(worker, pg, "SQL")
Rel(worker, rd, "broker")
Rel(api, wa, "HTTP send / status")
```

## Level 3 — Backend components (API)

```mermaid
C4Component
title backend_api components
Container_Boundary(api, "backend_api") {
  Component(auth, "Auth routers", "JWT / refresh / OAuth stubs")
  Component(tenant, "TenantMiddleware + deps", "X-Tenant-ID / JWT company_id")
  Component(bots, "Bot management", "CRUD + flow save/publish")
  Component(exec, "FlowExecutionService", "DFS walk + stream events")
  Component(rag, "RAGService", "Ingest + search")
  Component(guard, "AIGuardrailsService", "Injection / moderation")
  Component(bill, "Stripe + UsageService", "Checkout / UsageEvent")
  Component(analytics, "AnalyticsService", "Org meters")
}
Rel(auth, tenant, "scopes requests")
Rel(bots, exec, "publish → cache")
Rel(exec, rag, "knowledge_search nodes")
Rel(exec, guard, "inbound text")
Rel(exec, bill, "record MESSAGE_*")
Rel(bill, analytics, "aggregates")
```

## Domain model

```
User ──< UserCompanyWorkspace >── Organization (companies)
  │                                    └──< Project ──< Bot
  │                                                      ├── BotFlow (live graph)
  │                                                      ├── BotFlowRevision / BotFlowVersion
  │                                                      └── Integration / KnowledgeBase
  └── Subscription ──< BillingTransaction
                   └── UsageEvent
```

`bots.credentials` secrets are sealed at rest via `CREDENTIALS_ENCRYPTION_KEY`
(`aesgcm:` / legacy `enc:`). See also [`architecture_db.md.txt`](../architecture_db.md.txt)
(redirect + ER summary; do not use the old single-tenant draft).

## Request path (inbound message)

1. Messenger webhook → Celery inbound queue  
2. Quota / balance check  
3. `AIGuardrailsService.check_text`  
4. `FlowExecutor` / `FlowExecutionService` traversal  
5. `UsageService.record_and_debit`  
6. Outbound send + Prometheus counters  

## OpenAPI

- Interactive: `/docs` (Swagger)  
- Alternative: `/redoc`  
- Execute example: `POST /api/v1/bots/{bot_id}/execute` with `{ "message": "hello" }`  
- Auth example: `POST /api/v1/auth/login/json` → `access_token` + `refresh_token`
