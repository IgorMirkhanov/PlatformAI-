# MP.AI Native CRM — техническое задание и архитектура интеграции

**Статус:** черновик v1 для реализации через Cursor
**Дата:** 2026-07-23
**Автор контекста:** составлено на основе присланных инфра/докс-файлов MP.AI (multi-tenant SaaS-конструктор ИИ-ботов: FastAPI + SQLAlchemy async + Pydantic v2, Next.js 14 App Router, PostgreSQL + Redis/Celery, React Flow builder, org-level Stripe billing)

---

## 0. Формулировка задачи

Встроить в MP.AI **собственную CRM-систему** (аналог функциональности AmoCRM/Bitrix24: воронки продаж, сделки, контакты, задачи, коммуникации), полностью написанную нашей командой и интегрированную с уже существующими сущностями платформы — ботами, каналами (WhatsApp/Telegram/Instagram/WABA), конструктором сценариев (React Flow) и узлом `crm_action` (сейчас — внешний webhook в amoCRM/Bitrix).

Ключевой архитектурный принцип: **CRM — это не отдельный продукт, а модуль внутри существующего мульти-тенантного ядра**. Она обязана переиспользовать то, что уже построено (tenancy по `organization_id`, RBAC, аудит, биллинг/квоты, WS-инфраструктуру, очереди Celery), а не дублировать их.

---

## 1. Конкурентный анализ (AmoCRM / Bitrix24) — что берём, что осознанно упрощаем

| Возможность | AmoCRM | Bitrix24 | Решение для MP.AI v1 |
|---|---|---|---|
| Воронки (pipelines) + этапы (stages) | ✅ несколько воронок | ✅ несколько воронок + "смарт-процессы" | ✅ MVP: неограниченное число pipeline на организацию, кастомные этапы |
| Канбан-доска сделок | ✅ основной UI | ✅ | ✅ MVP, drag&drop |
| Карточка контакта/компании (раздельно) | ✅ Контакт + Компания раздельно | ✅ | ✅, но **переименовать «Компанию» во избежание коллизии с tenant-моделью** (см. §2.1) |
| Кастомные поля | ✅ богатый набор типов | ✅ + связи между сущностями | ✅ MVP: text/number/select/multiselect/date/boolean/url; связи — Phase B |
| Автоматизации (роботы/бизнес-процессы) | ✅ триггеры на этапах | ✅✅ мощный BPM-конструктор | ⚠️ Phase B, упрощённая модель триггер→условие→действие (см. §6) |
| Задачи/напоминания | ✅ | ✅✅ (расширенный таск-трекер) | ✅ MVP: простые задачи с due_at, напоминание через Celery |
| Единый чат/omnichannel inbox | ✅ (уже частично покрыто вашим `/inbox`) | ✅ | ✅ Переиспользуем существующий `/inbox` + Operator WS, добавляем привязку к сделке |
| Телефония/звонки | ✅ (через интеграции) | ✅✅ встроенная АТС | ❌ Вне MVP. Заложить модель `CrmActivity(type=call)` как контейнер под будущую интеграцию |
| Права доступа "только свои сделки / все сделки" | ✅ | ✅✅ детальные | ✅ MVP на уровне ролей, Phase B — per-deal scoping |
| Отчёты/воронка конверсии | ✅ | ✅✅ | ⚠️ Phase C, переиспользуем `AnalyticsService`/`UsageEvent` (уже в вашем roadmap как M5 "Org ROI report") |
| Публичный API/вебхуки для внешних систем | ✅ | ✅ | ✅ MVP: минимальный набор (создание сделки/контакта), Phase B — полноценный webhook-registry |
| Marketplace/маркетплейс интеграций | ✅ | ✅✅ | ❌ Не в скоуп; у вас уже есть свой Template Gallery в V1.1 roadmap — не смешивать |

**Вывод:** не пытаемся повторить Bitrix24 целиком (это отдельный продукт с BPM-движком). Цель — закрыть 80% сценариев продаж/лидогенерации, которые сейчас закрывают через внешние CRM, при этом **нативно** зная о ботах, каналах и диалогах — то, чего у AmoCRM/Bitrix24 нет по умолчанию (у них это отдельные интеграции).

---

## 2. Модель данных

