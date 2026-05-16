# Technology Stack

**Analysis Date:** 2026-05-16

## Languages

**Primary:**
- Python 3.11 — entire backend, ML models, API server, CLI tools
- TypeScript/JavaScript (JSX) — React frontend (`frontend/src/`)
- Rust — Tauri desktop shell (`frontend/src-tauri/`)

**Secondary:**
- Shell (Bash/Zsh) — build scripts (`scripts/`)

## Runtime

**Environment:**
- Python 3.11 (pinned via `.python-version`)
- Node.js 22 (required for `--experimental-strip-types` in tests)
- Rust stable (minimum 1.77.2 per `frontend/src-tauri/Cargo.toml`)

**Package Manager:**
- Python: `uv` (Astral) — lockfile at `uv.lock` (present)
- JavaScript: `bun` 1.3.11 — lockfile at `bun.lock` (present)
- Rust: `cargo` — lockfile at `frontend/src-tauri/Cargo.lock` (present)

## Frameworks

**Core:**
- FastAPI — REST API server (`backend/main.py`), port 3900
- Uvicorn — ASGI server for FastAPI
- React 19 — frontend UI (`frontend/src/`)
- Tauri 2.11.0 — cross-platform desktop shell wrapping React + Python backend (`frontend/src-tauri/`)

**ML / AI:**
- PyTorch 2.8.0 (CUDA 12.8 on Linux/Windows, CPU/MPS on macOS) — deep learning runtime
- Torchaudio 2.8.0 — audio I/O and transforms
- HuggingFace Transformers ≥5.3.0 — model hub integration and NLLB-200 translation
- WhisperX ≥3.1.0 — cross-platform ASR with wav2vec2 forced alignment
- Faster-Whisper ≥1.0.0 — CTranslate2-based Whisper fallback
- mlx-whisper ≥0.2.1 — Apple Silicon ASR (mac-ARM only)
- mlx-audio ≥0.3.0 — Apple Silicon multi-engine TTS (mac-ARM only; Kokoro, CSM, Dia, Qwen3-TTS, Chatterbox, MeloTTS, OuteTTS, Spark, Higgs-Audio)
- pyannote-audio ≥3.3.2,<4.0 — speaker diarization for dubbing
- Demucs ≥4.0.1 — audio source separation (vocals/music split)
- Pedalboard ≥0.9.14 — audio effects (DSP post-processing)
- AudioSeal ≥0.1.3 — invisible neural watermarking (Meta)
- KittenTTS 0.8.1 — lightweight English ONNX TTS (25-80 MB, 8 preset voices)
- Accelerate — HuggingFace distributed training/inference accelerator
- Pydub — audio format conversion
- Soundfile — audio file I/O (libsndfile)

**Frontend UI:**
- Tailwind CSS 4 — utility-first styling (Vite plugin)
- Radix UI — accessible headless component primitives (Dialog, Dropdown, Tabs, Slider, Select, Popover, etc.)
- Zustand 5 — frontend state management (`frontend/src/store/`)
- TanStack Query 5 — server state, caching, data fetching
- TanStack Table 8 — headless table primitives
- TanStack Virtual 3 — list virtualisation
- wavesurfer.js 7 — waveform visualisation in audio editor
- i18next 26 + react-i18next — internationalisation
- Lucide React — icon set
- react-hot-toast — toast notifications
- react-window 2 — virtualised list rendering

**Build / Dev:**
- Vite 8 — frontend bundler (port 3901 in dev)
- Vitest 4 — frontend unit test runner
- Turbo 2 — monorepo task orchestration (`turbo.json`)
- Tauri CLI 2.11.0 — desktop build toolchain
- PyInstaller ≥6.19.0 — Python backend freezing for desktop distribution (`backend.spec`)
- hatchling — Python package build backend (`pyproject.toml`)
- Alembic 1.13 — DB schema migrations (`alembic.ini`, `backend/migrations/`)
- Ruff — Python linting (`.ruff_cache/` present)
- ESLint 10 — JavaScript/JSX linting (`frontend/eslint.config.js`)
- Playwright 1.59 — end-to-end browser tests

**Testing:**
- pytest ≥9.0.3 — Python unit/integration tests (`tests/`, `backend/tests/`)
- pytest-asyncio ≥1.3.0 — async test support
- pytest-cov ≥6.0 — coverage reporting
- Vitest — React component/unit tests (`frontend/src/**/*.test.*`)
- Node test runner — legacy frontend API tests (`tests/frontend/*.test.mjs`)

