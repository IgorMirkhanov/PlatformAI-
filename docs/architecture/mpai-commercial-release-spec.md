# MP.AI — Commercial Release Specification Document
**Мастер-план вывода в релиз за 24–48 часов**

Стек: FastAPI (Python 3.11) · Next.js (TS) · PostgreSQL/SQLAlchemy/Alembic · Redis · ChromaDB · Celery · Docker Compose · Nginx.
Точка отсчёта: существующая кодовая база с миграциями до `056_byok_credentials_vault`.

---

## 1. Архитектура кошельков и изоляции балансов

### 1.1 Принцип

Баланс — свойство `Organization`, не `Bot` и не `User`. Списание атомарно, блокировка при исчерпании средств действует **строго в границах одной организации** — ни одна операция над кошельком компании А не должна брать блокировку, видимую компании Б.

### 1.2 Схема БД

```sql
-- ============================================================
-- ORGANIZATION_WALLETS — 1:1 с organizations
-- ============================================================
CREATE TABLE organization_wallets (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    balance_tokens          BIGINT NOT NULL DEFAULT 0 CHECK (balance_tokens >= 0),
    balance_currency_cents  BIGINT NOT NULL DEFAULT 0 CHECK (balance_currency_cents >= 0), -- если биллинг в деньгах, а не токенах
    currency                VARCHAR(3) NOT NULL DEFAULT 'USD',
    low_balance_threshold   BIGINT NOT NULL DEFAULT 1000,   -- порог для warning-уведомления
    status                  VARCHAR(20) NOT NULL DEFAULT 'active', -- active|blocked|grace_period
    blocked_at              TIMESTAMPTZ,
    grace_period_until      TIMESTAMPTZ,     -- отсрочка перед жёсткой блокировкой (опционально)
    version                 INT NOT NULL DEFAULT 0,  -- optimistic-lock счётчик (доп. защита поверх FOR UPDATE)
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- WALLET_TRANSACTIONS — неизменяемый журнал (ledger), source of truth
-- Баланс в organization_wallets — денормализованный кэш, восстанавливаемый из ledger.
-- ============================================================
CREATE TYPE wallet_tx_type AS ENUM ('debit_ai_usage', 'credit_topup', 'credit_refund', 'debit_adjustment', 'credit_adjustment');

CREATE TABLE wallet_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    wallet_id              UUID NOT NULL REFERENCES organization_wallets(id),
    bot_id                  UUID REFERENCES bots(id),           -- какой бот потратил (для аналитики per-bot)
    conversation_id          UUID REFERENCES conversations(id),
    tx_type                   wallet_tx_type NOT NULL,
    amount_tokens              BIGINT NOT NULL,                  -- всегда положительное число, знак определяется tx_type
    balance_after               BIGINT NOT NULL,                 -- снапшот баланса после операции (для аудита без пересчёта)
    model_used                    VARCHAR(100),
    idempotency_key                 VARCHAR(255) NOT NULL,       -- защита от двойного списания при retry
    metadata_json                    JSONB NOT NULL DEFAULT '{}',
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, idempotency_key)
);

CREATE INDEX idx_wallet_tx_org_created ON wallet_transactions (organization_id, created_at DESC);
CREATE INDEX idx_wallet_tx_bot ON wallet_transactions (bot_id, created_at DESC);
```

### 1.3 Атомарное списание (транзакционный SQL)

Ключевое требование: `FOR UPDATE` берётся **только на строку кошелька конкретной организации** — Postgres row-level lock физически не может заблокировать строку другой организации, поэтому "zero cross-tenant impact" гарантируется на уровне СУБД, а не только на уровне логики приложения.

