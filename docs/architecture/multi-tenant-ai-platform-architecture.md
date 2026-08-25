# Архитектурная спецификация: Multi-Tenant AI Platform (BYOK)

**Роль документа:** технический дизайн платформы уровня MoonAI/Salesbot — agnostic AI-оркестрация, мульти-канальные мессенджеры, CRM-автоматизация, BYOK-модель хранения ключей.

**Ключевой принцип:** платформа — это среда исполнения (routing, orchestration, encryption, persistence). Все "боевые" credentials принадлежат клиенту (tenant) и хранятся зашифрованными на его стороне записи. Платформенные `.env`-ключи — только fallback/системный шлюз (OAuth app-level secrets, дефолтная LLM-модель для аварийного отката).

---

## 1. Архитектурный дизайн

### 1.1 Модель предметной области (сущности верхнего уровня)

```
Organization (tenant)
 ├── Users (роли: owner/admin/operator)
 ├── Credentials (зашифрованные ключи любого провайдера)
 ├── Bots (логическая единица "ассистент")
 │     ├── BotChannels (привязка бота к мессенджеру)
 │     ├── BotAIConfig (какая модель, температура, RAG-коллекция)
 │     └── BotCRMLink (привязка бота к CRM-интеграции)
 ├── Integrations (CRM/LLM/каналы — статус подключения, метаданные OAuth)
 ├── Conversations
 │     └── Messages
 ├── Deals (проекция сделки в локальной БД, синхронная с CRM)
 └── AuditLog / WebhookEventLog
```

### 1.2 Схема БД (PostgreSQL, DDL уровня спецификации)

