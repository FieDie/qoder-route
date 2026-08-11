# QoderRoute — Documentation for Coding Agents

This document provides structural, operational, and conventions guidance for agents interacting with or modifying QoderRoute. All information must match the actual codebase under `/home/bro/devy/QoderRoute`.

## Project Structure Map

```
/home/bro/devy/QoderRoute/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI routers (HTTP endpoints)
│   │   │   ├── accounts.py       # CRUD, pool status, stats, quota/activity endpoints
│   │   │   ├── chat.py           # /v1/chat/completions implementation
│   │   │   ├── models.py         # /v1/models listing
│   │   │   ├── logs.py           # /api/logs (+ SSE streaming)
│   │   │   ├── settings.py       # Runtime settings (GET/PUT)
│   │   │   ├── status.py         # Model health snapshot
│   │   │   └── worker.py         # [gitignored; not in public build] optional trial-worker API
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings env vars (.env)
│   │   │   ├── database.py       # async engine, Base, init_db() with migrations
│   │   │   └── __init__.py
│   │   ├── models/               # SQLAlchemy ORM models & schemas
│   │   │   ├── account.py        # Account table (PAT, quota, activity fields)
│   │   │   ├── app_setting.py    # AppSetting table (key/value DB-backed settings)
│   │   │   ├── pool_counter.py   # PoolCounter table (lifetime credits_spent counter)
│   │   │   └── schemas.py        # Pydantic models: AccountCreate/Update/Out, ChatCompletion*, DashboardStats*
│   │   ├── services/             # Business logic services
│   │   │   ├── account_pool.py   # AccountPool class (rotation, refresh, mark_success/failure)
│   │   │   ├── activity_service.py   # Eligibility claim, signed balance for qwen38_800_invoke
│   │   │   ├── direct_client.py      # Build native request body, run_infer generator (signer→upstream stream)
│   │   │   ├── logbus.py               # In-memory ring buffer + SSE subscribers
│   │   │   ├── model_probe.py          # Periodic TPS probes per model level
│   │   │   ├── quota_service.py        # Job token exchange, plan/quota/userinfo fetch from openapi.qoder.sh
│   │   │   ├── settings_service.py     # In-memory cache of DB-backed settings with _DEFAULTS registry
│   │   │   ├── signer_service.py       # Signer singleton management (ensure_signer, supervisor, post_to_signer)
│   │   │   ├── worker_runner.py        # [gitignored; not in public build] optional worker runner
│   │   │   └── worker_pool.py          # [gitignored; not in public build] optional worker pool
│   │   ├── utils/
│   │   │   └── __init__.py
│   │   └── main.py                   # FastAPI app factory, lifespan, static mounting, router registration
│   ├── data/                         # SQLite DB, logs, pidfiles (gitignored)
│   ├── signer/
│   │   ├── qoder_auth_wasm.wasm      # Required WASM auth module (Qoder CLI 1.1.17 extracted) NOT IN PUBLIC REPO
│   │   ├── signer_server.mjs         # Node.js HTTP server on 127.0.0.1:8123 (WASM glue)
│   │   └── signer.log/pid/.start.lock (runtime files)
│   ├── tests/                        # pytest test suite (asyncio)
│   │   ├── conftest.py
│   │   ├── test_activity_service.py
│   │   ├── test_runtime_settings.py
│   │   ├── test_signer_resilience.py
│   │   └── test_thinking_regression.py
│   ├── requirements.txt              # Python deps: fastapi, uvicorn, sqlalchemy, httpx, etc.
│   ├── restart.sh                    # Graceful restart script (waits for old process to exit)
│   ├── run.py                        # Dev mode: uvicorn.run with reload if DEBUG
│   └── start.sh                      # Prod start script (no reload, flock-based guards)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── accounts/AccountManager.tsx     # Accounts tab with available/exhausted views
│   │   │   ├── layout/AppLayout.tsx            # Sidebar nav + Routes
│   │   │   ├── logs/Logs.tsx                   # SSE live logs component
│   │   │   ├── settings/Settings.tsx           # Runtime settings form
│   │   │   ├── status/Status.tsx               # Model probes TPS/status cards
│   │   │   ├── ui/GlassPanel.tsx               # Shared UI components (Card, Badge, Skeleton)
│   │   │   ├── worker/                         # [gitignored; not in public build] optional worker page
│   │   │   └── chat/                           # Optional chat client component (main project only)
│   │   ├── hooks/
│   │   │   ├── useApi.ts                       # TanStack Query hooks (usePoolStatus, useDashboardStats, etc.)
│   │   │   └── useCountUp.ts                   # Utility hook
│   │   ├── lib/
│   │   │   ├── features.ts                     # Conditional imports for optional modules (WORKER_ENABLED, WorkerPage lazy loader)
│   │   │   └── utils.ts                        # Formatting utilities (timeAgo, cn helpers)
│   │   ├── types/index.ts                      # TS types matching backend responses (Account, AppSettings, etc.)
│   │   ├── App.tsx                             # Root component (QueryClientProvider + BrowserRouter)
│   │   ├── main.tsx                            # Entry point
│   │   └── index.css                           # Tailwind styles + globals
│   ├── public/qoder.svg                        # Static favicon
│   ├── index.html                              # SPA entry
│   ├── package.json                            # Frontend dependencies (@tanstack/react-query, framer-motion, recharts)
│   ├── tsconfig.json
│   ├── vite.config.ts                          # Server port 5173, proxy /api & /v1 → localhost:8010
│   ├── tailwind.config.js
│   └── postcss.config.js
├── .gitignore                                    # Excludes node_modules, dist, data/, *.db, *.log, worker/, credentials.env
├── README.md                                     # User-facing documentation
└── AGENTS.md                                     # This file
```

