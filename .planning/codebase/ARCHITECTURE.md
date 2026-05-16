<!-- refreshed: 2026-05-16 -->
# Architecture

**Analysis Date:** 2026-05-16

## System Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│              Desktop Shell  (Tauri v2 + Rust)                          │
│  `frontend/src-tauri/src/main.rs` → `lib.rs`                          │
│                                                                        │
│  bootstrap.rs   tools.rs   backend.rs   commands.rs   config.rs       │
│  (venv + uv)  (sidecar)  (spawn uvicorn) (IPC cmds) (region/hotkey)  │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │ spawns subprocess  /  IPC invoke
                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│              React 18 SPA  (Vite + JSX)                                │
│  `frontend/src/main.jsx` → `main-app.jsx` → `App.jsx`                 │
│                                                                        │
│  pages/          components/         hooks/           store/           │
│  (full views)   (shared UI)       (data logic)   (Zustand slices)     │
│                                                                        │
│  api/client.ts → fetch → http://127.0.0.1:3900                        │
│  hooks/useRealtimeEvents.js → ws://127.0.0.1:3900/ws/events           │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │ HTTP REST + WebSocket
                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│              FastAPI Backend  (Python 3.11 / uvicorn)                  │
│  `backend/main.py`  — app factory, lifespan, 22 routers               │
│                                                                        │
│  api/routers/      services/          core/                           │
│  (HTTP handlers)  (ML + pipeline)  (db, config, tasks, event_bus)     │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │ Python import
                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│              OmniVoice Model Package                                   │
│  `omnivoice/models/omnivoice.py`  (lazy-loaded on first generate)     │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  SQLite  (`omnivoice.db` in platform data dir)                        │
│  + file system outputs (outputs/, voices/, dub_jobs/, preview/)       │
└───────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Key Files |
|-----------|----------------|-----------|
| Tauri shell | Desktop window management, sidecar bootstrap, IPC commands | `frontend/src-tauri/src/lib.rs`, `bootstrap.rs`, `backend.rs` |
| React SPA | All UI rendering, client-side state, API calls | `frontend/src/App.jsx`, `frontend/src/main-app.jsx` |
| Zustand store | Persistent + transient app state, slice composition | `frontend/src/store/index.ts` |
| API layer | Typed wrappers around every backend endpoint | `frontend/src/api/client.ts`, `frontend/src/api/*.ts` |
| FastAPI app | HTTP routing, middleware, lifespan startup/shutdown | `backend/main.py` |
| Routers | Thin HTTP handlers (one file per domain) | `backend/api/routers/*.py` |
| Services | ML inference, dubbing pipeline, DSP, ASR, translation | `backend/services/*.py` |
| Core | DB init/migrations, config, task queue, event bus, job store | `backend/core/*.py` |
| Model package | TTS model weights + inference class | `omnivoice/models/omnivoice.py` |
| MCP server | AI-agent tool interface (stdio or SSE) | `backend/mcp_server.py` |
| Plugin SDK | Abstract base + registry for third-party TTS engines | `backend/services/plugin_sdk.py` |

## Pattern Overview

**Overall:** Layered monolith with an async task queue — a single FastAPI process owns all ML inference, routing, and persistence. The desktop shell is a thin Tauri wrapper that spawns the Python backend as a subprocess sidecar.

**Key Characteristics:**
- No microservices; all backend logic in one Python process on port 3900
- React SPA deployed as static files served by the same FastAPI process (`/`) in production; Vite dev server in development
- ML inference always offloaded to a single-threaded `ThreadPoolExecutor` (`_gpu_pool`) to avoid GIL contention with FastAPI's async event loop
- Real-time UI updates driven by a WebSocket event bus (`/ws/events`) instead of polling
- SQLite with WAL mode for all persistence; no ORM — raw `sqlite3` with a context-managed `db_conn()` helper

## Layers

**Desktop Shell (Rust/Tauri):**
- Purpose: OS integration — window, tray icon, single-instance, global shortcut
- Location: `frontend/src-tauri/src/`
- Contains: Bootstrap state machine, subprocess management, Tauri IPC commands
- Depends on: Python backend (HTTP health probe), `uv`, `ffmpeg`/`ffprobe` sidecars
- Used by: End user on macOS/Windows/Linux desktop

**React Frontend:**
- Purpose: Full application UI
- Location: `frontend/src/`
- Contains: Pages, components, custom hooks, Zustand slices, typed API wrappers
- Depends on: Backend REST API (HTTP), backend WebSocket (`/ws/events`)
- Used by: Tauri webview in desktop mode; any browser in server/web mode

**FastAPI Routers:**
- Purpose: HTTP boundary — validate requests, delegate to services, return responses
- Location: `backend/api/routers/`
- Contains: 22 routers covering generation, dubbing, profiles, projects, setup, capture, etc.
- Depends on: Services, Core
- Used by: Frontend API layer, MCP server, external OpenAI-compat clients