```sql
-- ============================================================
-- 1. ORGANIZATIONS — корень мультитенантности
-- ============================================================
CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) UNIQUE NOT NULL,
    plan_tier       VARCHAR(50) NOT NULL DEFAULT 'free',
    status          VARCHAR(20) NOT NULL DEFAULT 'active', -- active|suspended|deleted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. CREDENTIALS — универсальное зашифрованное хранилище ключей
--    (единая таблица для LLM-провайдеров, мессенджеров, CRM)
-- ============================================================
CREATE TYPE credential_kind AS ENUM (
    'llm_openai', 'llm_deepseek', 'llm_anthropic', 'llm_groq',
    'llm_openrouter', 'llm_gemini',
    'channel_telegram', 'channel_wazzup', 'channel_greenapi', 'channel_widget',
    'crm_amocrm', 'crm_bitrix24'
);

CREATE TABLE credentials (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind                credential_kind NOT NULL,
    label               VARCHAR(255),                 -- "Основной OpenAI ключ отдела продаж"
    encrypted_payload   BYTEA NOT NULL,                -- AES-256-GCM ciphertext (JSON внутри)
    encryption_iv       BYTEA NOT NULL,                -- nonce, 12 байт
    encryption_tag      BYTEA NOT NULL,                -- GCM auth tag
    key_version         SMALLINT NOT NULL DEFAULT 1,   -- версия KEK для ротации мастер-ключа
    -- OAuth-специфичные поля (amoCRM/Bitrix24), тоже зашифрованы отдельно как payload,
    -- но метаданные храним открыто для планирования refresh:
    oauth_expires_at    TIMESTAMPTZ,                   -- когда access_token истекает
    oauth_refresh_locked_until TIMESTAMPTZ,             -- advisory-lock TTL для воркера
    status              VARCHAR(20) NOT NULL DEFAULT 'active', -- active|expired|revoked|error
    last_validated_at   TIMESTAMPTZ,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, kind, label)
);

CREATE INDEX idx_credentials_oauth_refresh
    ON credentials (oauth_expires_at)
    WHERE kind IN ('crm_amocrm', 'crm_bitrix24') AND status = 'active';

-- ============================================================
-- 3. INTEGRATIONS — статус/конфигурация "подключения" сервиса
--    (1 запись = 1 живая интеграция; ссылается на credentials)
-- ============================================================
CREATE TABLE integrations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    credential_id       UUID REFERENCES credentials(id) ON DELETE SET NULL,
    provider            credential_kind NOT NULL,
    external_account_id VARCHAR(255),      -- amoCRM subdomain / Bitrix portal / Wazzup channel_id
    config_json         JSONB NOT NULL DEFAULT '{}', -- provider-specific non-secret settings
    is_fallback_allowed BOOLEAN NOT NULL DEFAULT true, -- разрешён ли откат на платформенный ключ
    status              VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending|active|degraded|failed
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 4. BOTS — логическая единица ассистента внутри организации
-- ============================================================
CREATE TABLE bots (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    system_prompt       TEXT,
    ai_integration_id   UUID REFERENCES integrations(id), -- какой LLM-провайдер использовать
    model_name          VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini',
    fallback_model_name VARCHAR(100),                    -- ядро для деградации по таймауту
    rag_collection_id   VARCHAR(255),                    -- ChromaDB collection name
    crm_integration_id  UUID REFERENCES integrations(id),
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 5. BOT_CHANNELS — привязка бота к конкретному мессенджеру
--    Это ключевая таблица для резолва вебхуков.
-- ============================================================
CREATE TYPE channel_type AS ENUM ('telegram', 'wazzup', 'greenapi', 'widget');

CREATE TABLE bot_channels (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id              UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    channel_type        channel_type NOT NULL,
    credential_id       UUID NOT NULL REFERENCES credentials(id),
    -- reference_id — ЕДИНСТВЕННЫЙ источник истины для роутинга входящих вебхуков.
    -- Для Telegram: bot_id из getMe (числовой ID токена).
    -- Для Wazzup: channelId (UUID канала WhatsApp/Instagram).
    -- Для GreenAPI: idInstance.
    -- Для Widget: сгенерированный platform-side widget_key.
    reference_id        VARCHAR(255) NOT NULL,
    webhook_secret       VARCHAR(255) NOT NULL, -- HMAC-подпись для верификации входящих запросов
    status               VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel_type, reference_id)  -- глобальная уникальность для резолва без org_id в URL
);

CREATE INDEX idx_bot_channels_reference ON bot_channels (channel_type, reference_id);

-- ============================================================
-- 6. CONVERSATIONS / MESSAGES
-- ============================================================
CREATE TABLE conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_channel_id       UUID NOT NULL REFERENCES bot_channels(id),
    external_chat_id     VARCHAR(255) NOT NULL, -- chat_id в Telegram / clientId в Wazzup
    linked_client_id      UUID,                  -- ссылка на deals.client_id после первого маппинга
    status                VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bot_channel_id, external_chat_id)
);

CREATE TABLE messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    external_message_id   VARCHAR(255),          -- для идемпотентности
    direction              VARCHAR(10) NOT NULL,  -- in|out
    role                    VARCHAR(20) NOT NULL,  -- user|assistant|system
    content                 TEXT NOT NULL,
    tokens_used             INT,
    model_used               VARCHAR(100),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, external_message_id)
);

-- ============================================================
-- 7. DEALS — локальная проекция сделки/контакта CRM
-- ============================================================
CREATE TABLE deals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id       UUID REFERENCES conversations(id),
    crm_integration_id     UUID NOT NULL REFERENCES integrations(id),
    external_contact_id     VARCHAR(255),
    external_lead_id         VARCHAR(255),
    dedup_key                 VARCHAR(255) NOT NULL, -- hash(org_id + channel + external_chat_id)
    status                     VARCHAR(20) NOT NULL DEFAULT 'created',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, dedup_key)
);

-- ============================================================
-- 8. WEBHOOK_EVENT_LOG — идемпотентность + аудит + троттлинг Redis-lock backstop
-- ============================================================
CREATE TABLE webhook_event_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider              channel_type NOT NULL,
    reference_id           VARCHAR(255) NOT NULL,
    external_message_id     VARCHAR(255) NOT NULL,
    payload_hash              VARCHAR(64) NOT NULL,
    processed_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, reference_id, external_message_id)
);
```