```sql
BEGIN;

-- Блокируем ТОЛЬКО строку кошелька этой организации
SELECT id, balance_tokens, status
FROM organization_wallets
WHERE organization_id = :org_id
FOR UPDATE;

-- Приложение в Python проверяет:
--   status != 'active' OR balance_tokens < :required_tokens  -> ROLLBACK, вернуть "insufficient_balance"

INSERT INTO wallet_transactions (
    organization_id, wallet_id, bot_id, conversation_id, tx_type,
    amount_tokens, balance_after, model_used, idempotency_key
) VALUES (
    :org_id, :wallet_id, :bot_id, :conversation_id, 'debit_ai_usage',
    :tokens_spent, :balance_tokens - :tokens_spent, :model_used, :idempotency_key
)
ON CONFLICT (organization_id, idempotency_key) DO NOTHING
RETURNING id;
-- если RETURNING пусто -> это retry уже обработанной операции, не списываем повторно

UPDATE organization_wallets
SET balance_tokens = balance_tokens - :tokens_spent,
    version = version + 1,
    updated_at = now(),
    status = CASE WHEN balance_tokens - :tokens_spent <= 0 THEN 'blocked' ELSE status END,
    blocked_at = CASE WHEN balance_tokens - :tokens_spent <= 0 THEN now() ELSE blocked_at END
WHERE organization_id = :org_id;

COMMIT;
```

**Важно:** списание выполняется **после** успешного ответа от LLM-провайдера (по факту потраченных `tokens_used` из ответа API), а не до вызова — при неудачном вызове (timeout/ошибка провайдера) деньги не списываются. Если нужен pre-check баланса до дорогого вызова — делается дешёвая read-only проверка `SELECT balance_tokens FROM organization_wallets WHERE organization_id = :id` **без** `FOR UPDATE` (не блокирующая, race допустим — финальная точность гарантируется атомарным списанием выше).

### 1.4 Логика блокировки в `ai_orchestrator`

```
def check_wallet_before_generation(org_id) -> WalletCheckResult:
    wallet = wallet_repo.get_by_org(org_id)  # обычный SELECT, без лока
    if wallet.status == 'blocked':
        return WalletCheckResult(allowed=False, reason='balance_exhausted')
    if wallet.balance_tokens < MIN_TOKENS_RESERVE:
        return WalletCheckResult(allowed=False, reason='balance_exhausted')
    return WalletCheckResult(allowed=True)
```
При `allowed=False` — оркестратор **не вызывает** LLM-провайдера вообще (экономия и защита от отрицательного баланса), отправляет клиенту дефолтное вежливое сообщение (настраиваемое в `bots.low_balance_message`), пишет событие в `wallet_transactions`-адъяcent лог для owner-уведомления (email/Telegram-алерт админу организации).

Боты остальных организаций проходят свою собственную независимую проверку — никакой общей блокировки, никакого общего лока, никакой общей очереди.

### 1.5 Восстановление баланса (idempotent top-up)

Пополнение (`credit_topup`) идёт тем же путём — `INSERT ... ON CONFLICT DO NOTHING` по `idempotency_key` (обычно `payment_provider_transaction_id`), защищает от двойного зачисления при повторной доставке webhook платёжного провайдера.

---

## 2. Карта готовности каналов (Plug-and-Play Matrix)

Цель: после ввода **одного** ключа ИИ-провайдера все уже созданные каналы должны начать работать без деплоя нового кода.

| Канал | Backend-адаптер | Формат ответа (специфика) | Что уже должно быть закодировано |
|---|---|---|---|
| **Telegram** | `app/adapters/telegram_adapter.py` | MarkdownV2 с экранированием спецсимволов (`_*[]()~\`>#+-=|{}.!`), максимум 4096 символов на сообщение — авто-разбиение на части по границам абзацев | `send_message`, `set_webhook`, парсер `getMe` для `reference_id`, экранирующая функция `escape_markdown_v2()` |
| **Wazzup (WhatsApp/Instagram)** | `app/adapters/wazzup_adapter.py` | WhatsApp Markdown (`*bold*`, `_italic_`, `~strike~`, без вложенных HTML), лимит ~4096 символов, поддержка N `channelId` на 1 организацию | `send_message` с мультиканальным резолвом по `channelId`, конвертер из внутреннего Markdown в WhatsApp-формат (`markdown_to_whatsapp()`) |
| **GreenAPI** | `app/adapters/greenapi_adapter.py` | Аналогично Wazzup (WhatsApp-разметка), но собственный формат instance-адресации | `sendMessage` через `idInstance`/`apiTokenInstance`, обработка статусов доставки |
| **Widget** | `app/adapters/widget_adapter.py` | Полный HTML/Markdown рендеринг на фронтенде (без ограничений мессенджера) | WebSocket/SSE канал доставки, полный Markdown → HTML рендер на клиенте |

