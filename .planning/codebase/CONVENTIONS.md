# Coding Conventions

**Analysis Date:** 2026-05-16

## Naming Patterns

**Files (Python backend):**
- Modules use `snake_case`: `dub_pipeline.py`, `job_queue.py`, `tts_backend.py`
- Router files are prefixed by domain: `dub_core.py`, `dub_generate.py`, `dub_export.py`, `dub_translate.py`
- Private/internal module helpers are prefixed with `_`: `_get_semaphore`, `_spawn_with_retry`, `_clamp`

**Files (Frontend):**
- React components use `PascalCase`: `Button.jsx`, `Dialog.jsx`, `CastingView.jsx`
- Hooks use `camelCase` with `use` prefix: `useTTS.js`, `useDubWorkflow.js`, `useSegmentEditing.js`
- API modules use `camelCase` or `kebab-case` context nouns: `client.ts`, `dub.ts`, `profiles.ts`
- Utility modules use `camelCase`: `format.js`, `media.js`, `constants.js`

**Functions (Python):**
- Public functions: `snake_case` — `compute_file_hash`, `safe_job_dir`, `parse_srt`
- Private/internal helpers: leading underscore `_snake_case` — `_ts_to_seconds`, `_transcribe_chunk`, `_load`
- Async functions follow same convention; no `async_` prefix — `ingest_pipeline`, `run_proc`

**Functions (Frontend JS/TS):**
- Regular functions and hooks: `camelCase` — `apiUrl`, `apiFetch`, `apiJson`, `apiPost`
- React components: `PascalCase` — `Button`, `WaveformTimeline`, `BootstrapSplash`

**Variables (Python):**
- Module-level constants: `SCREAMING_SNAKE_CASE` — `DATA_DIR`, `DUB_DIR`, `TRANSCRIBE_CHUNK_S`, `CPU_POOL_WORKERS`
- Module-level private state: leading underscore `_snake_case` — `_dub_jobs`, `_active_procs`, `_listeners`, `_crash_log_lock`
- Local variables: `snake_case`

**Types/Classes (Python):**
- Classes: `PascalCase` — `JobQueue`, `JobState`, `DubSegment`, `ExportRequest`, `SrtParseResult`
- Enums: `PascalCase` with `SCREAMING_SNAKE_CASE` members — `class JobState(str, enum.Enum): QUEUED = "queued"`
- Pydantic models: `PascalCase` — `DubRequest`, `DubSegment`, `RevealRequest`
- Dataclasses: `PascalCase` — `Job`

**Types/Interfaces (TypeScript):**
- Interfaces: `PascalCase` — `EngineBackend`, `SystemInfo`, `EngineFamilyResponse`
- Type aliases: `PascalCase` — `EngineFamily`
- Error classes: `PascalCase` — `ApiError`

## Code Style

**Formatting (Python):**
- Ruff is configured (`.ruff_cache/` present, version 0.15.11)
- `from __future__ import annotations` used in 38 of 75 Python files in `backend/` — use it in all new files that use type hints
- No trailing commas rule enforced; inline comments used heavily for context
- Long docstrings at module top describe purpose and section breakdown

**Formatting (Frontend):**
- No Prettier config detected — formatting is not strictly enforced beyond ESLint
- Tailwind CSS 4.x via `@tailwindcss/vite` plugin; utility classes inline in JSX

**Linting:**
- Python: Ruff (`.ruff_cache/` confirms active use). Suppressions use `# noqa: <CODE>` inline
  - Common suppressions: `# noqa: F401` (side-effect imports), `# noqa: BLE001` (broad exception catch), `# noqa: E402` (module-level import order)
  - `# type: ignore[<category>]` used for optional third-party deps that may not be installed
- Frontend: ESLint 10.x configured in `frontend/eslint.config.js`
  - Applies `eslint/js.recommended`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`
  - Rule override: `'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }]` — uppercase constants are exempt
  - TypeScript: `tsc --noEmit --checkJs false` in CI (JS errors pre-existing; only `.ts` files block CI)

## Import Organization

**Python order (per `backend/services/dub_pipeline.py` pattern):**
1. `from __future__ import annotations`
2. Standard library imports (alphabetical within group): `asyncio`, `hashlib`, `json`, `logging`, `os`, …
3. `from typing import …`
4. Third-party packages: `import soundfile as sf`
5. Internal project imports: `from core.config import …`, `from fastapi import …`, `from services.… import …`