**Замечания по дизайну:**

- `credentials` — единая таблица-хранилище для *любого* секрета (LLM/мессенджер/CRM). Это упрощает ротацию мастер-ключа (KEK) и аудит: один код-путь шифрования/расшифровки для всех типов.
- `bot_channels.reference_id` глобально уникален по `(channel_type, reference_id)` — именно это поле резолвит входящий вебхук **без** передачи `organization_id` в URL (см. раздел 3).
- `is_fallback_allowed` в `integrations` — явный флаг, разрешает ли клиент откатываться на платформенный ключ (важно для биллинга: если используется platform-key, нужно списывать токены с баланса клиента платформы, а не провайдера).
- `dedup_key` в `deals` — детерминированный хэш, который гарантирует, что параллельные сообщения от одного и того же внешнего клиента не создадут два лида (см. раздел 3.4).

---

## 2. Матрица зависимостей подключений

Разделение критично для UX и security review: часть параметров — статические, платформенные, задаются один раз в инфраструктуре; часть — вводятся каждым клиентом в UI как его личные credentials.

### 2.1 LLM-провайдеры

| Провайдер | Настраивает Платформа (.env / инфра) | Вводит Клиент в UI |
|---|---|---|
| OpenAI | `PLATFORM_OPENAI_FALLBACK_KEY` (для деградации), список разрешённых моделей | `api_key` (sk-...), опционально `organization_id`, выбор модели из allowlist |
| DeepSeek | `PLATFORM_DEEPSEEK_FALLBACK_KEY` | `api_key`, base_url (обычно фиксирован) |
| Anthropic (Claude) | `PLATFORM_ANTHROPIC_FALLBACK_KEY` | `api_key` (sk-ant-...), выбор модели |
| Groq | `PLATFORM_GROQ_FALLBACK_KEY` (используется как fast-fallback ядро по умолчанию для всех тенантов) | `api_key` (опционально — можно использовать платформенный) |
| OpenRouter | — (обычно нет платформенного fallback, т.к. это агрегатор) | `api_key`, `model_slug` (например `anthropic/claude-sonnet-4.5`) |
| Google Gemini | `PLATFORM_GEMINI_FALLBACK_KEY` | `api_key`, `project_id` (если Vertex AI режим) |

### 2.2 Мессенджеры

| Канал | Настраивает Платформа | Вводит Клиент в UI |
|---|---|---|
| **Telegram** (Тип A) | `WEBHOOK_BASE_URL` (публичный домен платформы), общий rate-limit прокси | `bot_token` (получен у @BotFather). Платформа сама вызывает `setWebhook(https://{base}/api/v1/webhooks/telegram)` и валидирует токен через `getMe` |
| **Wazzup** (Тип B) | `WAZZUP_PARTNER_API_KEY` (если платформа — партнёр Wazzup с white-label доступом), приёмный webhook endpoint | `api_key` организации в Wazzup, список `channel_id` (номера WhatsApp/Instagram), URL коллбэка регистрируется автоматически при сохранении ключа |
| **GreenAPI** (Тип C) | Базовый URL API (`api.green-api.com`), опционально партнёрский `PARTNER_TOKEN` | `id_instance`, `api_token_instance` — данные конкретного WhatsApp-инстанса клиента |
| **Widget** (Тип D) | Домен для встраиваемого JS-скрипта (`widget.platform.com/embed.js`), CORS allowlist policy | Ничего не вводит — платформа генерирует `widget_key` и код `<script>` для вставки на сайт клиента |

### 2.3 CRM