### 2.1 Единый форматтер-диспетчер

```python
# app/services/formatting/message_formatter.py
class MessageFormatter:
    """
    Единая точка форматирования: ai_orchestrator всегда генерирует ответ
    в едином внутреннем формате (расширенный Markdown), а форматтер
    адаптирует его под целевой канал перед отправкой.
    """
    @staticmethod
    def format_for_channel(text: str, channel_type: ChannelType) -> str:
        match channel_type:
            case ChannelType.TELEGRAM:
                return TelegramFormatter.to_markdown_v2(text)
            case ChannelType.WAZZUP | ChannelType.GREENAPI:
                return WhatsAppFormatter.to_whatsapp_markdown(text)
            case ChannelType.WIDGET:
                return text  # передаётся как есть, рендерится на фронте
```

Это архитектурное развязывание критично: `ai_orchestrator` **не знает** про Telegram/WhatsApp вообще — он производит нейтральный markdown, а `ChannelSenderFactory` перед отправкой прогоняет текст через `MessageFormatter`.

### 2.2 Matrix готовности "из коробки"

| Требование | Статус готовности |
|---|---|
| Резолв `bot_id`/`org_id`/`credential_id` по `bot_channels` без привязки к URL | ✅ Реализовано в `webhooks.py` (см. предыдущий документ, раздел 3.2) |
| Активация всех каналов после ввода одного ключа AI | ✅ При условии, что `bots.ai_integration_id` уже указывает на integration с этим ключом — активация канала (`bot_channels.status = 'active'`) не зависит от наличия AI-ключа, это ортогональные сущности |
| RAG fallback без фатальной ошибки | ✅ `rag_service.retrieve_context()` оборачивается в `try/except ChromaDBConnectionError`, при ошибке — `warning`-лог + пустой контекст |
| Передача менеджеру (handoff) | Требует реализации: функция `escalate_to_human(conversation_id)` — переводит `conversations.status = 'escalated'`, останавливает автогенерацию ИИ, шлёт уведомление в CRM/Telegram-группу операторов |

---

## 3. Чек-лист подготовки к выкатке за 24–48 часов

### День 1 (0–24ч) — Core Correctness

- [ ] **Кошельки:** миграция `organization_wallets` + `wallet_transactions`, backfill существующих организаций начальным балансом (grace-баланс для текущих клиентов).
- [ ] **Атомарность списаний:** нагрузочный тест — 50 параллельных запросов на одну организацию с балансом на 10 списаний → ровно 10 успешных, 40 отклонённых, баланс не уходит в минус (assert на уровне БД `CHECK (balance_tokens >= 0)` как последняя линия защиты).
- [ ] **Изоляция:** тест на 2 организации одновременно — блокировка баланса орг. А не создаёт задержек на запросах орг. Б (замер latency p95 под нагрузкой).
- [ ] **Форматирование:** unit-тесты на `TelegramFormatter`/`WhatsAppFormatter` — экранирование спецсимволов, разбиение длинных сообщений по границам абзацев (не разрывая слова/markdown-теги посередине).
- [ ] **RAG fallback:** тест с искусственно недоступным ChromaDB (mock connection refused) — бот отвечает без контекста, не падает 500-кой.
- [ ] **OAuth refresh:** ручная проверка на staging — токен amoCRM/Bitrix обновляется автоматически, advisory lock не залипает при рестарте воркера.

### День 2 (24–48ч) — Hardening & Launch