**Services:**
- Purpose: ML inference and media pipeline — the "heavy" business logic
- Location: `backend/services/`
- Contains: `model_manager.py` (TTS loading/idle), `tts_backend.py`, `asr_backend.py`, `dub_pipeline.py`, `speaker_clone.py`, `translation_engines.py`, `audio_dsp.py`, `ffmpeg_utils.py`, etc.
- Depends on: Core config, OmniVoice model package, external ML libs
- Used by: Routers

**Core:**
- Purpose: Shared infrastructure with no ML dependencies
- Location: `backend/core/`
- Contains: `db.py` (SQLite init + migrations), `config.py` (paths), `event_bus.py` (WebSocket pub/sub), `tasks.py` (async task manager + SSE), `job_store.py` (SQLite job metadata), `prefs.py` (user prefs JSON), `onboarding.py`, `personalities.py`
- Depends on: Nothing outside stdlib and `core.config`
- Used by: Services, Routers

**OmniVoice Model Package:**
- Purpose: TTS model definition and inference
- Location: `omnivoice/` (top-level package, separate from `backend/`)
- Contains: `models/omnivoice.py` — the `OmniVoice` class
- Depends on: PyTorch, torchaudio
- Used by: `backend/services/model_manager.py` (lazy-loaded)

## Data Flow

### TTS Generation Request

1. User submits form in `frontend/src/pages/CloneDesignTab.jsx`
2. `frontend/src/api/generate.ts` calls `apiPost('/generate', formData)`
3. `backend/api/routers/generation.py` → `POST /generate` handler validates form fields
4. Handler calls `await get_model()` from `backend/services/model_manager.py` — loads TTS if not in memory
5. `loop.run_in_executor(_gpu_pool, _run_inference, ...)` offloads PyTorch to the GPU thread pool
6. `_run_inference` calls `model.generate(...)` from `omnivoice/models/omnivoice.py`
7. Result passes through `services/audio_dsp.py` (`apply_mastering`, `normalize_audio`)
8. Audio written to `OUTPUTS_DIR`; metadata inserted into `generation_history` via `core/db.py`
9. `core/event_bus.emit("generation_history")` → broadcasts to all WebSocket listeners
10. HTTP response streams WAV bytes back to frontend (`StreamingResponse`)
11. `frontend/src/hooks/useRealtimeEvents.js` receives the `generation_history` event → TanStack Query cache invalidated → sidebar refreshes

### Dubbing Pipeline

1. User uploads video in `frontend/src/pages/DubTab.jsx`
2. `POST /dub/ingest` → `backend/api/routers/dub_core.py` streams SSE progress events
3. `services/dub_pipeline.py` manages job state + file paths under `DUB_DIR`
4. Pipeline stages: ffmpeg extract audio → ASR (`services/asr_backend.py`) → translate (`services/translation_engines.py`) → re-synthesize per segment (`services/tts_backend.py`) → ffmpeg re-compose
5. Each stage emits SSE events the frontend consumes via `EventSource`
6. Final export via `POST /dub/export` → `backend/api/routers/dub_export.py`

### Desktop Bootstrap Sequence

1. Tauri `run()` in `frontend/src-tauri/src/lib.rs` — app builds, window opens
2. `BootstrapSplash` React component renders, polling `bootstrap_status` Tauri IPC command
3. `backend.rs` calls `bootstrap::ensure_venv_ready()` — checks for `.venv`, runs `uv sync --frozen` if absent
4. On venv ready, `backend.rs` spawns `uvicorn backend.main:app --port 3900`
5. `backend.rs` probes `GET /system/info` until healthy (max 60 s)
6. Bootstrap stage transitions to `Ready` → splash removed → main App renders
7. `backend/main.py` lifespan: `init_db()` → sweep orphans → `preload_model()` task started

**State Management:**
- Frontend: Zustand (`frontend/src/store/`) — slices for prefs, UI, dub, generate, pill, glossary. Persisted subset to `localStorage` under key `omnivoice.app`
- Backend: SQLite for durable state; in-memory `dict` for active job runtime state; `prefs.json` for user preferences

## Key Abstractions

**TaskManager (`backend/core/tasks.py`):**
- Purpose: In-memory async task dispatcher with SQLite-backed metadata
- Pattern: Each long job (dub ingest, batch TTS) gets a UUID, stored in `jobs` table; SSE listeners fan out progress events; `?after_seq=N` allows reconnect and replay

**EventBus (`backend/core/event_bus.py`):**
- Purpose: Push-based sidebar reactivity — fire-and-forget pub/sub to all connected WebSocket clients
- Pattern: `emit(kind, payload)` is safe from both sync and async; frontend treats events as cache invalidation signals (not data payloads)

**TTSPlugin / PluginSDK (`backend/services/plugin_sdk.py`):**
- Purpose: Extension point for third-party TTS engines
- Pattern: Subclass `TTSPlugin`, decorate with `@register_plugin` or add to `PLUGINS` dict; engine appears in Settings engine picker