| CRM | Настраивает Платформа | Вводит Клиент в UI |
|---|---|---|
| **amoCRM** | Публичная интеграция: `AMOCRM_CLIENT_ID`, `AMOCRM_CLIENT_SECRET`, `AMOCRM_REDIRECT_URI` (зарегистрированы в кабинете разработчика amoCRM) | Нажимает "Подключить amoCRM" → OAuth-редирект на `{subdomain}.amocrm.ru` → платформа получает и шифрует `access_token`/`refresh_token`; клиент вводит только свой поддомен перед редиректом |
| **Битрикс24** | Для тиражируемого приложения: `BITRIX_APP_ID`, `BITRIX_APP_SECRET` (реестр Bitrix Marketplace). Для локальных вебхуков — ничего | Вариант 1 (Marketplace): OAuth-установка одним кликом из портала Bitrix. Вариант 2 (локальный вебхук): клиент сам создаёт исходящий/входящий вебхук в своём портале и вставляет `webhook_url` в UI платформы |

### 2.4 Итоговое правило

> Платформа **никогда** не хранит "боевые" ключи клиентов в `.env` — только OAuth app-credentials (client_id/secret) и fallback-ключи, используемые с явного согласия клиента (`is_fallback_allowed = true`) и, как правило, с ограничением по лимиту/биллингу.

---

## 3. Спецификация Webhook Routing & Execution Pipeline

Путь от входящего сообщения клиента до сохранённой сделки и ответа ИИ.

### 3.1 Точка входа

```
POST /api/v1/webhooks/{provider}
```
`{provider}` ∈ `telegram | wazzup | greenapi | widget`. **Организация НЕ определяется по URL** — только по содержимому payload.

### 3.2 Пошаговый пайплайн

1. **Приём запроса (Webhook Receiver, stateless).**
   Верифицируется подпись (HMAC/секрет из `bot_channels.webhook_secret`, или Telegram `X-Telegram-Bot-Api-Secret-Token`). Невалидная подпись → `403`, без записи в БД.

2. **Извлечение `reference_id`.**
   - Telegram: `payload.message.chat.id` привязывается через `bot.id`, извлекаемый из URL secret token, либо через заранее сохранённый `bot_token`-hash.
   - Wazzup: `payload.channelId`.
   - GreenAPI: `payload.instanceData.idInstance`.
   - Widget: `payload.widget_key`.

3. **Резолв канала.**
   ```sql
   SELECT bc.*, b.organization_id
   FROM bot_channels bc
   JOIN bots b ON b.id = bc.bot_id
   WHERE bc.channel_type = :provider AND bc.reference_id = :reference_id
     AND bc.status = 'active';
   ```
   Не найдено → `404` + запись в `webhook_event_log` со статусом `unmatched` для последующего дебага.

4. **Идемпотентность (Redis distributed lock).**
   ```
   key = f"webhook_lock:{provider}:{reference_id}:{external_message_id}"
   SET key "1" NX PX 30000
   ```
   Если `SET NX` вернул `false` → событие уже обрабатывается/обработано → `200 OK` без побочных эффектов (важно для дублей от нестабильной доставки провайдера). После успешной обработки — `INSERT ... ON CONFLICT DO NOTHING` в `webhook_event_log` как постоянный backstop (Redis TTL не панацея от рестарта воркера).

5. **Резолв/создание Conversation.**
   `UPSERT` по `(bot_channel_id, external_chat_id)`.

6. **AI Orchestration Call (асинхронно, через очередь — не в HTTP request/response цикле).**
   a. Оркестратор берёт `bots.ai_integration_id` → `integrations.credential_id` → `credentials.encrypted_payload` → расшифровка **в памяти воркера**, никогда не логируется и не кэшируется на диск.
   b. Инициализация клиента провайдера (OpenAI/Claude/DeepSeek/...).
   c. Если задан `rag_collection_id` — запрос к ChromaDB; при недоступности — `warning`-лог + продолжение без контекста (graceful degradation).
   d. Вызов модели с таймаутом (например 12с). При превышении — переключение на `fallback_model_name` (быстрое ядро, обычно Groq/DeepSeek).
   e. Если провайдер возвращает `insufficient_quota`/`401` — помечаем `integrations.status = 'degraded'`, шлём уведомление владельцу организации, и если `is_fallback_allowed = true` — повторяем запрос с платформенным fallback-ключом (с флагом `used_platform_fallback = true` в логе для биллинга).