- [ ] **Идемпотентность лидов:** stress-тест — 20 параллельных входящих сообщений от одного клиента → создаётся ровно одна сделка.
- [ ] **BYOK Vault:** валидация ключей при вводе (реальный ping-запрос к провайдеру: `GET /v1/models` для OpenAI, `getMe` для Telegram) — невалидный ключ не сохраняется молча, UI показывает конкретную причину.
- [ ] **Billing edge cases:** top-up webhook идемпотентен (двойная доставка от платёжного провайдера не зачисляет баланс дважды).
- [ ] **Nginx/Docker prod:** проверка `docker-compose.prod.yml` — health-checks на все сервисы, restart-policy `unless-stopped`, лимиты памяти на Celery-воркеры (защита от OOM при пиковой нагрузке).
- [ ] **Secrets:** `.env.production` содержит только platform-level OAuth app credentials и fallback-ключи — никаких боевых клиентских токенов.
- [ ] **Мониторинг:** алерты на `wallet blocked events`, `oauth refresh failures`, `webhook unmatched events` (canary на сломанный роутинг).
- [ ] **Rollback-план:** тегированный Docker-образ предыдущей стабильной версии готов к быстрому откату; миграции Alembic имеют рабочий `downgrade()`.
- [ ] **Playground/Demo:** финальный прогон полного пути (Telegram → AI → amoCRM сделка) на реальных тестовых аккаунтах перед объявлением релиза.

---

## 4. Промпты для Cursor Composer (Ctrl + I)

Четыре последовательных промпта. Каждый — самостоятельный composer-запрос, использующий уже существующую структуру репозитория (`backend/app/{api,core,models,repositories,services,adapters,workers}`).

### Этап 1 — Изоляция кошельков организаций

```
Ты работаешь в существующем репозитории MP.AI (backend/app/{models,repositories,services,workers}).
Текущая последняя миграция: 056_byok_credentials_vault. Реализуй Этап 1: финансовая изоляция 
организаций через кошельки.

1. models/wallet.py:
   - SQLAlchemy 2.0 async-модели OrganizationWallet и WalletTransaction по следующей DDL 
     (вставь SQL из раздела 1.2 этого документа). Добавь Enum WalletTxType, Mapped[...] аннотации, 
     CHECK constraint balance_tokens >= 0 на уровне модели (через __table_args__).

2. alembic/versions/057_organization_wallets.py:
   - Migration с созданием обеих таблиц, индексами из раздела 1.2.
   - Data migration: backfill — для каждой существующей organizations создать 
     organization_wallets с balance_tokens = 0, status = 'active' (используй bulk insert, 
     не ORM-цикл, т.к. организаций может быть много).
   - Обязательно реализуй downgrade() с корректным дропом таблиц.

3. repositories/wallet_repository.py:
   - `get_by_org(org_id) -> OrganizationWallet | None` — обычный SELECT без блокировки.
   - `debit_atomic(org_id, bot_id, conversation_id, amount_tokens, model_used, idempotency_key) 
     -> WalletDebitResult` — реализуй ТОЧНО транзакционный сценарий из раздела 1.3: 
     `SELECT ... FOR UPDATE` только на строку этой организации, проверка достаточности 
     баланса, INSERT в wallet_transactions с ON CONFLICT DO NOTHING по idempotency_key, 
     UPDATE баланса с условной установкой status='blocked' при уходе в 0.
   - `credit_atomic(org_id, amount_tokens, tx_type, idempotency_key, metadata)` — аналогично 
     для пополнений, идемпотентно по idempotency_key.
   - Все методы принимают внешнюю AsyncSession (не открывают собственную транзакцию — 
     чтобы вызывающий код мог включить это в более широкую unit-of-work при необходимости).

4. services/wallet_service.py:
   - `check_wallet_before_generation(org_id) -> WalletCheckResult` — read-only быстрая 
     проверка (см. раздел 1.4), НЕ берёт лок.
   - Интегрируй вызов этого метода в начало services/ai_orchestrator.py — ПЕРЕД вызовом 
     любого LLM-провайдера. При allowed=False — вернуть bots.low_balance_message (добавь 
     это поле в модель Bot, миграция 058), НЕ вызывать провайдера вообще.
   - После успешного ответа провайдера с известным usage.total_tokens — вызвать 
     wallet_repository.debit_atomic(...) с idempotency_key = f"{conversation_id}:{message_id}".

5. Тесты (tests/unit/test_wallet_repository.py, tests/stress/test_wallet_isolation.py):
   - Unit: повторный вызов debit_atomic с тем же idempotency_key не списывает баланс дважды.
   - Unit: debit_atomic при balance_tokens < amount возвращает insufficient_balance, 
     баланс не меняется.
   - Stress (pytest-asyncio + реальная тестовая БД, НЕ моки): создай 2 организации. 
     Организация А — баланс на 10 успешных списаний, запусти 50 параллельных 
     debit_atomic-вызовов asyncio.gather — ровно 10 должны быть успешными, баланс 
     организации А не уходит в отрицательное значение. Одновременно запусти 20 
     параллельных запросов на организацию Б (баланс достаточный) — все 20 должны 
     завершиться успешно с latency p95 < 200мс, НЕЗАВИСИМО от нагрузки на организацию А 
     (замерь через time.perf_counter, assert на верхнюю границу latency).

После реализации кратко объясни, почему FOR UPDATE на строку organization_wallets 
физически не может заблокировать другую организацию (row-level lock в PostgreSQL) — 
это ключевой инвариант zero cross-tenant impact.
```