### 2.1. ⚠️ Критично: конфликт имён "Company"

В текущей схеме MP.AI тенант (организация-клиент SaaS) уже называется `companies` в БД (см. `STRIPE_ORG_MIGRATION.md`: `companies.stripe_customer_id` и т.д.), а на уровне API/бизнес-терминов — `organization_id`. Если по аналогии с AmoCRM назвать CRM-сущность "компания клиента" тоже `Company` — будет прямая путаница (две разные сущности "Company" в одной кодовой базе: тенант vs клиент тенанта).

**Решение:** CRM-сущность именуем `CrmAccount` (в БД — `crm_accounts`), а не `Company`/`CrmCompany`. Во всех докстрингах и в UI термин "Компания" на фронтенде допустим (пользователю всё равно), но в коде — только `CrmAccount`.

### 2.2. Сущности (ядро, Phase A/MVP)

Все таблицы — `organization_id UUID NOT NULL REFERENCES companies(id)` + индекс, без исключений. Ни одна CRM-таблица не существует без tenant-скоупа.

```
crm_pipelines
  id, organization_id, name, position, is_default, created_at

crm_stages
  id, organization_id, pipeline_id → crm_pipelines,
  name, position, color, is_won (bool), is_lost (bool)

crm_accounts            -- ранее "Company" в терминах AmoCRM, см. §2.1
  id, organization_id, name, industry, website,
  custom_fields JSONB, created_at, updated_at

crm_contacts
  id, organization_id, account_id → crm_accounts (nullable),
  first_name, last_name, phone, email,
  source (enum: whatsapp/telegram/instagram/waba/manual/api),
  linked_client_id → clients.id (nullable, см. §2.4),
  custom_fields JSONB, avatar_url, created_at, updated_at

crm_deals
  id, organization_id, pipeline_id → crm_pipelines, stage_id → crm_stages,
  contact_id → crm_contacts (nullable), account_id → crm_accounts (nullable),
  bot_id → bots.id (nullable, откуда пришёл лид),
  assigned_user_id → users.id (nullable),
  title, amount NUMERIC, currency (default из org settings),
  status (enum: open/won/lost),
  source, tags (M2M через crm_deal_tags),
  custom_fields JSONB,
  created_at, updated_at, closed_at

crm_activities            -- задачи/звонки/встречи
  id, organization_id, deal_id → crm_deals (nullable),
  contact_id → crm_contacts (nullable),
  type (enum: task/call/meeting/email),
  title, description, due_at, completed_at,
  assigned_user_id → users.id,
  created_by_id → users.id, created_at

crm_notes
  id, organization_id, deal_id (nullable), contact_id (nullable),
  author_id → users.id, text, created_at

crm_timeline_events       -- автолог: смена этапа, входящее сообщение, звонок, изменение поля
  id, organization_id, deal_id (nullable), contact_id (nullable),
  event_type, payload JSONB, actor_id (nullable, null = система),
  created_at

crm_tags
  id, organization_id, name, color

crm_custom_field_defs
  id, organization_id, entity_type (enum: contact/account/deal),
  field_key, label, field_type (text/number/select/multiselect/date/bool/url),
  options JSONB (для select), is_required, position
```

### 2.3. Сущности Phase B

```
crm_automation_rules
  id, organization_id, name, is_active,
  trigger_type (enum: stage_entered/field_changed/tag_added/no_activity_for/deal_created),
  trigger_config JSONB,           -- напр. {"stage_id": "...", "pipeline_id": "..."}
  conditions JSONB,               -- переиспользуем DSL из FlowExecutor, см. §6
  actions JSONB,                  -- [{"type":"move_stage","stage_id":"..."}, {"type":"send_webhook","url":"..."}]
  created_at, updated_at

crm_webhook_subscriptions  -- исходящие вебхуки CRM → внешние системы (партнёрский API)
  id, organization_id, target_url, event_types TEXT[], secret, is_active

crm_api_keys                -- входящие: внешние системы пушат лиды в CRM
  id, organization_id, key_hash, label, scopes, last_used_at, created_at
```

### 2.4. Связь с существующими таблицами `clients` / `chat_messages`