7. **Идемпотентное создание сделки в CRM.**
   ```sql
   INSERT INTO deals (organization_id, conversation_id, crm_integration_id, dedup_key, ...)
   VALUES (..., encode(sha256(org_id || channel_type || external_chat_id), 'hex'), ...)
   ON CONFLICT (organization_id, dedup_key) DO UPDATE SET updated_at = now()
   RETURNING id, (xmax = 0) AS was_inserted;
   ```
   `was_inserted = true` → реально новый лид → вызывается `POST /api/v4/leads` (amoCRM) или `crm.lead.add` (Bitrix). Иначе — сделка уже существует, просто добавляется сообщение в её таймлайн (если CRM это поддерживает).
   Для amoCRM/Bitrix OAuth-запрос выполняется через прокси-слой, который **перед каждым исходящим запросом** проверяет `oauth_expires_at`; если до истечения < 5 мин и лок не занят другим воркером — синхронный refresh на месте (см. 3.3), иначе — используется текущий токен.

8. **Ответ пользователю.**
   Сгенерированный текст отправляется обратно через API канала (Telegram `sendMessage`, Wazzup `sendMessage`, GreenAPI `sendMessage`), сообщение сохраняется в `messages` с `direction='out'`.

9. **HTTP-ответ вебхук-роутеру провайдера** — отдаётся **немедленно** после шага 4 (`200 OK`), не дожидаясь генерации ответа ИИ — это защищает от повторных доставок из-за таймаута на стороне Telegram/Wazzup. Вся тяжёлая обработка (шаги 5–8) — в фоновой задаче (Celery/RQ).

### 3.3 Фоновый воркер обновления OAuth-токенов (amoCRM)

```
Celery beat: каждые 60 секунд
SELECT * FROM credentials
WHERE kind = 'crm_amocrm' AND status = 'active'
  AND oauth_expires_at < now() + interval '5 minutes'
  AND (oauth_refresh_locked_until IS NULL OR oauth_refresh_locked_until < now());

# Advisory lock на уровне БД, защита от гонки двух воркеров:
SELECT pg_try_advisory_lock(hashtext(credential_id::text));
-- если lock получен:
UPDATE credentials SET oauth_refresh_locked_until = now() + interval '2 minutes' WHERE id = :id;
-- выполняем refresh_token запрос к amoCRM
-- при успехе: обновляем encrypted_payload, oauth_expires_at, снимаем lock
-- при ошибке: status = 'error', last_error = ..., уведомление владельцу
SELECT pg_advisory_unlock(hashtext(credential_id::text));
```

### 3.4 Защита от дублирования лидов при параллельных сообщениях

Race condition: клиент присылает 2 сообщения подряд за 200мс → два параллельных воркера могут одновременно создавать сделку.
Решение — комбинация:
1. `dedup_key` с UNIQUE constraint на уровне БД (последняя линия защиты — атомарна на уровне Postgres).
2. `ON CONFLICT DO UPDATE ... RETURNING (xmax = 0)` — определяет, кто "выиграл гонку" и должен реально вызвать CRM API.
3. Redis-lock на уровне `conversation_id` (`SET NX PX 5000`) перед созданием сделки — снижает конкуренцию до момента обращения к БД.

---

## 4. Промпт для Cursor Composer (Ctrl + I)

Готовый промпт для вставки в Cursor Composer — можно использовать целиком как ТЗ на реализацию по шагам.

