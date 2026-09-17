# Где крутить MP.AI бесплатно / дёшево

Стек — это **не один сайт**: Postgres, Redis, Chroma, FastAPI, Celery, WhatsApp, nginx.
Его **нельзя целиком поставить на Vercel**. Vercel тянет только Next.js-фронт; боты, вебхуки и БД умрут.

## Что выбрать

| Вариант | Цена | Подходит | Не подходит |
|---|---|---|---|
| **Этот ПК + Cloudflare Tunnel** | бесплатно | тест в интернете, Telegram HTTPS webhook за час | ПК выключили — всё упало |
| **Oracle Cloud Always Free VM** | бесплатно (нужна карта) | настоящий 24/7 Docker-прод | регистрация, лимиты ARM |
| **Fly.io / Railway** | почти всегда платно на таком объёме | маленький staging | бесплатный лимит съест Postgres+Redis |
| **Vercel** | бесплатный фронт | CDN/UI, если API уже на VPS | API, БД, Celery, WhatsApp |

Рекомендация: **сначала туннель на этом ПК**, когда понадобится «всегда онлайн» — **бесплатная VM с Docker** (Oracle или любой дешёвый VPS от $4).

## 1. Быстрый публичный HTTPS с этого компьютера

1. Поставьте [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/).
2. В отдельном терминале:

```powershell
cloudflared tunnel --url http://127.0.0.1
```

3. Скопируйте URL вида `https://xxxx.trycloudflare.com` (без `/` в конце).
4. В `.env.production`:

```
WEBHOOK_BASE_URL=https://xxxx.trycloudflare.com
CORS_ORIGINS=https://xxxx.trycloudflare.com,http://127.0.0.1,http://localhost
FRONTEND_URL=https://xxxx.trycloudflare.com
```

5. Пересоздайте API (том Postgres **не** трогать):

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --no-deps --force-recreate backend_api celery_worker
```

6. Откройте `https://xxxx.trycloudflare.com` и в боте Telegram проверьте webhook  
   (`WEBHOOK_BASE_URL/api/v1/webhooks/telegram`).

Туннель меняет URL после перезапуска `cloudflared` — тогда снова пропишите `WEBHOOK_BASE_URL`. Постоянный хост: свой домен в Cloudflare + named tunnel.

Альтернатива с тем же смыслом: ngrok (`ngrok http 80`), URL в `WEBHOOK_BASE_URL` и `NGROK_TUNNEL_URL`.

## 2. Бесплатный сервер 24/7 (Docker)

1. Oracle Cloud: Always Free Ampere, Ubuntu, откройте порты 80/443.
2. На VM: Docker + Compose, скопируйте репозиторий и `.env.production` (не в git).
3. DNS A-запись домена → IP VM.
4. Let's Encrypt — см. [PRODUCTION_DEPLOY.md](./PRODUCTION_DEPLOY.md) §4.
5. `WEBHOOK_BASE_URL=https://ваш-домен` и `./deploy.sh` или `.\deploy.ps1`.

Так выглядит настоящий публичный прод. Vercel здесь не участвует.

## 3. Если очень хочется Vercel

Только фронт:

- Root: `frontend/`, env `NEXT_PUBLIC_API_URL=https://api.ваш-домен`
- API/БД/воркеры остаются на Docker-хосте из §1 или §2

Без своего API Vercel бесполезен для ботов.

## 4. Бэкап (уже в репо)

```powershell
.\deploy.ps1 -Backup
```

Дамп пишется в `backups/pg_*` (папка в `.gitignore`). Копию унесите на диск / Google Drive.

## 5. Каналы и Locust

- Telegram: после публичного HTTPS переподключите бота в UI, чтобы `setWebhook` ушёл на новый URL.
- Виджет: тот же HTTPS-домен.
- WhatsApp: отсканируйте QR в админке; сессии живут в томе `whatsapp_sessions`.
- Locust — только на отдельном тестовом боте, не на живых 21 агентах:

```powershell
cd backend
$env:MPAI_BASE_URL="http://127.0.0.1"
$env:MPAI_EMAIL="..."
$env:MPAI_PASSWORD="..."
$env:MPAI_DISABLE_SHAPE="1"
locust -f locustfile.py --host=http://127.0.0.1 --users 10 --spawn-rate 2 --run-time 3m --headless
```
