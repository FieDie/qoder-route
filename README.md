# QoderRoute

QoderRoute is an OpenAI-compatible proxy router for Qoder (qoder.sh). It maintains a pool of Qoder accounts (via PAT tokens), accepts requests formatted for the OpenAI chat API at `/v1/chat/completions` and model listings at `/v1/models`, signs outbound requests through a Node.js WASM sidecar, forwards them to Qoder upstream endpoints (`api1/2/3.qoder.sh`), and automatically rotates between accounts when quota is exhausted. The project includes a React + TypeScript admin panel for monitoring accounts, quotas, model health, activity logs via SSE, and runtime settings.

## Features

- **Account Pool with Fill‑First Rotation**  
  Accounts are ordered by priority (descending) then ID (ascending). The first available account with remaining quota serves until it exhausts, then the next in line takes over. For Qwen3.8-Max (`qmodel_38max`), accounts whose credit quota is exhausted but that have an active free-call campaign are prioritized.

- **Quota Tracking & Plan Metadata**  
  Every account's plan tier, name, end date, and quota usage are fetched from `openapi.qoder.sh`. The background loop refreshes this every 5 minutes. Account cards display plan type, paid/free status, plan end date, and quota progress. When an account hits quota, it is parked and will automatically rejoin rotation once credits renew.

- **Free-Call Activity / Reward Support for Qwen3.8-Max**  
  Accounts can participate in the Qwen3.8-Max activity campaign (`qwen38_800_invoke`). The system checks eligibility, claims activity, fetches signed balances, and uses one free invocation per completion instead of deducting credits when the campaign is active.

- **Model Health Probes with TPS**  
  Periodic probes measure each exposed model's liveness and tokens-per-second (TPS). Status is shown on the Status page; probes respect the `probe_interval_minutes` setting (or run every minute if disabled).

- **Live Logs via SSE**  
  An SSE stream replays recent events then pushes new ones in real time (`GET /api/logs/stream`). Sources include chat completions, account events, provisioning, and activity updates.

- **Runtime Settings**  
  All configuration values are persisted in the database and editable via `/api/settings`. Options control log visibility, token/email/request display, auto-delete behavior for exhausted accounts, Qoder backend endpoint selection, and probe frequency.

- **Auto-Delete Exhausted Accounts Option**  
  When enabled, accounts marked as quota-exceeded are removed from the pool. A secondary option keeps an account if it still has an active free-call activity slot.

- **OpenAI-Compatible API**  
  The `/v1/chat/completions` endpoint accepts standard OpenAI request fields (messages, tools, reasoning_effort, context_window, max_tokens, etc.) and returns streaming SSE chunks matching the OpenAI response shape. `/v1/models` lists supported model tiers with display names.

## Architecture

```
+-----------+      HTTP          +--------------+      HTTP      +------------------+
|   Client   | ----------------> | FastAPI :8010 | -------------> | Signer :8123      |
+-----------+                   +--------------+                  | (Node.js/WASM)   |
                                                                  +------+-----------+
                                                                         |
                                                                         | HTTPS
                                                                         v
                                                                  +--------------+
                                                                  | Qoder Upstream |
                                                                  | api1/2/3.qoder |
                                                                  +----------------+

Data Layer:
  - SQLite: data/qoderroute.db (accounts, settings, counters)
  - Frontend: built from frontend/dist (SPA fallback served by FastAPI)

Background Loops:
  - Quota refresher: every 300 seconds (pool.refresh_all_quotas)
  - Model prober: configurable interval via settings
  - Signer supervisor: monitors signer process; restarts if unhealthy
```

## Requirements

- Python 3.11+
- Node.js 18+ (for the signer sidecar)
- npm (to build the frontend)

## Setup

### Prerequisites

The repo ships with the WASM auth module (`backend/signer/qoder_auth_wasm.wasm`, extracted from Qoder CLI 1.1.17) — no extra steps needed, the signer works out of the box.

### Backend Installation

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optionally configure environment variables in `.env` (see Configuration below). The backend reads these via pydantic-settings at startup.

### Frontend Build

```bash
cd frontend
npm install
npm run build
```

The build output is placed in `frontend/dist`. The production backend serves these files under `/` with SPA routing.

### Running the Server

**Production (no reload):**

```bash
cd backend
./start.sh
```

The server binds to `0.0.0.0:8010`. Use `./restart.sh` for a graceful restart that preserves the signer process.

**Development (auto-reload):**

```bash
cd backend
python3 run.py
```

This starts uvicorn with hot-reload enabled when `DEBUG=true` in `.env`.

**Frontend Development:**

```bash
cd frontend
npm run dev
```

Vite runs on `http://localhost:5173` and proxies `/api` and `/v1` to `http://localhost:8010`.

### Tests