```
Ты выступаешь как senior backend engineer. Реализуй backend мультитенантной AI-платформы 
на стеке: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Redis, Celery, Pydantic v2.

КОНТЕКСТ АРХИТЕКТУРЫ:
Платформа работает в BYOK-режиме: каждая организация (tenant) хранит свои зашифрованные 
API-ключи LLM-провайдеров, токены мессенджеров и OAuth-креды CRM в единой таблице `credentials` 
(AES-256-GCM шифрование payload в памяти). Платформенные ключи в .env — только fallback.

ВЫПОЛНИ РЕАЛИЗАЦИЮ ПО ШАГАМ, каждый шаг — отдельный коммит с тестами:

ШАГ 1 — Модели данных
- Создай SQLAlchemy 2.0 async-модели по следующей DDL-схеме (вставь схему из раздела 1.2 
  этого документа целиком). Используй declarative mapping с типизированными Mapped[...] 
  аннотациями, UUID PK через `uuid.uuid4`, серверные default через `server_default`.
- Добавь Alembic migration для всех таблиц с корректными индексами и unique-constraints, 
  включая партиционирование `webhook_event_log` по `provider` при необходимости.
- Напиши pytest-фикстуры для каждой модели (factory pattern через `factory_boy`).

ШАГ 2 — Сервис шифрования credentials
- Создай `app/services/crypto_service.py`:
  - `encrypt_payload(plaintext: dict, kek: bytes) -> tuple[bytes, bytes, bytes]` 
    (возвращает ciphertext, iv, tag), используй `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
  - `decrypt_payload(ciphertext, iv, tag, kek) -> dict`.
  - Мастер-ключ (KEK) берётся из переменной окружения `MASTER_ENCRYPTION_KEY`, 
    поддержи версионирование через `key_version` для будущей ротации (KEK per version 
    хранится в `KMS_KEYS = {1: "...", 2: "..."}`).
  - Никогда не логируй расшифрованные значения — добавь кастомный `SecretStr`-wrapper 
    поверх Pydantic, чтобы предотвратить случайное попадание в логи/Sentry.
- Напиши unit-тесты: round-trip шифрование/дешифрование, попытка расшифровки с неверным 
  IV/tag должна кидать `InvalidTag`.

ШАГ 3 — Repository слой для credentials/integrations
- `CredentialsRepository`: CRUD + метод `get_decrypted(organization_id, kind, label=None) -> dict`, 
  который инкапсулирует расшифровку и НЕ должен вызываться вне сервисного слоя AI-оркестратора.
- `IntegrationsRepository`: методы `get_active_for_bot(bot_id)`, `mark_degraded(id, error)`, 
  `mark_active(id)`.

ШАГ 4 — Agnostic AI Provider Engine
- Создай `app/services/ai/base.py` с абстрактным классом `BaseLLMProvider` 
  (методы `async def generate(messages, model, timeout) -> LLMResponse`).
- Реализуй адаптеры: `OpenAIProvider`, `AnthropicProvider`, `DeepSeekProvider`, 
  `GroqProvider`, `OpenRouterProvider`, `GeminiProvider` — каждый в своём файле, 
  используя официальные SDK (`openai`, `anthropic`, `google-genai` и т.д. — 
  для DeepSeek/Groq/OpenRouter используй openai-compatible client с другим base_url).
- Создай `AIOrchestrator` сервис:
  - принимает `bot_id`, `messages`;
  - резолвит integration → расшифровывает ключ → инициализирует провайдер;
  - оборачивает вызов в `asyncio.wait_for(timeout=...)`;
  - при `TimeoutError` — retry на `fallback_model_name`;
  - при auth/quota ошибке от провайдера — если `is_fallback_allowed`, retry на 
    платформенном ключе из `.env`, помечает `used_platform_fallback=True` в ответе 
    для последующего биллинга;
  - при недоступности ChromaDB (RAG) — ловит исключение, логирует warning, 
    продолжает без контекста.
- Напиши unit-тесты с моками провайдеров (respx для httpx-based клиентов) на каждый 
  сценарий деградации отдельно.