Важно: документ `architecture_db.md.txt`, который вы присылали, описывает **устаревшую однотенантную схему** (`bots.user_id`, без `organization_id`). Прежде чем проектировать CRM поверх `clients`/`chat_messages`, нужно свериться с **актуальной** схемой из вашего backend-кода (в частности — есть ли у `clients` сейчас `organization_id`/`company_id` напрямую или только через `bot_id → bots.organization_id`). Это первый пункт, который надо уточнить в реальном коде до начала миграций (см. Открытые вопросы, §10).

Логика связки (независимо от точной FK-цепочки):
- Каждый `clients`-рекорд (человек, который написал боту) должен маппиться на `crm_contacts.linked_client_id` — **1:1, лениво создаётся** при первом сообщении (см. §5, автозахват лида).
- `chat_messages` не дублируются в CRM — таймлайн сделки **ссылается** на них (или на агрегированные события), а не копирует текст переписки, чтобы не плодить источники правды.

---

## 3. Backend: структура (Cursor должен повторить существующий паттерн `routers → services → repositories`)

```
backend/app/
├── models/crm/
│   ├── pipeline.py
│   ├── stage.py
│   ├── account.py
│   ├── contact.py
│   ├── deal.py
│   ├── activity.py
│   ├── note.py
│   ├── timeline_event.py
│   ├── tag.py
│   ├── custom_field.py
│   └── automation_rule.py          # Phase B
├── schemas/crm/                     # Pydantic v2, зеркалит models
├── repositories/crm/
│   ├── base_crm_repository.py       # ОБЯЗАТЕЛЬНЫЙ миксин: все query автоматически .where(organization_id=...)
│   ├── pipeline_repository.py
│   ├── deal_repository.py
│   ├── contact_repository.py
│   └── ...
├── services/crm/
│   ├── pipeline_service.py
│   ├── deal_service.py              # move_stage(), assign(), win(), lose()
│   ├── contact_service.py           # get_or_create_from_client()  ← точка входа автозахвата
│   ├── timeline_service.py          # log_event() — вызывается из других сервисов, не наоборот
│   ├── automation_service.py        # Phase B, реюзает flow_parser condition evaluator
│   └── crm_bridge_service.py        # мост Flow Builder ↔ CRM (см. §5)
├── api/endpoints/crm/
│   ├── pipelines.py
│   ├── deals.py
│   ├── contacts.py
│   ├── accounts.py
│   ├── activities.py
│   ├── automations.py               # Phase B
│   └── public_webhooks.py           # внешний inbound API, авторизация по crm_api_keys
└── tasks/crm_tasks.py                # Celery: activity-напоминания, no-activity nudges, automation runner
```

**Правило для Cursor (жёсткое):** ни один CRM-репозиторий не пишет `select(Model)` напрямую — только через `base_crm_repository`, который инъектит фильтр по `organization_id` из контекста запроса. Это то же самое требование, что уже прописано у вас в `.cursorrules` для остального backend ("роуты → сервисы → репозитории"), просто явно продублировать для CRM, потому что цена утечки данных между организациями здесь особенно высока (сделки/контакты — самое чувствительное, что есть в CRM).

### 3.1. Очереди Celery — используем то, что уже задано в инфраструктуре

Обратите внимание: в `docker-compose.prod.yml` уже объявлена очередь:
```
CELERY_QUEUES: inbound_messages,crm_actions
```
Название `crm_actions` уже зарезервировано под текущий узел `crm_action` (внешний webhook в amoCRM/Bitrix). **Новую очередь заводить не нужно** — все асинхронные CRM-операции (автозахват лида, применение автоматизаций, напоминания задач) должны идти через эту же очередь `crm_actions`, только с новыми типами задач (`crm_actions.capture_lead`, `crm_actions.run_automation`, `crm_actions.reminder_due`). Это минимизирует изменения в `docker-compose.prod.yml`/`deploy.sh` и логично с точки зрения домена.

---

## 4. Frontend: структура

