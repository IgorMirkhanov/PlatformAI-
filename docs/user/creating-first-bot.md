# Creating your first bot

## 1. Create the agent

1. In the dashboard sidebar, choose **Create agent**.
2. Set name, timezone, and default LLM model.
3. Note the `botId` (UUID) — you will use it in Flow Builder and webhooks.

## 2. Build a minimal flow

1. Open `/flow-builder?botId=<uuid>`.
2. Drag **Trigger** (message received).
3. Add **RAG** (optional) → **LLM** with a system prompt.
4. Optionally add **Human Handoff** for operator takeover.
5. Click **Auto layout**, then **Save Flow**, then **Publish**.

Publish stores a `BotFlowRevision` snapshot (rollback from Flow versions API / UI when enabled).

## 3. Test in Preview

1. Open the Preview pane in the builder.
2. Send `hello` — you should see a bot reply and a node trace.
3. For API testing:

```bash
curl -X POST "$API/api/v1/bots/$BOT_ID/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","use_draft":false}'
```

## 4. Connect a channel

### Telegram
1. Create a bot with BotFather → copy token.
2. Paste token in Channels → Telegram → Connect.
3. Ensure `WEBHOOK_BASE_URL` is public HTTPS.

### WhatsApp (QR)
1. Start WhatsApp service (compose includes `whatsapp_service`).
2. Open Channels → WhatsApp → scan QR.
3. Sessions persist in `mpai_whatsapp_sessions`.

## 5. Knowledge base (RAG)

1. Upload PDF/Docx under Knowledge.
2. In the flow, place a **RAG** node before **LLM** and reference `{{rag_context}}`.
3. Collections are bot-scoped (`bot_{botId}`) with `organization_id` metadata.

## 6. Go live checklist (bot-level)

- [ ] Published flow has a Trigger and reachable reply node
- [ ] Preview OK
- [ ] Channel connected + inbound test message
- [ ] Guardrails not blocking legitimate traffic
- [ ] Usage events appear under Billing / Analytics