### Этап 2 — Plug-and-Play подключение каналов

```
Реализуй Этап 2: унифицированное форматирование ответов ИИ под каждый канал 
и проверку "активации из коробки".

1. services/formatting/message_formatter.py:
   - Абстрактный класс BaseChannelFormatter с методом format(text: str) -> str.
   - TelegramFormatter.to_markdown_v2(text): экранирование спецсимволов MarkdownV2 
     (_ * [ ] ( ) ~ ` > # + - = | { } . !) вне code-блоков, разбиение сообщений длиннее 
     4096 символов на части по границам абзацев (не разрывая markdown-теги и слова 
     посередине — используй regex-based splitting с сохранением целостности **bold** 
     и других парных токенов).
   - WhatsAppFormatter.to_whatsapp_markdown(text): конвертация из внутреннего 
     расширенного markdown (**bold**, _italic_, ```code```) в WhatsApp-формат 
     (*bold*, _italic_, без code-блоков — замени на моноширинный текст в кавычках), 
     разбиение на части по лимиту ~4096 символов.
   - MessageFormatter.format_for_channel(text, channel_type) — диспетчер (см. раздел 2.1).

2. services/message_formatter должен ИСПОЛЬЗОВАТЬСЯ в services/channel_sender.py 
   (ChannelSenderFactory) ПЕРЕД вызовом adapters/{telegram,wazzup,greenapi}_adapter.py 
   send_message — не внутри ai_orchestrator (оркестратор остаётся channel-agnostic).

3. scripts/verify_channel_readiness.py:
   - CLI-скрипт (может быть вызван из workers/scripts): для каждой organization 
     проверяет — есть ли активный ai_integration с валидным credential, есть ли хотя бы 
     один bot_channel в статусе active без соответствующего активного AI integration 
     (это "осиротевший" канал — залогировать warning). Выводит таблицу готовности 
     по всем организациям для admin-дашборда.

4. Добавь функцию escalate_to_human(conversation_id) в services/conversation_service.py:
   - Переводит conversations.status = 'escalated' (добавь это значение в допустимые статусы).
   - Останавливает автогенерацию ИИ для этого conversation (проверка статуса в начале 
     process_message task).
   - Отправляет уведомление операторам через отдельный Telegram-канал/webhook 
     (настраиваемый per-organization в новой таблице operator_notification_channels 
     — organization_id, channel_type, target_chat_id).
   - Добавь миграцию 059_operator_notifications.

