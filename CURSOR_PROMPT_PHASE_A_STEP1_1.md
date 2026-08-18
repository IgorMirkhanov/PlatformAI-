# Промпт для Cursor — Phase A, Шаг 1: Pipelines + Stages

Скопируйте текст ниже целиком в Cursor (Composer/Agent-режим, с включённым доступом к репозиторию). Это первый из серии PR-размерных промптов согласно `CRM_INTEGRATION_SPEC.md` (раздел 9). Не давайте Cursor весь CRM-спек одним промптом — только этот шаг.

---

## ПРОМПТ (копировать с этой строки)

Ты работаешь в существующем backend MP.AI (FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2). Перед началом работы обязательно изучи текущие конвенции проекта:

1. Прочитай `.cursorrules` в корне репозитория — следуй ему без исключений.
2. Найди и открой 2–3 существующих модуля, построенных по паттерну `models → schemas → repositories → services → api/endpoints` (например, всё, что связано с `organizations`/`bots`), и повтори их стиль: naming, base-классы, способ фильтрации по tenant (`organization_id`), формат Pydantic-схем, структуру роутеров, способ подключения роутера в `main.py`/`api/__init__.py`.
3. Найди текущую последнюю Alembic-ревизию (`alembic history` / файлы в `backend/migrations` или `backend/alembic/versions`) — она должна быть `022_user_is_support`. Новая миграция обязана указывать её как `down_revision`.

### Задача

Реализовать первый CRM-модуль: **Pipelines (воронки) и Stages (этапы)**. Это первый из серии шагов по внедрению нативной CRM (аналог AmoCRM/Bitrix24, но нашей разработки) — контекст в файле `CRM_INTEGRATION_SPEC.md` в корне репозитория (раздел 2.2 "Сущности", раздел 3 "Backend: структура", раздел 9 "Порядок реализации"). Прочитай его перед началом, но реализуй **только пункт 1 из Phase A** (`023_crm_pipelines_stages`) — ничего сверх этого шага (без Contacts/Deals/Accounts — это отдельные последующие промпты).

### Модели

`backend/app/models/crm/pipeline.py`:
```
CrmPipeline
  id: UUID (PK)
  organization_id: UUID (FK → companies.id, NOT NULL, indexed)
  name: str
  position: int
  is_default: bool (default False)
  created_at, updated_at: timestamptz
```

`backend/app/models/crm/stage.py`:
```
CrmStage
  id: UUID (PK)
  organization_id: UUID (FK → companies.id, NOT NULL, indexed)   # денормализовано намеренно — фильтрация без join через pipeline
  pipeline_id: UUID (FK → crm_pipelines.id, NOT NULL, indexed, ON DELETE CASCADE)
  name: str
  position: int
  color: str (hex, nullable)
  is_won: bool (default False)
  is_lost: bool (default False)
  created_at, updated_at: timestamptz
```

Ограничение на уровне БД: у одного pipeline не может быть больше одного `is_won=True` и больше одного `is_lost=True` этапа — реализуй как partial unique index (`WHERE is_won`, `WHERE is_lost`), не как runtime-проверку в сервисе (защита от гонок).

### Репозитории

`backend/app/repositories/crm/base_crm_repository.py` — базовый класс/миксин, который:
- принимает `organization_id` в конструкторе или в каждом методе (повтори способ передачи tenant-контекста, который уже используется в существующих tenant-aware репозиториях проекта — не изобретай новый способ);
- **все** SELECT/UPDATE/DELETE автоматически добавляют `.where(Model.organization_id == self.organization_id)`;
- любой метод, который бы позволил забыть про этот фильтр (например, "получить по id без проверки organization_id"), не должен существовать в публичном API класса.

`backend/app/repositories/crm/pipeline_repository.py`, `stage_repository.py` — наследуются от `base_crm_repository`, CRUD + `reorder(positions: list[tuple[id, int]])`.

### Сервисы