```
frontend/src/
├── app/dashboard/crm/
│   ├── page.tsx                     # Kanban-доска (сделки по этапам)
│   ├── [dealId]/page.tsx            # Карточка сделки: таймлайн, заметки, задачи, контакт
│   ├── contacts/page.tsx            # Таблица контактов
│   ├── contacts/[id]/page.tsx
│   └── settings/
│       ├── pipelines/page.tsx       # редактор воронок/этапов
│       ├── fields/page.tsx          # редактор кастомных полей
│       └── automations/page.tsx     # Phase B
├── components/crm/
│   ├── KanbanBoard.tsx / DealCard.tsx
│   ├── DealTimeline.tsx
│   ├── ContactCard.tsx
│   ├── PipelineEditor.tsx
│   ├── CustomFieldsForm.tsx         # динамическая форма по crm_custom_field_defs
│   └── AutomationRuleBuilder.tsx    # Phase B — см. заметку ниже
├── store/useCrmStore.ts             # Zustand, тот же паттерн, что useFlowStore/useBotStore
└── lib/crm/api.ts                   # типизированные клиенты к /api/v1/crm/*
```

**Заметка про UX-синергию:** для канбан-доски не переиспользуйте React Flow (он для графов, не для списков-колонок) — возьмите `@hello-pangea/dnd` или `dnd-kit`, они уже фактически стандарт для kanban в React-экосистеме и не конфликтуют с React Flow, который у вас уже используется в конструкторе.

Для `AutomationRuleBuilder.tsx` в Phase B, наоборот, **имеет смысл переиспользовать React Flow** — правило "триггер → условия → действия" визуально то же самое, что и ветка в конструкторе бота, а у вас уже есть готовый `PropertiesPanel`/canvas-инфраструктура. Это ускорит разработку и даст пользователю знакомый UI.

---

## 5. Интеграция с Flow Builder и автозахват лидов

### 5.1. Автозахват (без участия пользователя)

Событие: первое входящее сообщение от нового `clients`-рекорда (не важно, из какого канала — WhatsApp/Telegram/Instagram/WABA).

```
inbound webhook (whatsapp/telegram/…)
  → Celery: crm_actions.capture_lead(client_id, bot_id)
    → contact_service.get_or_create_from_client(client_id)
    → если для организации включена настройка "auto-create deal on first message":
        deal_service.create(pipeline=default, stage=first_stage, contact=…, bot_id=…, source=channel)
    → timeline_service.log_event(deal, "lead_captured")
```

Настройка "включать ли автозахват" — на уровне организации (`crm_settings.auto_capture_enabled`), т.к. не все клиенты захотят, чтобы каждое сообщение боту сразу создавало сделку (спам/боты-тест-чаты).

### 5.2. Расширение узла `crm_action` в конструкторе

Сейчас (`FLOW_BUILDER_RUNTIME.md`): `crm_action` → `amoCRM / Bitrix / webhook`. Добавляем 4-й таргет — **`internal`**:

```json
{
  "type": "crm_action",
  "data": {
    "target": "internal",
    "action": "move_stage" | "create_task" | "add_tag" | "update_field" | "add_note",
    "params": { "stage_id": "...", "field_key": "...", "value": "{{last_user_message}}" }
  }
}
```

Выполняется тем же `FlowExecutionService`, просто внутренний `target=internal` роутится в `crm_bridge_service` вместо HTTP-запроса наружу. Это значит: **既 старые сценарии с amoCRM/Bitrix продолжают работать без изменений**, новая CRM — просто ещё один вариант в том же селекте узла. Ничего в существующем контракте узла ломать не нужно.

### 5.3. Inbox ↔ CRM

`/inbox` (Operator Live Chat, уже существует) должен получить панель "Сделка клиента" сбоку — при открытии диалога подтягивается `crm_deals`, привязанная к `linked_client_id`. Это устраняет необходимость держать два разных места (чат и CRM) как несвязанные приложения — то, чем страдают интеграции AmoCRM с мессенджерами "из коробки" (два открытых окна, ручное сопоставление).

---

## 6. Автоматизации (Phase B) — не изобретаем второй DSL

У вас уже есть `FlowExecutor` (`backend/app/services/flow_parser.py`) с условной логикой для узла `condition`. Автоматизации CRM (`crm_automation_rules.conditions`) должны использовать **тот же формат условий и тот же evaluator**, только с другим набором переменных контекста (`deal.amount`, `deal.stage`, `contact.tags`, вместо `message.text`/`session.variables`). Это экономит время реализации и тестирования — не нужно писать/тестировать второй парсер условий с нуля.