## Build/Run/Test Commands

### Backend

- **Prod Start (no reload):**  
  ```bash
  cd backend && ./start.sh
  ```
  Runs `uvicorn app.main:app` bound to `0.0.0.0:8010`, writes logs to `data/server.log`.

- **Graceful Restart:**  
  ```bash
  cd backend && ./restart.sh
  ```
  Waits for the existing backend process to fully exit (active streams drain), refuses overlapping backends. The signer is a host-level singleton and survives this restart. Optional env `QODERROUTE_FORCE_RESTART_AFTER=N` to force-kill after N seconds.

- **Dev Mode (reload):**  
  ```bash
  cd backend && python3 run.py
  ```
  Uses `DEBUG` setting for auto-reload.

### Frontend

- **Build for Production:**  
  ```bash
  cd frontend && npm install && npm run build
  ```
  Produces `frontend/dist/` served by FastAPI as static assets + SPA fallback.

- **Development Server:**  
  ```bash
  cd frontend && npm run dev
  ```
  Vite runs on `http://localhost:5173` with proxies `/api` and `/v1` to `http://localhost:8010`.

### Tests

- **Run All Tests:**  
  ```bash
  cd backend && python3 -m pytest tests/
  ```
  Requires `pytest` and `pytest-asyncio` installed separately (not in `requirements.txt`). The suite uses `@pytest.mark.asyncio` decorators and relies on `conftest.py` for path setup.

## Conventions

- **Routers:** Each feature's HTTP routes are defined in a dedicated file under `backend/app/api/`. These are included in `app/main.py` via `app.include_router()`.

- **Business Logic:** Implementation lives in `backend/app/services/`. Key services:
  - `account_pool.py`: Account rotation, quota tracking, success/failure bookkeeping, free-call activity usage for `qmodel_38max`.
  - `quota_service.py`: PAT validation, job token exchange, plan/quota userinfo fetching.
  - `direct_client.py`: Builds the native Qoder request shape, delegates to signer `/infer`, parses upstream SSE (including encrypted events).
  - `settings_service.py`: Central registry `_DEFAULTS` keyed by setting name; reads/writes DB with in-memory cache for zero-latency reads. New settings must be added here.