5. Тесты:
   - Unit на TelegramFormatter: длинный текст с **bold** и *italic* разбивается на части 
     без разрыва markdown-токенов, спецсимволы экранированы корректно.
   - Unit на WhatsAppFormatter: конвертация основных markdown-конструкций.
   - Integration: сообщение длиной 10000 символов с вложенным code-блоком корректно 
     разбивается на части для Telegram, каждая часть <= 4096 символов и является 
     валидным MarkdownV2 (проверь через попытку парсинга).
```

### Этап 3 — CRM Роутинг, OAuth Refresh и идемпотентность лидов

```
Реализуй Этап 3: надёжный CRM-слой поверх существующих adapters/amocrm_adapter.py 
и adapters/bitrix24_adapter.py (если их ещё нет в adapters/ — создай по интерфейсу ниже).

1. core/pg_locks.py (если отсутствует):
   - Утилита async def try_advisory_lock(session, lock_key: int) -> bool 
     (обёртка над pg_try_advisory_lock).
   - async def advisory_unlock(session, lock_key: int).
   - Хелпер lock_key_for_credential(credential_id: UUID) -> int (стабильный hashtext).

2. workers/oauth_refresh_worker.py:
   - Celery Beat task каждые 60 секунд.
   - Выборка credentials типа crm_amocrm/crm_bitrix24 с oauth_expires_at < now() + 5 минут, 
     status='active'.
   - Для каждого: try_advisory_lock -> если получен, выполнить refresh через 
     соответствующий adapter, обновить encrypted_payload (используй core/crypto_service.py), 
     oauth_expires_at, снять lock. При ошибке — status='error', last_error, отправить 
     уведомление владельцу организации (переиспользуй operator_notification_channels 
     из Этапа 2, либо email через services/notifications).

3. repositories/deal_repository.py:
   - `upsert_idempotent(organization_id, crm_integration_id, conversation_id, dedup_key, ...) 
     -> DealUpsertResult(deal_id, was_inserted: bool)` — используй 
     `INSERT ... ON CONFLICT (organization_id, dedup_key) DO UPDATE SET updated_at = now() 
     RETURNING id, (xmax = 0) AS was_inserted` (см. раздел 3.4 предыдущего документа архитектуры).
   - dedup_key вычисляется как sha256(organization_id + channel_type + external_chat_id) — 
     вынеси в отдельную чистую функцию compute_dedup_key() для тестируемости.

4. services/crm_orchestrator.py:
   - `handle_new_message_for_crm(conversation)`:
     - вычисляет dedup_key, вызывает deal_repository.upsert_idempotent
     - если was_inserted=True — вызывает CRM-адаптер (amoCRM или Bitrix24 в зависимости 
       от bots.crm_integration_id) для создания лида/контакта
     - если was_inserted=False — опционально добавляет заметку/сообщение в таймлайн 
       существующей сделки через adapter.add_note(external_lead_id, text), если 
       поддерживается
   - Оборачивает вызов CRM API в try/except — ошибка CRM НЕ должна приводить к потере 
     ответа ИИ пользователю (лог ошибки, retry через Celery с exponential backoff, 
     но ответ в мессенджер уже отправлен независимо).

5. Тесты:
   - tests/integration/test_oauth_refresh_race.py: запусти 2 параллельные Celery-таски 
     (или прямых вызова advisory-lock логики) для одного и того же credential_id, 
     замокай HTTP-вызов к amoCRM refresh endpoint — assert call_count == 1.
   - tests/stress/test_deal_idempotency.py: 20 параллельных asyncio-вызовов 
     handle_new_message_for_crm с одинаковым external_chat_id/organization_id — 
     в БД должна остаться ровно одна запись Deal, CRM create_lead вызван ровно 1 раз 
     (остальные 19 — просто upsert без вызова CRM).
```

### Этап 4 — Frontend UI + E2E тесты

```
Реализуй Этап 4 во frontend/ (Next.js App Router, TypeScript) поверх backend-API, 
реализованного на Этапах 1-3.