Триггеры v1 (минимальный набор, достаточный для 80% сценариев):
- `stage_entered` — сделка попала на этап X
- `field_changed` — изменилось кастомное поле
- `tag_added`
- `no_activity_for` — сделка не двигалась N дней (проверяется периодической Celery-задачей, не событийно)

Действия v1:
- `move_stage`, `assign_user`, `add_tag`, `create_task`, `send_webhook`

⚠️ **Безопасность действия `send_webhook`:** как и в WhatsApp `media_url` (см. отдельный разбор `server.js` ранее), любой пользовательский URL, который система сама будет дёргать по расписанию/триггеру — потенциальный вектор SSRF. Обязательно: валидация схемы (`https://` only), блокировка приватных/loopback-диапазонов перед отправкой, таймаут и лимит числа исходящих вызовов на организацию в минуту (переиспользовать паттерн `limit_req_zone` подхода, но на уровне приложения/Celery rate-limit).

---

## 7. RBAC, квоты и биллинг — переиспользование, не изобретение

### 7.1. Роли
Существующие роли `OWNER / ADMIN / PROMPT_ENGINEER / OPERATOR` нужно замапить на CRM-права:

| Действие | OWNER | ADMIN | OPERATOR | PROMPT_ENGINEER |
|---|---|---|---|---|
| Просмотр всех сделок орг. | ✅ | ✅ | ⚠️ Phase B: настраивается ("только свои") | ❌ (нет доступа к CRM по умолчанию) |
| Редактирование pipeline/этапов/полей | ✅ | ✅ | ❌ | ❌ |
| Создание/перемещение сделок | ✅ | ✅ | ✅ | ❌ |
| Настройка автоматизаций | ✅ | ✅ | ❌ | ❌ |
| Удаление сделки/контакта | ✅ | ✅ | ❌ | ❌ |

MVP: реализовать только "все сделки видны всем с доступом к CRM" — per-deal scoping ("только свои") — Phase B, т.к. требует отдельной модели видимости и это ощутимый объём работы, не блокирующий MVP.

### 7.2. Квоты/биллинг
Число контактов/открытых сделок/активных правил автоматизации логично добавить как новые измерения квот, по аналогии с уже существующими `bots/messages/tokens` (`QuotaService`/`UsageService`, HTTP 402). Пример: `PLAN_LIMITS.crm_contacts_max`, `PLAN_LIMITS.crm_automation_rules_max`. Не делать этого в MVP не обязательно (можно временно не квотировать CRM в v1, добавить лимиты в Phase B), но модель `UsageEvent` стоит **сразу** расширить новыми типами событий (`DEAL_CREATED`, `DEAL_WON`, `DEAL_LOST`, `TASK_COMPLETED`) — это прямо соответствует уже запланированному в `V1.1_ROADMAP.md` пункту **M5 "Org ROI report"**, который без данных о сделках попросту нечем будет наполнять. CRM де-факто становится источником данных для этого будущего фичи, так что стоит спроектировать события заранее, а не потом добавлять миграцией.

---

## 8. Real-time

Канбан-доска должна обновляться в реальном времени при изменениях от других пользователей (например, оператор в `/inbox` подвинул сделку). Переиспользуем существующий WS-гейтвей (`/api/v1/ws/`), добавляя топик `crm:{organization_id}` и события:
```json
{ "type": "deal.updated", "deal_id": "...", "stage_id": "...", "actor_id": "..." }
{ "type": "deal.created", "deal": {...} }
```
Никакой новой WS-инфраструктуры заводить не нужно — то же самое соединение, что уже держит фронтенд для Operator Live Chat, просто ещё один канал/топик поверх него.

---

## 9. Порядок реализации (для Cursor — по одному ограниченному PR за раз)

Рекомендация: не давать Cursor весь этот документ одним промптом на "напиши CRM". Разбивайте на PR-размерные задачи, каждая — одна модель + repo + service + router (+ Pydantic-схемы) + минимальные тесты, в порядке ниже. Каждый шаг — отдельная Alembic-миграция (следующая за вашей последней `022_user_is_support`, т.е. начиная с `023_crm_pipelines_stages`).