- **Data Models:** SQLAlchemy models in `backend/app/models/*.py`. Pydantic schemas (request/response models) consolidated in `backend/app/models/schemas.py`.

- **Frontend Organization:** Components are organized by feature folder (`components/accounts`, `components/settings`, etc.). State is managed via TanStack Query with hooks in `hooks/useApi.ts`. Types live in `types/index.ts`.

- **Settings Registry:** `settings_service.py` defines `_DEFAULTS` dict at module scope. Every new runtime setting requires three updates:
  1. Add key with default value to `_DEFAULTS`.
  2. Update `SettingsUpdate` schema in `backend/app/api/settings.py` to accept the field.
  3. Add the property to `AppSettings` type in `frontend/src/types/index.ts`.

- **Signer Lifecycle:** The signer is a Node.js server at `127.0.0.1:8123`. It is started exactly once by `signer_service.ensure_signer()` which uses a filesystem lock (`backend/signer/.start.lock`) to avoid duplicate spawns. A background supervisor (`signer_supervisor()`) monitors health and restarts the signer if it exits unexpectedly. Because the signer is detached (`start_new_session=True`), it survives backend process replacement.

## Gotchas

- **Worker Files Are GitIgnored & Conditionally Imported**  
  The optional worker/trial activation modules (`worker.py`, `worker_runner.py`, `worker_pool.py`, and the frontend `worker/` directory) are gitignored and not shipped in the public build. Imports are guarded:
  - Frontend: `import.meta.glob()` in `lib/features.ts` resolves to `undefined` when absent; `WORKER_ENABLED` and `WorkerPage` become falsy/null.
  - Backend: `try/except ImportError` in `app/main.py` allows startup without these modules. Do not assume their presence in tests or production builds where they are excluded.

- **Exhausted Accounts Are Not Polled**  
  The background quota loop (`_quota_refresher`) only refreshes non-exhausted accounts (`is_quota_exceeded == False`). Exhausted accounts remain untouched until manually refreshed via `/api/accounts/{id}/quota/refresh` (which may un-park them if credits are renewed). This prevents unnecessary traffic to users that have truly exited rotation.

- **Account Deletion Invalidates Multiple Query Keys**  
  Deleting an account triggers immediate cache invalidation in `useDeleteAccount()`:
  ```ts
  ['pool-status'], ['dashboard-stats'], ['accounts', 'available'], ['accounts', 'exhausted']
  ```
  Any agent implementing similar mutations must invalidate these four query keys to keep the UI consistent.

- **Model Keys vs Display Names**  
  The public endpoint `/v1/models` returns model objects with `id` set to internal level keys (e.g., `qmodel_38max`). Clients sending requests should pass these exact strings. Friendly names like `"Qwen3.8-Max"` or `"qwer-3.8-max"` are normalized by `resolve_model_level()` but relying on normalization adds fragility—prefer canonical IDs.

- **Qwen3.8-Max Reasoning Effort Mapping**  
  For `qmodel_38max`, the supported effort enum value is `xhigh`, not `max`. `direct_client._MAX_REASONING_EFFORT_BY_MODEL` maps this automatically, but any custom request builders must respect it to avoid upstream rejections.

- **Context Window Parameter Placement**  
  The `context_length` parameter inside the request body sets the reservation; putting the same value in `model_config.context_window` has no effect on the inference path. Use only `parameters.context_length`.

- **Live Logs Replay Strategy**  
  `/api/logs/stream` first yields ~100 recent events then subscribes. Clients using `EventSource` should maintain idempotent event processing because reconnection will replay the tail again. The sequence number (`seq`) can be used to skip duplicates.

## Data Flow Summary: Chat Request

