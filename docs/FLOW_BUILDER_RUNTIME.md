# Flow Builder + Execution Runtime

## Architecture

```
Frontend /flow-builder?botId=
  React Flow + Zustand (localStorage persist) + backend sync
       │ save/publish          │ Preview pane
       ▼                       ▼
  GET/POST /bots/{id}/flow   WS /api/v1/sandbox/{botId}
  POST /bots/{id}/publish    POST /bots/{id}/execute
                             WS /api/v1/ws/execution/{session_id}
       │
       ▼
  BotFlow (live) + BotFlowRevision / BotFlowVersion (snapshots)
       │
       ▼
  FlowExecutionService → FlowExecutor (flow_parser)
       ├─ LLM / RAG / Condition / Loop / API / CRM / HumanHandoff
       ├─ AIGuardrailsService (inbound)
       └─ UsageEvent (MESSAGE_IN / MESSAGE_OUT) → AnalyticsService
```

## Frontend layout

```
frontend/src/
├── app/flow-builder/page.tsx          # Full builder: palette + canvas + properties + preview
├── components/flow/
│   ├── nodes/                         # LLM, RAG, Condition, Loop, WhatsApp, APICall, CRM, Handoff…
│   ├── PropertiesPanel.tsx
│   ├── FlowPreviewPane.tsx            # Sandbox WS preview
│   └── TopControlBar.tsx              # Save / Publish / Auto-layout / Export JSON / Test
├── store/useFlowStore.ts              # Zustand + persist(localStorage) + API sync
├── lib/flowAutoLayout.ts              # Layered auto-layout (dagre-style)
└── types/flow.ts                      # NodeType, CustomNode, CustomEdge, FlowData
```

## Node library

| Canvas | Backend type | Notes |
|--------|--------------|-------|
| Trigger | `trigger` | Entry |
| Text / WhatsApp | `text_message` | Outbound (+ channel meta) |
| Condition | `condition` | true/false handles |
| Loop | `loop` | body/exit + max_iterations |
| RAG | `knowledge_search` | → `{{rag_context}}` |
| LLM | `ai_agent` | tool/prompt variables |
| API Call | `api_request` | success/failure |
| CRM Action | `crm_action` | amoCRM / Bitrix / webhook |
| Human Handoff | `human_handoff` | pause bot for operator |

## Preview ↔ execution

1. **Preview pane:** sandbox WS `getSandboxWsUrl(botId)` — published graph + execution trace.
2. **HTTP execute:** `POST /api/v1/bots/{id}/execute`  
   ```json
   { "message": "hi", "session_id": null, "use_draft": false }
   ```
3. **Streaming WS:** `getExecutionWsUrl(sessionId)`  
   send `{ "type":"message", "bot_id":"…", "text":"…" }`  
   receive `start → node_enter* → message → done | error`.

## Versioning

- Publish → `BotFlowRevision` snapshot (`BotFlowVersion` alias).
- List: `GET /api/v1/bots/{id}/flow/revisions`
- Rollback: `POST /api/v1/bots/{id}/flow/revisions/{version}/rollback`

## Backend services

| Service | Path |
|---------|------|
| FlowExecutionService | `backend/app/services/flow_execution_service.py` |
| FlowExecutor | `backend/app/services/flow_parser.py` |
| RAGService | `backend/app/services/rag_service.py` |
| AnalyticsService | `backend/app/services/analytics_service.py` |
| Versioning | `flow_version_service.py` |

## Load test (Locust)

```bash
cd backend
export MPAI_BASE_URL=http://localhost:8000
export MPAI_TOKEN=<jwt>
export MPAI_BOT_ID=<uuid>
locust -f locustfile.py --host=$MPAI_BASE_URL
```

## Smoke test

```bash
cd backend && uvicorn main:app --reload

curl -s -X POST http://localhost:8000/api/v1/auth/login/json \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@mp.ai","password":"ChangeMeNow!"}'

curl -s -X POST http://localhost:8000/api/v1/bots/<BOT_ID>/execute \
  -H "Authorization: Bearer <TOKEN>" \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello","use_draft":true}'
```

## Playwright

```bash
cd frontend
npx playwright test e2e/saas-v1-flow.spec.ts          # CI-friendly mocked API
npm run test:e2e:stress                               # full omniproduct (live stack)
npx playwright test e2e/omniproduct-stress.spec.ts --ui
```

Manual builder check:

1. Open `/flow-builder?botId=<uuid>`
2. Drag Loop + Human Handoff from palette
3. Auto layout → Save → Publish
4. Send a message in Preview pane
5. Export JSON from toolbar