1. app/(dashboard)/wallet/page.tsx:
   - Отображение текущего баланса organization_wallets (запрос к новому эндпоинту 
     GET /api/v1/wallet — добавь его в backend/app/api/v1/wallet.py, отдаёт баланс + 
     статус + last 20 транзакций из wallet_transactions).
   - Разбивка расхода токенов по каждому боту за период (используй bot_id из 
     wallet_transactions, агрегация SUM(amount_tokens) GROUP BY bot_id за последние 
     7/30 дней — добавь эндпоинт GET /api/v1/wallet/usage-by-bot).
   - Real-time обновление — используй polling каждые 10 секунд (SWR/React Query 
     revalidateOnFocus + refreshInterval), не WebSocket для MVP.
   - Компонент предупреждения при status='blocked' с CTA на пополнение.

2. app/(dashboard)/byok-vault/page.tsx:
   - Форма добавления ключа для каждого типа credential_kind (LLM/канал/CRM).
   - При сабмите — вызов POST /api/v1/credentials с полем validate_before_save=true; 
     backend должен (добавь в backend/app/api/v1/credentials.py) синхронно выполнить 
     дешёвый ping-запрос к провайдеру перед сохранением (GET /v1/models для OpenAI, 
     getMe для Telegram bot_token, простой auth-check для остальных) и вернуть 
     4xx с понятной причиной при невалидном ключе — форма должна показать конкретную 
     ошибку inline, а не generic "Error".
   - Список уже добавленных credentials со статусом (active/expired/error) и кнопкой 
     "Проверить снова".

3. app/(dashboard)/playground/page.tsx:
   - Тестовый чат-интерфейс: выбор бота, отправка сообщения, отображение ответа.
   - Backend-эндпоинт POST /api/v1/playground/chat (добавь в 
     backend/app/api/v1/playground.py) — вызывает ai_orchestrator.generate() напрямую 
     (минуя реальный канал/webhook), НЕ списывает с боевого кошелька (используй 
     отдельный флаг dry_run=true в AIOrchestrator, который считает токены, но 
     пропускает wallet_repository.debit_atomic).
   - В ответе показывать: сгенерированный текст, использованный RAG-контекст 
     (список retrieved chunks с score), оценочную стоимость запроса в токенах.

4. E2E тесты (используй Playwright, frontend/e2e/):
   - wallet-isolation.spec.ts: залогиниться под организацией с обнулённым балансом, 
     убедиться, что UI показывает статус blocked и сообщение о пополнении, playground 
     возвращает понятную ошибку при попытке отправить сообщение.
   - byok-vault-validation.spec.ts: ввод заведомо невалидного OpenAI-ключа → форма 
     показывает конкретную ошибку валидации, ключ не сохраняется в списке.
   - full-pipeline.spec.ts (можно как integration-тест backend, а не строго Playwright, 
     если требуется реальный Telegram/webhook): симулирует входящий webhook от Telegram 
     → проверяет, что создалась Conversation, списался баланс, создалась Deal в 
     тестовом CRM-моке, ответ отправлен обратно (мокни исходящий HTTP-вызов к Telegram 
     Bot API и проверь его payload).

После реализации всех 4 этапов — подготовь краткий README-чеклист 
(docs/architecture/RELEASE_CHECKLIST.md) со ссылкой на все новые эндпоинты, 
миграции (057-059+) и инструкцией по запуску полного тестового набора одной командой.
```

---

### Итог

Документ формализует четыре независимых, но последовательных фронта работ, каждый из которых замыкается на существующую структуру репозитория MP.AI и может быть выполнен отдельным Cursor Composer сеансом с полным покрытием тестами (unit → stress → integration → E2E). Ключевые инварианты релиза:

1. **Финансовая изоляция** гарантируется на уровне PostgreSQL row-level lock, а не только логикой приложения.
2. **Plug-and-play каналов** достигается разделением ответственности: `ai_orchestrator` не знает о мессенджерах, `MessageFormatter` — не знает об LLM.
3. **Идемпотентность** (кошелёк, сделки, OAuth-refresh) везде реализована через `UNIQUE`-constraint + `ON CONFLICT`, а не только через распределённые локи — Redis/advisory locks снижают конкуренцию, но финальную гарантию даёт СУБД.