## Key Dependencies

**Critical:**
- `torch==2.8.0` / `torchaudio==2.8.0` — constrained version; Linux/Windows pull from PyTorch CUDA 12.8 index (`https://download.pytorch.org/whl/cu128`)
- `whisperx>=3.1.0` — ASR default; pins `pyannote-audio<4.0` for compatibility
- `pyannote-audio>=3.3.2,<4.0` — speaker diarization; must stay <4.0 until whisperx releases a compatible build
- `kittentts @ https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl` — not on PyPI, installed via GitHub Releases URL
- `scalar-fastapi` — replaces default FastAPI `/docs` with Scalar interactive docs

**Infrastructure:**
- `fastapi` + `uvicorn` + `python-multipart` + `websockets` — API server stack
- `alembic` — schema migration management (SQLite via `sqlite3` stdlib)
- `imageio-ffmpeg ≥0.6.0` — bundled FFmpeg binary fallback
- `yt-dlp ≥2024.12.13` — YouTube/URL video download for dubbing
- `psutil ≥7.2.2` — system metrics
- `gradio` + `gradio_client` — optional legacy demo UI

## Configuration

**Environment:**
- `.env` file at repo root (loaded by `python-dotenv` in `backend/main.py`)
- Per-user persistent config: `~/.config/omnivoice/env` (survives Tauri/Finder launches)
- `OMNIVOICE_DATA_DIR` — overrides default platform data directory
- `OMNIVOICE_CACHE_DIR` — redirect HF/Torch cache (sets `HF_HOME`, `HF_HUB_CACHE`, `TORCH_HOME`)
- `OMNIVOICE_IDLE_TIMEOUT` — seconds before model unloads from VRAM (default 900)
- `OMNIVOICE_CPU_POOL` — thread pool workers (default: min(8, cpu_count))
- `OMNIVOICE_LOG_LEVEL` — logging level (default `INFO`)
- `OMNIVOICE_JSON_LOGS=1` — switch to JSON-per-line log format
- `OMNIVOICE_DISABLE_FILE_LOG` — suppress rolling file log (useful in CI)
- `OMNIVOICE_ALLOWED_ORIGINS` — comma-separated CORS origins (default: localhost:3901, tauri://localhost)
- `HF_HUB_DISABLE_XET=1` — force LFS over Xet (set by default in `backend/main.py`)
- `HF_HUB_DISABLE_SYMLINKS` / `HF_HUB_DISABLE_SYMLINKS_WARNING` — Windows symlink workaround

**Platform Data Directories (auto-resolved in `backend/core/config.py`):**
- macOS: `~/Library/Application Support/OmniVoice/`
- Windows: `%APPDATA%\OmniVoice\`
- Linux: `~/.omnivoice/`

**Build:**
- `pyproject.toml` — Python packaging, dependency declarations, pytest config
- `uv.lock` — pinned Python dependency tree
- `package.json` — root monorepo scripts and dev tooling
- `frontend/package.json` — React/Tauri frontend
- `turbo.json` — task graph for build/dev/desktop targets
- `backend.spec` — PyInstaller spec for frozen backend binary
- `frontend/src-tauri/tauri.conf.json` + `tauri.macos.conf.json` / `tauri.linux.conf.json` / `tauri.windows.conf.json` — platform-specific Tauri config
- `alembic.ini` — Alembic migration config (DB URL set programmatically in `backend/migrations/env.py`)

## Platform Requirements

**Development:**
- Python 3.11
- `uv` (Python dependency management)
- Bun 1.3.11 (JavaScript package management)
- Rust stable ≥1.77.2 (for `tauri dev` / `cargo check`)
- FFmpeg (system install or bundled via `imageio-ffmpeg`)
- CUDA 12.8 toolkit (optional, Linux/Windows GPU acceleration)

**Production:**
- Docker: `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base image (`deploy/Dockerfile`)
- Docker Compose CPU and GPU profiles (`deploy/docker-compose.yml`)
- Container registry: `ghcr.io/debpalash/omnivoice-studio` (GitHub Container Registry)
- Desktop: self-updating Tauri bundles — `.dmg`/`.app` (macOS), `.msi` (Windows), `.deb`/`.AppImage` (Linux)
- Updater endpoint: `https://github.com/debpalash/OmniVoice-Studio/releases/latest/download/latest.json`
- macOS minimum version: 12.0

---

*Stack analysis: 2026-05-16*
