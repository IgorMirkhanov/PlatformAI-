# Load testing — MP.AI (`backend/locustfile.py`)

## Goals

| Metric | Threshold |
|--------|-----------|
| Steady RPS | ~**20** |
| Users | ramp **10 → 50** |
| `POST /api/v1/bots/{id}/execute` p95 | **< 2000 ms** |
| Fail ratio | **< 1%** (402 quota counted as success) |

## Scenarios covered

1. Auth login (`MPAI_EMAIL` / `MPAI_PASSWORD`) or pre-minted `MPAI_TOKEN`
2. Create bot
3. Open flow-builder data (`GET .../flow`, profile)
4. Execute simple flow (weighted heaviest)
5. WhatsApp webhook-style send (tolerant of 404/405)
6. Health + billing status

## Local

```bash
cd backend
python -m pip install locust

export MPAI_BASE_URL=http://localhost:8000
export MPAI_TOKEN=<jwt>
export MPAI_BOT_ID=<uuid>          # optional
export MPAI_ORG_ID=<company uuid>  # optional X-Company-Id
export MPAI_ASSERT_THRESHOLDS=1

mkdir -p reports
locust -f locustfile.py --host=$MPAI_BASE_URL \
  --run-time 10m --headless --csv=reports/locust
```

Shape (10→50) is built-in via `StagesShape`. To use CLI users only:

```bash
export MPAI_DISABLE_SHAPE=1
locust -f locustfile.py --host=$MPAI_BASE_URL --users 50 --spawn-rate 5 --run-time 10m --headless
```

## Docker

```bash
docker compose -f docker-compose.prod.yml run --rm \
  -e MPAI_TOKEN=... -e MPAI_BOT_ID=... -e MPAI_ASSERT_THRESHOLDS=1 \
  backend locust -f locustfile.py --host=http://api:8000 \
  --run-time 5m --headless --csv=/tmp/locust
```

## Staging

```bash
export MPAI_BASE_URL=https://staging.example.com
export MPAI_TOKEN=<staging jwt>
export MPAI_ASSERT_THRESHOLDS=1
locust -f locustfile.py --host=$MPAI_BASE_URL --run-time 15m --headless --csv=reports/staging
```

Use a dedicated load org / FREE-plan bots so 402s don't surprise you (they are treated as success).

## Interpreting results

| CSV | Meaning |
|-----|---------|
| `*_stats.csv` | Per-endpoint RPS, avg, p50/p95/p99, failures |
| `*_failures.csv` | Error samples |
| `*_stats_history.csv` | Time series for graphs |

**Pass:** execute p95 < 2s, fail_ratio < 0.01, no sustained 5xx.  
**Investigate:** p95 creep with users → LLM/RAG latency or DB pool; 401 → token; 402 storm → expected on FREE.

With `MPAI_ASSERT_THRESHOLDS=1`, Locust exits non-zero if thresholds breach.