**AppStore (`frontend/src/store/index.ts`):**
- Purpose: Single Zustand root store composed from typed slices
- Pattern: `useAppStore(s => s.field)` at call sites; never create sibling stores; `partialize` controls which fields survive reload

## Entry Points

**Backend (HTTP server):**
- Location: `backend/main.py`
- Triggers: `uvicorn backend.main:app` (spawned by Tauri) or direct invocation
- Responsibilities: FastAPI app factory, lifespan startup (DB init, task workers, model preload), CORS, static file mounts, 22 router registrations

**Desktop app:**
- Location: `frontend/src-tauri/src/main.rs` → `lib.rs:run()`
- Triggers: User launches OmniVoice.app / .exe
- Responsibilities: Tauri window setup, single-instance enforcement, bootstrap state machine, backend subprocess lifecycle, system tray, global dictation shortcut

**Frontend SPA:**
- Location: `frontend/src/main.jsx` → `main-app.jsx:bootstrapApp()`
- Triggers: Tauri webview load or browser navigation
- Responsibilities: React root render, QueryClient setup, font + i18n init, widget vs. main app branching (`?window=widget`)

**MCP Server:**
- Location: `backend/mcp_server.py`
- Triggers: `python -m backend.mcp_server` (stdio for Claude Desktop) or `--sse` flag
- Responsibilities: Expose TTS generation + voice profile listing as AI-agent tools

## Architectural Constraints

- **Threading:** FastAPI runs on a single asyncio event loop. All PyTorch/ML work runs in `_gpu_pool` (single-worker `ThreadPoolExecutor` in `backend/services/model_manager.py`) to serialize GPU access. CPU-bound work uses `_cpu_pool` (up to 8 workers).
- **Global state:** `model_manager.py` holds `model` (TTS model singleton), `_gpu_pool`, `_cpu_pool`, `_loading_detail` as module-level singletons. `dub_pipeline.py` holds `_dub_jobs` and `_active_procs` module-level dicts. `event_bus.py` holds `_listeners` module-level list.
- **Circular imports:** `backend/main.py` imports from `core.*` and `services.*`; routers import from both layers. Avoid importing `api.*` from `services.*` or `core.*`.
- **Port:** Backend always binds to port 3900 (overridable via `OMNIVOICE_PORT`). Frontend hardcodes this default in `frontend/src/api/client.ts`.
- **Data dir:** All user data (DB, audio outputs, voice references) lives under a platform-specific directory resolved by `backend/core/config.py:get_app_data_dir()`. Never write to the project root at runtime.

## Anti-Patterns

### Importing API routers from services or core

**What happens:** A service or core module imports from `api/routers/`.
**Why it's wrong:** Creates a circular dependency chain; routers already import services/core.
**Do this instead:** Services emit to `core.event_bus` or return data to the router; the router shapes the HTTP response.

### Writing ML inference directly in router handlers

**What happens:** PyTorch calls or heavy I/O inside an `async def` route without `run_in_executor`.
**Why it's wrong:** Blocks the asyncio event loop; all other requests hang for the duration of inference.
**Do this instead:** Wrap the synchronous work in `await loop.run_in_executor(_gpu_pool, fn, *args)` as in `backend/api/routers/generation.py`.

### Creating sibling Zustand stores in the frontend

**What happens:** A new feature calls `create<SomeSlice>()` at module level instead of adding a slice to the root store.
**Why it's wrong:** Breaks the single-store contract; persisted state becomes fragmented across multiple `localStorage` keys.
**Do this instead:** Create a new slice file under `frontend/src/store/`, export `createXxxSlice`, import and spread it in `frontend/src/store/index.ts`.

## Error Handling

**Strategy:** FastAPI global exception handler in `backend/main.py` catches unhandled exceptions, writes to `CRASH_LOG_PATH`, attaches CORS headers, and returns `500` JSON. Client disconnects are caught separately and return `499`.

**Patterns:**
- Routers raise `HTTPException` for known bad inputs (400, 404)
- Services raise `RuntimeError` for ML failures (OOM, engine crash), which bubble to the global handler
- Frontend: `apiFetch` in `frontend/src/api/client.ts` throws `ApiError` on non-2xx responses; components use `react-hot-toast` for user-visible errors

## Cross-Cutting Concerns

**Logging:** Python `logging` with rotating file handler at `LOG_PATH` (2 MB, 3 backups). JSON format opt-in via `OMNIVOICE_JSON_LOGS=1`. Log level via `OMNIVOICE_LOG_LEVEL`. Logger namespace convention: `omnivoice.<module>` (e.g., `omnivoice.api`, `omnivoice.model`, `omnivoice.db`).

**Validation:** Pydantic handled by FastAPI on request bodies where schema files exist (`backend/schemas/`). File path inputs use `os.path.realpath` + prefix checks to prevent traversal.

**Authentication:** None — single-user local application. CORS restricted to `tauri://localhost` + `localhost:3901` by default (overridable via `OMNIVOICE_ALLOWED_ORIGINS`).

---

*Architecture analysis: 2026-05-16*