1. **Ingest:** Client POSTs JSON to `POST /v1/chat/completions` with `messages`, optionally `tools`, `reasoning_effort`, `fast`, `context_window`, `max_tokens`. Body validated by `ChatCompletionRequest` schema.

2. **Resolve Model:** `resolve_model_level(request.model)` normalizes input to a canonical level key (e.g., `"qmodel_38max"`). For Qwen3.8-Max special routing rules apply.

3. **Select Account:** `pool.get_next_account(db, exclude_ids=set(), model_level=key)` executes:
   - If `model_level == "qmodel_38max"`, check exhausted-credit accounts with active `qwen38_800_invoke` campaign first.
   - Otherwise, select first `is_active && is_available && !is_quota_exceeded && cooldown_ok` account ordered by priority desc, id asc.

4. **Prepare Upstream Request:** `direct_client.run_infer(pat, model_level, messages, ...)` performs:
   - Job token exchange via `quota_service.get_job_token(pat)` (cached).
   - User info extraction for UID via `quota_service.get_uid(pat)`.
   - Build native body (`_build_body`): system/history split, context strings, business envelope, parameters (`max_tokens`, `context_length`, `enable_thinking`, `reasoning_effort`).
   - Call signer `POST /infer` with `{jt, uid, machine_id, base_url, body_json, model_key, model_source}`. Signer returns `{url, headers, body_b64}`.

5. **Stream from Qoder:** Backend streams POST to the returned URL. SSE lines are buffered and decoded (with decryption via signer `/decrypt` when necessary). Events emitted: `text`, `thinking`, `reasoning_item`, `reasoning_signature`, `tool_calls`, `function_call`, `done`, `error`.

6. **Map to OpenAI Chunks:** In streaming mode, each SSE chunk from Qoder is wrapped into OpenAI-style `chat.completion.chunk` format and yielded via `StreamingResponse`. Final chunk includes usage metrics and finish_reason.

7. **Bookkeeping:** On `done`:
   - `pool.mark_success(account_id, tokens_used, credits_used, model_level)` updates counters. If activity consumed was used, credits are zeroed locally but upstream credits are logged.
   - Log entry pushed via `logbus.push("info", "chat", ...)`.
   - Usage stats reflected immediately in dashboard/activity queries.

8. **Failure Handling:** Errors classified by source (infrastructure, quota, model_queue, account):
   - Infrastructure: raise HTTPException (immediate failure).
   - Quota: `pool.mark_quota_exceeded()` and swap to next account (retry up to MAX_SWAP_ATTEMPTS=3).
   - Model queue (10605): retry once after delay if `isQueued=false`; otherwise fail.
   - Account error: `pool.mark_failure()` with exponential cooldown backoff; raise HTTPException.

9. **Completion Response:** Streaming mode yields SSE; non-streaming mode aggregates text/thinking/tool calls/function call/signature and returns `ChatCompletionResponse`.

## Testing Conventions

- **Framework:** `pytest` with `pytest.mark.asyncio` for async tests. Tests live in `backend/tests/`.

- **Setup:** `conftest.py` ensures the backend root is importable. Services rely on dependency injection patterns; mocks can patch `async_session` or individual service methods.

- **Async Patterns:** Use `async def` test functions with `await` throughout. Mock external calls (`httpx.AsyncClient`, signer service) where appropriate to isolate unit behavior.

- **Coverage Examples:**
  - `test_signer_resilience.py`: Tests concurrent ensure-signer locking, recovery loops.
  - `test_runtime_settings.py`: Validates SettingsUpdate schema constraints for known keys.
  - `test_activity_service.py`: Covers eligibility checks, claim outcomes, rowcount expectations.
  - `test_thinking_regression.py`: Verifies correct model config (context length, reasoning enums) for specific model levels.

When writing new tests, follow existing patterns: define fake sessions/repositories for isolation, mock network calls, and assert both side-effects (session state changes) and return values.