```bash
cd backend
python3 -m pytest tests/
```

Install test dependencies separately (pytest and pytest-asyncio):

```bash
pip install pytest pytest-asyncio
```

## Configuration

Environment variables are loaded from `backend/.env` (pydantic-settings field mapping to UPPER_SNAKE_CASE). Common options:

| Variable                   | Default                              | Description                                             |
|----------------------------|--------------------------------------|---------------------------------------------------------|
| `DEBUG`                    | `True`                               | Enable debug mode / SQL echo                           |
| `HOST`                     | `0.0.0.0`                            | Host to bind to                                         |
| `PORT`                     | `8010`                               | HTTP port                                               |
| `DATABASE_URL`             | `sqlite+aiosqlite:///./data/qoderroute.db` | Database URL                                          |
| `JWT_SECRET`               | `qoderroute-super-secret-key...`     | Secret key for JWT authentication                       |
| `JWT_ALGORITHM`            | `HS256`                              | JWT algorithm                                           |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440`                             | Token expiration                                        |
| `QODERCLI_PATH`            | ``                                   | Path to qodercli binary (optional)                      |
| `QODER_POLL_INTERVAL`      | `300`                                | Seconds between pool refreshes                          |
| `ACCOUNT_COOLDOWN_SECONDS` | `30`                                 | Base backoff on consecutive failures                    |
| `MAX_CONSECUTIVE_FAILURES` | `3`                                  | Max failures before cooldown                            |
| `CORS_ORIGINS`             | `["http://localhost:5173", ...]`     | Allowed origins                                         |
| `DATA_DIR`                 | `./data`                             | Data directory path                                     |
| `QODER_WORKER_SCRIPT`      | ``                                   | Optional; enables extra API module not shipped in public build |
| `QODER_INFER_BASE`         | (settings-based default)             | Optional env override for Qoder backend (api1/api2/api3)|

Settings managed via `/api/settings` (stored in DB):

- `worker_logs_enabled`, `worker_retry_allow`
- `accounts_show_email`, `accounts_show_tokens`, `accounts_show_requests`
- `accounts_auto_delete_exhausted`, `accounts_auto_delete_keep_activity`
- `account_activity_checks_enabled`
- `qoder_infer_base` (`api1` | `api2` | `api3`)
- `probe_interval_minutes` (0 = disabled; otherwise 5–60 min steps)

## API Overview

**OpenAI-Compatible Endpoints**

- `POST /v1/chat/completions` — Chat completion (streaming SSE or JSON). Request schema follows `ChatCompletionRequest`. Accepts messages, tools, reasoning_effort, fast mode, context_window, max_tokens.
- `GET /v1/models` — List supported models with display names.

**Admin REST API**

- `GET POST /api/accounts` — List accounts or create a new account (PAT validation required). Includes filter views: `GET /api/accounts/available`, `GET /api/accounts/exhausted`.
- `GET /api/accounts/{id}` — Get account details.
- `PATCH /api/accounts/{id}` — Update account fields.
- `DELETE /api/accounts/{id}` — Delete account.
- `POST /api/accounts/{id}/quota/refresh` — Refresh quota for one account.
- `POST /api/accounts/quota/refresh-all` — Refresh all active accounts' quotas.
- `POST /api/accounts/activity/refresh-all` — Refresh activity balance for all active accounts.
- `GET /api/accounts/stats/dashboard` — Dashboard statistics.
- `GET /api/accounts/stats/activity` — Recent traffic aggregated by minute and model.
- `GET /api/accounts/models/list` — Available model tiers.
- `GET /api/status/models` — Model health snapshot (TPS, latency, alive/error).
- `GET /api/logs` — Recent log events.
- `GET /api/logs/stream` — SSE stream of live logs.
- `GET /api/settings` — Current settings.
- `PUT /api/settings` — Update settings.
- `GET /api/health` — Health check (200 ok, 503 degraded if signer unavailable).
- `GET /api/health/live` — Liveness probe (always OK).

## Development

- **Frontend Dev Server**: Run `npm run dev` inside `frontend/`. Vite listens on port 5173 and proxies `/api` and `/v1` to the backend. The dev server works even without building the production bundle first.

- **Backend Dev Mode**: Run `python3 run.py` from `backend/`. When `DEBUG=true`, uvicorn reloads on changes. Ensure the signer is running (it starts automatically with the backend via `ensure_signer` in lifespan).

- **Tests**: Located in `backend/tests/`. They use pytest with asyncio support. Command: `cd backend && python3 -m pytest tests/`. See conftest.py for session setup.

## License & Notice

This is an unofficial third-party project. It is not affiliated with, endorsed by, or associated with Qoder or its operators. Use at your own risk. This software redistributes authenticated user credentials (PAT tokens); ensure compliance with applicable terms of service and handle credentials securely.