`backend/app/services/crm/pipeline_service.py`:
- `create_default_pipeline(organization_id)` — создаёт воронку "Продажи" с этапами: Новый лид → Квалификация → Предложение → Переговоры → Выиграна (is_won=True) / Проиграна (is_lost=True). Этот метод должен вызываться из существующего flow создания организации (найди, где в коде сейчас создаётся `Company`/`Organization` при регистрации, и добавь вызов туда — не дублируй логику seed'а в нескольких местах).
- `create_pipeline`, `update_pipeline`, `delete_pipeline` (запрети удаление, если есть сделки — этот чек можно временно оставить как TODO-комментарий с `NotImplementedError`, т.к. `crm_deals` появятся в следующем шаге; не блокируй текущий PR на этом).
- `reorder_stages`.

### API

`backend/app/api/endpoints/crm/pipelines.py`, подключить под префиксом `/api/v1/crm/pipelines`:
- `GET /api/v1/crm/pipelines` — список воронок организации (с вложенными stages)
- `POST /api/v1/crm/pipelines`
- `PATCH /api/v1/crm/pipelines/{id}`
- `DELETE /api/v1/crm/pipelines/{id}`
- `POST /api/v1/crm/pipelines/{id}/stages`
- `PATCH /api/v1/crm/pipelines/{id}/stages/{stage_id}`
- `DELETE /api/v1/crm/pipelines/{id}/stages/{stage_id}`
- `POST /api/v1/crm/pipelines/{id}/stages/reorder`

Все эндпоинты — только для ролей OWNER/ADMIN (повтори существующий dependency для ролевой проверки, найди его по аналогии с другими admin-only роутами). Authentication — как у остальных `/api/v1/*` эндпоинтов (JWT, tenant из `X-Tenant-ID`/JWT claim — используй тот же механизм, что уже есть, не изобретай новый).

### Миграция

`023_crm_pipelines_stages` — Alembic revision, `down_revision = '022_user_is_support'` (проверь точное имя ревизии в репозитории и поправь при необходимости). Создаёт обе таблицы + индексы + partial unique constraints, описанные выше. Данные не бэкфиллятся (новые таблицы, пустые).

### Тесты

Добавь pytest-тесты в стиле существующих (найди похожий тестовый модуль для ориентира — расположение, фикстуры БД/тенанта, авторизация тестового клиента):
- создание pipeline создаёт дефолтные этапы там, где ожидается;
- CRUD pipelines/stages корректно скоупится по organization_id — **обязательно** тест, что пользователь организации A не видит/не может изменить pipeline организации B (создай два тенанта в фикстуре, попробуй кросс-доступ, ожидай 403/404);
- reorder корректно применяет позиции;
- партиал-unique constraint на is_won/is_lost не даёт создать два "выигранных" этапа в одной воронке.

### Что НЕ делать в этом PR

- Не трогай `crm_action` узел конструктора — это отдельный шаг.
- Не создавай `crm_deals`/`crm_contacts`/`crm_accounts` — следующий промпт.
- Не трогай `.env.production.example`/`docker-compose*.yml`/`nginx` — этот шаг чисто в рамках backend-кода и одной миграции.
- Не добавляй ничего во frontend в этом PR.

### Definition of Done

- [ ] Миграция применяется чисто на пустой БД и на БД с текущим head (`022_user_is_support`)
- [ ] Все новые SELECT проходят только через `base_crm_repository` (без прямых `select(CrmPipeline)`/`select(CrmStage)` вне репозитория — проверь grep'ом по diff перед завершением)
- [ ] Тест на кросс-тенантный доступ зелёный
- [ ] `alembic downgrade -1` от новой ревизии откатывается чисто
- [ ] Существующие тесты не сломаны (`pytest` полностью зелёный, не только новые файлы)

## КОНЕЦ ПРОМПТА (копировать до этой строки)

---

## Что дальше

После того как этот PR смёржен, следующий промпт в этой же серии — **Шаг 2: CrmAccount + CrmContact + связка с `clients.linked_client_id`** (миграция `024_crm_accounts_contacts`). Прежде чем его писать, пришлите мне реальный код моделей `Client`/`Bot` из вашего backend (пункт 1 из "Открытых вопросов" в `CRM_INTEGRATION_SPEC.md`) — без него есть риск неверно спроектировать FK на `clients`, т.к. присланный ранее `architecture_db.md.txt` устарел и не отражает актуальную мульти-тенантную схему.
