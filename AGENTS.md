# QoderRoute — Documentation for Coding Agents

This document provides structural, operational, and conventions guidance for agents interacting with or modifying QoderRoute. All information must match the actual codebase in this repository.

## Project Structure Map

```
QoderRoute/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI routers (HTTP endpoints)
│   │   │   ├── accounts.py       # CRUD, pool status, quota and traffic-stat endpoints
│   │   │   ├── chat.py           # /v1/chat/completions implementation
│   │   │   ├── anthropic.py      # /v1/messages + /v1/messages/count_tokens (Anthropic Messages API)
│   │   │   ├── models.py         # /v1/models + /api/models/catalog
│   │   │   ├── logs.py           # /api/logs (+ SSE streaming)
│   │   │   ├── settings.py       # Runtime settings (GET/PUT)
│   │   │   ├── status.py         # Model health snapshot
│   │   │   └── worker.py         # [gitignored; not in public build] optional trial-worker API
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings env vars (.env)
│   │   │   ├── database.py       # async engine, Base, init_db() with migrations
│   │   │   └── __init__.py
│   │   ├── models/               # SQLAlchemy ORM models & schemas
│   │   │   ├── account.py        # Account table (PAT, plan, quota, usage fields)
│   │   │   ├── app_setting.py    # AppSetting table (key/value DB-backed settings)
│   │   │   ├── pool_counter.py   # PoolCounter table (lifetime credits_spent counter)
│   │   │   └── schemas.py        # Pydantic models: AccountCreate/Out, ChatCompletion*, DashboardStats*
│   │   ├── services/             # Business logic services
│   │   │   ├── account_pool.py   # AccountPool class (rotation, refresh, mark_success/failure)
│   │   │   ├── direct_client.py      # Build native request body, run_infer generator (signer→upstream stream)
│   │   │   ├── logbus.py               # In-memory ring buffer + SSE subscribers
│   │   │   ├── model_catalog.py         # Canonical model keys, credit factors and capabilities
│   │   │   ├── model_probe.py          # Periodic TPS probes per model level
│   │   │   ├── quota_service.py        # Job token exchange, plan/quota/userinfo fetch from openapi.qoder.sh
│   │   │   ├── qoder_version.py        # Cosy/CLI version from npm @qoder-ai/qodercli (auto-refresh)
│   │   │   ├── settings_service.py     # In-memory cache of DB-backed settings with _DEFAULTS registry
│   │   │   ├── signer_service.py       # Signer singleton management (ensure_signer, supervisor, post_to_signer)
│   │   │   ├── worker_runner.py        # [gitignored; not in public build] optional worker runner
│   │   │   └── worker_pool.py          # [gitignored; not in public build] optional worker pool
│   │   ├── utils/
│   │   │   └── __init__.py
│   │   └── main.py                   # FastAPI app factory, lifespan, static mounting, router registration
│   ├── data/                         # SQLite DB, logs, pidfiles (gitignored)
│   ├── signer/
│   │   ├── qoder_auth_wasm.wasm      # WASM auth module shipped in-repo for the Node signer
│   │   ├── signer_server.mjs         # Node.js HTTP server on 127.0.0.1:8123 (WASM glue)
│   │   └── signer.log/pid/.start.lock (runtime files)
│   ├── tests/                        # [gitignored, local only] pytest regression suite
│   │   ├── conftest.py
│   │   ├── test_model_catalog.py
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
│   │   │   ├── models/Models.tsx               # Catalog, canonical keys and credit multipliers
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
├── .gitignore                                    # Excludes builds, data, local tests, optional worker and secrets
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

The regression suite is local and gitignored. Run it only when `backend/tests/` exists in the current checkout:

- **Run All Tests:**  
  ```bash
  cd backend && python3 -m pytest tests/
  ```
  Requires `pytest` and `pytest-asyncio` installed separately (not in `requirements.txt`). A clean public clone does not contain `backend/tests/`.

## Conventions

- **Routers:** Each feature's HTTP routes are defined in a dedicated file under `backend/app/api/`. These are included in `app/main.py` via `app.include_router()`. The Anthropic router (`anthropic.py`) translates the Anthropic Messages API (block content, `input_schema` tools, named SSE events) onto the same `direct_client.run_infer` pipeline as `chat.py`, reusing its account swap / queue-retry / error-classification helpers via imports from `app.api.chat`.

- **Business Logic:** Implementation lives in `backend/app/services/`. Key services:
  - `account_pool.py`: Account rotation, quota tracking, and success/failure bookkeeping.
  - `model_catalog.py`: Single source of truth for public model keys, names, credit factors, context windows and Reasoning/Thinking capabilities.
  - `model_probe.py`: Probes only the canonical keys selected by the `probe_model_keys` runtime setting.
  - `quota_service.py`: PAT validation, job token exchange, plan/quota userinfo fetching.
  - `direct_client.py`: Builds the native Qoder request shape, delegates to signer `/infer`, parses upstream SSE (including encrypted events).
  - `settings_service.py`: Central registry `_DEFAULTS` keyed by setting name; reads/writes DB with in-memory cache for zero-latency reads. New settings must be added here.

- **Data Models:** SQLAlchemy models in `backend/app/models/*.py`. Pydantic schemas (request/response models) consolidated in `backend/app/models/schemas.py`.

- **Frontend Organization:** Components are organized by feature folder (`components/accounts`, `components/settings`, etc.). State is managed via TanStack Query with hooks in `hooks/useApi.ts`. Types live in `types/index.ts`.

- **Settings Registry:** `settings_service.py` defines `_DEFAULTS` dict at module scope. Every new runtime setting requires three updates:
  1. Add key with default value to `_DEFAULTS`.
  2. Update `SettingsUpdate` schema in `backend/app/api/settings.py` to accept the field.
  3. Add the property to `AppSettings` type in `frontend/src/types/index.ts`.
  List-valued settings such as `probe_model_keys` are JSON-serialized in the key/value settings table and must return detached list copies from `snapshot()`.

- **Signer Lifecycle:** The signer is a Node.js server at `127.0.0.1:8123`. It is started exactly once by `signer_service.ensure_signer()` which uses a filesystem lock (`backend/signer/.start.lock`) to avoid duplicate spawns. A background supervisor (`signer_supervisor()`) monitors health and restarts the signer if it exits unexpectedly. Because the signer is detached (`start_new_session=True`), it survives backend process replacement.

## Gotchas

- **429 / Rate-Limit Is NOT Quota Exhaustion**  
  `looks_like_quota_error()` deliberately excludes 429/rate-limit markers — those are transient backpressure handled via `looks_like_rate_limit()` and the normal failure-cooldown path. Only genuine quota markers (`quota`, `credits exhausted`, `isquotaexceeded`, `insufficient credits`) park an account. Never add rate-limit patterns back into the quota matcher: with auto-delete enabled that silently destroys healthy accounts.

- **Backend Datetimes Are Naive UTC**  
  `_utcnow()` stores naive UTC datetimes; JSON responses contain strings like `"2026-08-11T10:00:00"` with no offset marker. The frontend MUST parse them as UTC (`lib/utils.ts: parseUtc` appends `Z`) — plain `new Date(s)` would parse them as browser-local time. Epoch-float fields (`plan_end_date`, `quota_expires_at`, `*_fetched_at`) are milliseconds and unaffected.

- **Plan Display Names Come From Quota Size**  
  The Qoder plan endpoint cannot distinguish paid tiers. `quota_service._plan_name_from_quota()` maps `quota_total` to names: ≥2,000 → Pro Plan, ≥6,000 → Pro+ Plan, ≥20,000 → Ultra Plan. Trial tiers (`personal_professional_trial`) keep the API-reported name. Do not "fix" this by trusting `plan_tier_name` for paid tiers.

- **Worker Files Are GitIgnored & Conditionally Imported**  
  The optional worker/trial activation modules (`worker.py`, `worker_runner.py`, `worker_pool.py`, and the frontend `worker/` directory) are gitignored and not shipped in the public build. Imports are guarded:
  - Frontend: `import.meta.glob()` in `lib/features.ts` resolves to `undefined` when absent; `WORKER_ENABLED` and `WorkerPage` become falsy/null.
  - Backend: `try/except ImportError` in `app/main.py` allows startup without these modules. Do not assume their presence in tests or production builds where they are excluded.

- **The Test Suite Is Local and GitIgnored**
  `backend/tests/` is deliberately excluded from Git. It may exist in the shared development workspace, but a clean clone will not contain it. Do not make production imports depend on tests, and do not claim tests were run unless the directory is actually present.

- **Exhausted Accounts Are Not Polled**  
  The background quota loop (`_quota_refresher`) only refreshes non-exhausted accounts (`is_quota_exceeded == False`). Exhausted accounts remain untouched until manually refreshed via `/api/accounts/{id}/quota/refresh` — which, when credits are back, also restores `is_available`, clears cooldown/failures, and rejoins routing immediately. With `accounts_auto_delete_exhausted` enabled, parking is replaced by deletion.

- **Concurrent Delete vs In-Flight Request**  
  `mark_success` / `mark_failure` catch `StaleDataError`: an account deleted (manual or auto-sweep) while its request was streaming must not turn a successful completion into a 500. Keep these handlers in place when editing bookkeeping code.

- **Account Deletion Invalidates Multiple Query Keys**  
  Deleting an account triggers immediate cache invalidation in `useDeleteAccount()`:
  ```ts
  ['pool-status'], ['dashboard-stats'], ['accounts', 'available'], ['accounts', 'exhausted']
  ```
  Any agent implementing similar mutations must invalidate these four query keys to keep the UI consistent.

- **Model Keys vs Display Names**  
  The public endpoint `/v1/models` returns model objects with `id` set to canonical catalog keys (for example `qmodel_38max`, `cmodel`, `ultimate`). Clients should pass these exact strings. Friendly names such as `"Qwen3.8-Max"` are normalized by `resolve_model_level()`, but canonical IDs are preferred. `qmodel_preview` is a private compatibility key and must not be advertised as Qwen3.8-Max.

- **Model Catalog Is the Single Source of Truth**
  Add or change public models in `services/model_catalog.py`; do not independently hardcode another public list in routing, API handlers, probes, or the frontend. `QODER_MODEL_DISPLAY`, `/v1/models`, `/api/models/catalog`, `MODEL_KEY_MAP`, account selectors, and probe choices must stay derived from this catalog. Credit factors are base multipliers; actual upstream billing can vary.

- **Reasoning and Thinking Are Different Capabilities**
  `is_reasoning` mirrors Qoder's model classification. `supports_thinking` mirrors the presence of `thinking_config`. Kimi-K3 (`kmodel_latest`) is the important counterexample: `is_reasoning=false`, but thinking is enabled with `low/high/max` effort and defaults to `max`. Kimi-K2.7-Code (`kmodel`) has no thinking config in the current catalog. Never infer thinking support from `is_reasoning` alone.

- **Model Probes Spend Real Credits**
  `probe_model_keys` controls exactly which routes are probed. The safe default is the named catalog models, including Qwen3.8-Flash (`qfmodel`) and GLM-5.3-Flash (`gfmodel`); Cantus (`3.2×`) and generic tiers are opt-in. An empty list is valid and probes nothing. Selection changes apply on the next cycle, and stale status results for deselected models are filtered from the API snapshot.

- **Reasoning Effort Defaults**  
  `_normalize_effort` defaults to the model peak (`max`, or `xhigh` for `qmodel_38max` / `qfmodel`) only when the OpenAI client omits `reasoning_effort`. An explicit client value is honored as-is; bare `max` on the Qwen3.8 routes is rewritten to `xhigh`. For those two keys, explicit `reasoning_effort` / `enable_thinking` are still omitted from the upstream body when the client did not send an effort, because that provider rejects inventing the switches.

- **Account Name Defaults From Userinfo**  
  `POST /api/accounts` accepts an optional `name`. If omitted or blank, `quota_service.resolve_account_name` uses `/api/v1/userinfo` (`name` / `username` / `user_name`, same keys as the CLI credential record), then email, then `"account"`.

- **No Per-Account Disable**  
  Accounts cannot be toggled inactive. Startup backfill forces `is_active = 1` for any legacy disabled rows; the column remains only so existing pool filters keep working.

- **Near-Exhaustion Spill Under Concurrency**  
  Fill-first still sticks to one PAT while healthy. When `quota_remaining <= 15` and that account already has an in-flight request, additional starts spill to the next available account. `begin_request` re-checks DB routability before upstream work; SSE reading stops on the first upstream error so hung post-quota connections do not burn the 300s timeout.

- **Cosy/CLI Version Auto-Refresh**  
  Do not hardcode `Cosy-Version` / `business.version` / `qoder/<ver>` User-Agent. `qoder_version.py` fetches `@qoder-ai/qodercli` latest from npm on startup and every 6 hours, then feeds `quota_service`, `direct_client`, and the signer `/infer` payload (`cosy_version`). Fallback stays in memory if npm is unreachable. `/api/health` exposes `qoder_cli_version` + source.

- **Context Window Parameter Placement**  
  The `context_length` parameter inside the request body sets the reservation; putting the same value in `model_config.context_window` has no effect on the inference path. Use only `parameters.context_length`.

- **Live Logs Replay Strategy**  
  `/api/logs/stream` first yields ~100 recent events then subscribes. Clients using `EventSource` should maintain idempotent event processing because reconnection will replay the tail again. The sequence number (`seq`) can be used to skip duplicates.

- **Usage Activity Counts Completion Log Spellings**  
  `/api/accounts/stats/activity` aggregates only log events whose `message` matches an entry in `_COMPLETION_MESSAGES` in `backend/app/api/accounts.py` — currently `"stream done"`, `"completion ok"`, `"anthropic stream done"`, `"anthropic completion ok"`. A new endpoint dialect that logs a different completion message must register it there, or its traffic silently drops out of the Usage charts (this exact bug hid all Anthropic traffic from the dashboard).

- **10605 Queue Payloads Must Stay JSON-Parsed**  
  The 403 handler in `direct_client.run_infer` extracts the inner `{"code":"10605",...}` payload via `_extract_queue_payload` (json.loads on the substring from `{`). The API layer's `parse_model_queue` reads `isQueued` from that message to drive the quiet retry. Do not replace this with string `replace()` tricks — stripping `"upstream status "` left a `403:` prefix behind and blanket-unescaping broke quoted values, so the retry never fired and clients got 503s instead.

## Data Flow Summary: Chat Request

1. **Ingest:** Client POSTs JSON to `POST /v1/chat/completions` with `messages`, optionally `tools`, `reasoning_effort`, `fast`, `context_window`, `max_tokens`. Body validated by `ChatCompletionRequest` schema.

2. **Resolve Model:** `resolve_model_level(request.model)` normalizes input against `model_catalog.py` to a canonical level key (e.g., `"qmodel_38max"`).

3. **Select Account:** `pool.get_next_account(db, exclude_ids=set())` selects the first `is_active && is_available && !is_quota_exceeded && cooldown_ok` account ordered by priority desc, id asc.

4. **Prepare Upstream Request:** `direct_client.run_infer(pat, model_level, messages, ...)` performs:
   - Job token exchange via `quota_service.get_job_token(pat)` (cached).
   - User info extraction for UID via `quota_service.get_uid(pat)`.
   - Build native body (`_build_body`): system/history split, context strings, business envelope, parameters (`max_tokens`, `context_length`, `enable_thinking`, `reasoning_effort`).
   - Call signer `POST /infer` with `{jt, uid, machine_id, base_url, body_json, model_key, model_source}`. Signer returns `{url, headers, body_b64}`.

5. **Stream from Qoder:** Backend streams POST to the returned URL. SSE lines are buffered and decoded (with decryption via signer `/decrypt` when necessary). Events emitted: `text`, `thinking`, `reasoning_item`, `reasoning_signature`, `tool_calls`, `function_call`, `done`, `error`.

6. **Map to OpenAI Chunks:** In streaming mode, each SSE chunk from Qoder is wrapped into OpenAI-style `chat.completion.chunk` format and yielded via `StreamingResponse`. Final chunk includes usage metrics and finish_reason.

7. **Bookkeeping:** On `done`:
   - `pool.mark_success(account_id, tokens_used, credits_used)` updates counters and local quota estimates.
   - Log entry pushed via `logbus.push("info", "chat", ...)`.
   - Usage stats reflected immediately in dashboard traffic queries.

8. **Failure Handling:** Errors classified by source (infrastructure, quota, model_queue, account):
   - Infrastructure: raise HTTPException (immediate failure).
   - Quota: `pool.mark_quota_exceeded()` and swap to next account (retry up to MAX_SWAP_ATTEMPTS=3).
   - Model queue (10605): retry once after delay if `isQueued=false`; otherwise fail.
   - Account error: `pool.mark_failure()` with exponential cooldown backoff; raise HTTPException.

9. **Completion Response:** Streaming mode yields SSE; non-streaming mode aggregates text/thinking/tool calls/function call/signature and returns `ChatCompletionResponse`.

## Testing Conventions

- **Availability:** `backend/tests/` is a gitignored local suite. Check that it exists before planning or reporting test work; it is absent from a clean public clone.

- **Framework:** When present, the suite uses `pytest` with `pytest.mark.asyncio` for async tests.

- **Setup:** `conftest.py` ensures the backend root is importable. Services rely on dependency injection patterns; mocks can patch `async_session` or individual service methods.

- **Async Patterns:** Use `async def` test functions with `await` throughout. Mock external calls (`httpx.AsyncClient`, signer service) where appropriate to isolate unit behavior.

- **Coverage Examples:**
  - `test_signer_resilience.py`: Tests concurrent ensure-signer locking, recovery loops.
  - `test_runtime_settings.py`: Validates SettingsUpdate schema constraints for known keys.
  - `test_model_catalog.py`: Verifies catalog metadata, canonical routing identities, API output, and runtime probe selection.
  - `test_thinking_regression.py`: Verifies correct model config (context length, reasoning enums) for specific model levels.

When writing new tests, follow existing patterns: define fake sessions/repositories for isolation, mock network calls, and assert both side-effects (session state changes) and return values.