**Python internal import note:**
- Lazy imports inside functions are used for optional heavy dependencies to avoid import errors when the dep is not installed (e.g., `import whisperx`, `import mlx_audio`). Guarded with `# noqa: F401` + `try/except ImportError`.

**Frontend order (per `frontend/src/App.jsx` and hook files):**
1. React and framework imports: `import React, { useState, … } from 'react'`
2. CSS imports: `import './index.css'`
3. Internal store: `import { useAppStore } from './store'`
4. Internal components: `import Button from './components/Button'`
5. Internal hooks: `import useTTS from './hooks/useTTS'`
6. Internal API: `import { apiJson } from './api/client'`
7. Internal utils: `import { formatTime } from './utils/format'`
8. Third-party libs: `import { toast } from 'react-hot-toast'`

**Path Aliases:**
- No `@/` path alias configured in Vite. All imports use relative paths.

## Error Handling

**Python backend patterns:**
- Route handlers raise `fastapi.HTTPException` with explicit `status_code` and `detail` string: `raise HTTPException(status_code=404, detail="Job not found")`
- Service-layer functions raise Python exceptions (`ValueError`, `RuntimeError`, `OSError`) — routers catch and convert to `HTTPException`
- `from e` chaining used on re-raises: `raise HTTPException(status_code=400, ...) from e`
- Broad `except Exception as e:` used only in entry-point/recovery paths, suppressed with `# noqa: BLE001`
- `logger.error(...)` / `logger.warning(...)` called before or after raising in service code

**Frontend patterns:**
- `ApiError` class (`frontend/src/api/client.ts`) carries `.status` and `.detail`; thrown by `apiFetch` on non-2xx
- Error detail extracted from JSON `{ detail }` or `{ error }` field first, then raw text, then `statusText`
- `toast.error(...)` used in React components for user-visible errors (via `react-hot-toast`)

## Logging

**Framework:** Python `logging` module; logger names follow `"omnivoice.<module>"` pattern

**Logger declaration (always module-level):**
```python
logger = logging.getLogger("omnivoice.dub")   # in dub_generate.py
logger = logging.getLogger("omnivoice.jobs")  # in job_queue.py, job_store.py
logger = logging.getLogger("omnivoice.db")    # in core/db.py
```

**Patterns:**
- `logger.info(...)` for normal milestones (cache hit, job start/end)
- `logger.warning(...)` for recoverable failures (demucs fallback, subprocess kill error)
- `logger.error(...)` for data integrity failures (DB decode error, persist failure)
- Use `%s` lazy-format, not f-strings in logger calls: `logger.warning("msg %s: %s", job_id, e)`

## Comments

**When to Comment:**
- Module-level docstrings required for services and routers — describe responsibility, what's included, what stays elsewhere
- Section dividers used with em-dash box comments: `# ── Section Name ──────────────────────────────────────────────────────────`
- Inline comments explain non-obvious business logic, pinned dependency reasons, and platform constraints
- Pinned dependency rationale always documented inline in `pyproject.toml`

**Docstrings:**
- Module: multi-line triple-quote with description, sub-sections where applicable
- Classes: single-line triple-quote on the class body line: `"""Single-lane serial async worker with cancellation and introspection."""`
- Functions: single-line triple-quote when purpose is non-obvious: `"""SHA-256 digest of a file, streamed in 256 KB chunks."""`
- No NumPy/Google-style parameter docs observed — prose-style only

## Function Design

**Size:** No strict line limit; complex service functions (ingest pipeline, dub pipeline) are long but heavily sectioned with inline comments. Aim for single responsibility.

**Parameters:** Type-annotated in all new code. Optional parameters use `Optional[T] = None` or `T | None = None` (Python 3.11 style). Pydantic `BaseModel` used for HTTP request bodies.

**Return Values:** Type-annotated in all new code. Return `Optional[str]`/`Optional[dict]` for functions that can return `None` rather than raising.

## Module Design

**Exports:**
- Python: no explicit `__all__` observed; consumers import by name. Private helpers use `_` prefix.
- Frontend: named exports preferred for utilities and API functions. Default export used for React components and hooks.

**Barrel Files:**
- Python: `backend/api/routers/setup/__init__.py` re-exports from submodules with `# noqa: F401`
- Frontend: `frontend/src/store/index.js` (implied by `import { useAppStore } from '../store'`)

---

*Convention analysis: 2026-05-16*