ШАГ 5 — Webhook Router
- `app/api/v1/webhooks.py`: единый endpoint `POST /api/v1/webhooks/{provider}`.
- Для каждого provider — свой парсер payload → извлечение `reference_id` и 
  `external_message_id` (создай `app/services/webhooks/parsers/{telegram,wazzup,greenapi,widget}.py`).
- Верификация подписи запроса (HMAC для Wazzup/GreenAPI, `X-Telegram-Bot-Api-Secret-Token` 
  для Telegram) — до любого обращения к БД.
- Резолв `bot_channels` по `(channel_type, reference_id)`.
- Redis distributed lock (`redis.set(key, "1", nx=True, px=30000)`) для идемпотентности, 
  плюс постоянная запись в `webhook_event_log` с `ON CONFLICT DO NOTHING`.
- Постановка задачи в Celery (`process_incoming_message.delay(...)`) и немедленный 
  возврат `200 OK`.
- Интеграционные тесты: дублирующийся `external_message_id` не должен создавать 
  вторую запись `Conversation`/`Message`.

ШАГ 6 — Celery task: обработка сообщения → AI → CRM
- `app/tasks/process_message.py`:
  - upsert Conversation;
  - вызов `AIOrchestrator.generate(...)`;
  - идемпотентное создание/обновление Deal через `dedup_key` 
    (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING (xmax = 0) AS was_inserted`);
  - если `was_inserted` — вызов CRM-адаптера (`AmoCRMAdapter.create_lead` / 
    `Bitrix24Adapter.create_lead`);
  - отправка ответа обратно в канал через `ChannelSenderFactory.get(channel_type).send(...)`.
- Напиши тест на race condition: две параллельные Celery-таски с одинаковым 
  `dedup_key` должны создать ровно один Deal (используй pytest-asyncio + 
  реальную тестовую БД, не моки, для проверки UNIQUE constraint).

ШАГ 7 — OAuth refresh worker (amoCRM/Bitrix24)
- Celery beat task каждые 60 секунд, выбирающая credentials с `oauth_expires_at < now() + 5min`.
- PostgreSQL advisory lock (`pg_try_advisory_lock(hashtext(credential_id))`) вокруг 
  refresh-запроса — не Redis-lock, именно DB-level advisory lock, чтобы переживать 
  рестарт воркера без "залипших" локов.
- Тест: два параллельных вызова таски для одного и того же credential_id — 
  refresh-запрос к amoCRM должен произойти ровно один раз (мокни внешний HTTP-вызов 
  и проверь call count).

ШАГ 8 — CRM Adapters
- `AmoCRMAdapter`: OAuth authorize URL builder, exchange code, `create_lead`, `find_contact_by_phone`.
- `Bitrix24Adapter`: поддержка обоих режимов — local webhook (просто HTTP POST с токеном 
  в URL) и OAuth-приложение (Marketplace).
- Оба адаптера реализуют общий интерфейс `BaseCRMAdapter` для унификации вызова 
  из Celery-таски.

ШАГ 9 — Наблюдаемость
- Structured logging (JSON, через `structlog`) на каждом шаге пайплайна с 
  `organization_id`, `bot_id`, `conversation_id`, но БЕЗ секретов и БЕЗ содержимого 
  сообщений пользователя (только метаданные — длина, модель, latency).
- Prometheus-метрики: `ai_provider_latency_seconds{provider,model}`, 
  `webhook_events_total{provider,status}`, `crm_lead_create_total{crm,result}`, 
  `oauth_refresh_total{crm,result}`.

Для каждого шага: сгенерируй код, затем сгенерируй тесты, затем кратко объясни, 
какие security-инварианты этот код обеспечивает (особенно для шагов 2, 3, 5, 6, 7).
Не переходи к следующему шагу, пока текущий не покрыт тестами.
```

---

### Итог

Документ покрывает: доменную модель и DDL, разграничение platform-level / user-level конфигурации по каждому провайдеру, полный путь обработки входящего события с гарантиями идемпотентности и graceful degradation, и исполняемый пошаговый промпт для автоматизированной реализации в Cursor.