**Phase A (MVP, миграции 023–027):**
1. `023_crm_pipelines_stages` — Pipeline + Stage (+ дефолтная воронка "Продажи" с этапами Новый лид → Квалификация → Предложение → Переговоры → Выиграна/Проиграна, сидируется при создании организации)
2. `024_crm_accounts_contacts` — CrmAccount + CrmContact (+ `linked_client_id`)
3. `025_crm_deals` — Deal + связь с pipeline/stage/contact/account/bot
4. `026_crm_activities_notes_timeline` — Activity + Note + TimelineEvent
5. `027_crm_tags_custom_fields` — Tag + CustomFieldDefinition
6. Frontend: Kanban + карточка сделки + контакты (без автоматизаций и кастомных полей в UI — можно API-only на первой итерации)
7. Автозахват лида (§5.1) + расширение `crm_action` (§5.2, только `move_stage`/`add_note`/`add_tag` — минимальный набор действий)

**Phase B (миграции 028+):**
1. `028_crm_automation_rules`
2. Automation engine на базе `flow_parser` evaluator (§6)
3. RBAC per-deal scoping
4. Полный набор действий `crm_action(target=internal)`
5. Real-time WS-топик (§8)
6. Публичный inbound API + `crm_api_keys`

**Phase C:**
1. Отчёты/воронка конверсии (реюз `AnalyticsService`)
2. Квоты на CRM-сущности (§7.2)
3. Исходящие вебхуки для партнёров (`crm_webhook_subscriptions`)

### 9.1. Что добавить в `.cursorrules` перед началом

Ваш текущий `.cursorrules` не содержит CRM-специфичных правил. Рекомендую добавить блок:

```
## Правила для CRM-модуля
- Любая CRM-таблица обязана иметь organization_id и попадать под base_crm_repository — прямой select() по CRM-моделям в обход репозитория запрещён.
- Действия автоматизаций типа send_webhook обязаны проходить через shared SSRF-guard (allowlist схемы + блокировка приватных диапазонов) перед выполнением исходящего запроса.
- Название "Company"/"Организация" зарезервировано за tenant-моделью (companies/organization_id). CRM-сущность клиента компании называется исключительно CrmAccount.
- Все мутации сделок (move_stage, assign, win/lose) обязаны писать TimelineEvent — источник правды для истории сделки, а не подразумеваемая логика на фронтенде.
```

---

## 10. Открытые вопросы (нужно уточнить до старта миграций)

1. **Актуальная схема `clients`/`bots`.** `architecture_db.md.txt`, который у меня есть, устарел (однотенантный, `bots.user_id` вместо `organization_id`). Нужен реальный код моделей `Client`/`Bot` из backend, иначе §2.4 (связка CRM ↔ существующие диалоги) можно спроектировать неверно.
2. **Мультивалютность.** Нужна ли поддержка нескольких валют на организацию для `crm_deals.amount/currency`, или на первую версию достаточно одной валюты на организацию (проще: поле в настройках org)?
3. **Объём Phase A по каналам.** Нужен ли автозахват лида сразу для всех каналов (WhatsApp/Telegram/Instagram/WABA/Wazzup) или для MVP хватит WhatsApp+Telegram (судя по маршрутам `dashboard/channels-agent/[id]/*`, у вас их 5+)?
4. **Кто "assigned_user_id"** — только штатные пользователи организации (`users` с ролью OPERATOR+) или также нужна концепция "отдел продаж" отдельно от ролей платформы?
5. **Нужна ли CRM как отдельный тарифный признак** (доступна только на PRO/ENTERPRISE) или доступна на всех планах с квотами по числу контактов?

---

## Итог

CRM проектируется не как самостоятельный продукт, а как **пятый модуль поверх уже существующего ядра** MP.AI (наравне с Flow Builder, каналами, биллингом, admin-панелью), с максимальным переиспользованием: tenancy-модели, RBAC, Celery-очереди `crm_actions`, WS-гейтвея, condition-evaluator из `FlowExecutor`, `AnalyticsService`/`UsageEvent`. Это и быстрее в реализации через Cursor (меньше нового кода — меньше риска рассинхрона с house style, который уже виден в `.cursorrules`), и логичнее для пользователя (CRM "знает" о ботах и диалогах нативно, чего конкурентам приходится добиваться через отдельные интеграции).
