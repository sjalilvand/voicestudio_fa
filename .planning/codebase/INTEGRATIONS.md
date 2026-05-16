# External Integrations

**Analysis Date:** 2026-05-16

## APIs & External Services

**LLM / AI Inference (Translation & Glossary):**
- OpenAI-compatible endpoints — cinematic translation, glossary auto-extraction, TTS translation
  - SDK/Client: `openai` Python package (lazy import in `backend/services/llm_backend.py`)
  - Auth: `TRANSLATE_API_KEY` env var (falls back to `OPENAI_API_KEY`)
  - Base URL: `TRANSLATE_BASE_URL` env var (defaults to OpenAI; override for Ollama `http://localhost:11434/v1`, LM Studio, Together, Anyscale, DeepSeek, Qwen, OpenRouter)
  - Model: `TRANSLATE_MODEL` env var (default `gpt-4o-mini`)
  - Timeout: `OMNIVOICE_LLM_TIMEOUT` env var (default 45 seconds)
  - Backend selection: `OMNIVOICE_LLM_BACKEND` env var or user preference in `core/prefs`
  - Implementation: `backend/services/llm_backend.py`, `backend/services/translator.py`

**HuggingFace Hub:**
- Purpose: model weight downloads (OmniVoice, WhisperX, NLLB-200, pyannote, mlx-community models)
  - Auth: `HF_TOKEN` env var (required for gated models like pyannote speaker diarization)
  - Cache: `HF_HOME` / `HF_HUB_CACHE` env vars (or `OMNIVOICE_CACHE_DIR`)
  - Windows cache path override: `%LOCALAPPDATA%\OmniVoice\hf_cache` (auto-set in `backend/core/config.py`)
  - Xet disabled by default (`HF_HUB_DISABLE_XET=1`) to keep tqdm progress hooks working
  - HTTP client: `httpx` (shared pool in `backend/api/http_client.py`); HuggingFace Hub SDK uses its own session

**YouTube / URL Video Download:**
- `yt-dlp ≥2024.12.13` — downloads video from YouTube URLs for dubbing workflow
  - No API key required for public videos
  - Used in: `backend/api/routers/dub_core.py`, `backend/services/dub_pipeline.py`

## Translation Providers

The translation engine registry (`backend/services/translation_engines.py`) is the single source of truth. Engines are installed/uninstalled at runtime via `uv pip` or `python -m pip`.

**Offline (no API key):**
- `argos` — Argos Translate (`argostranslate` package); pure-CPU, ~50 MB language packs downloaded per language pair
- `nllb` — Meta NLLB-200 (`transformers` package, already a core dep); ~2.4 GB HF model download

**Online (no API key):**
- `google` — Google Translate via `deep_translator` package; free web endpoint, rate-limited
- `mymemory` — MyMemory via `deep_translator`; crowdsourced, 5K chars/day anonymous free tier

**Online (API key required):**
- `deepl` — DeepL via `deep_translator`; 500K chars/month free tier
  - Auth: `DEEPL_API_KEY` env var
- `microsoft` — Azure Cognitive Services Translator via `deep_translator`; 2M chars/month free tier
  - Auth: `MICROSOFT_API_KEY` env var
- `openai` — Any OpenAI-compatible endpoint via `openai` package (GPT-4/5, Claude via OpenRouter, Gemini, DeepSeek, Qwen, Ollama, LM Studio)
  - Auth: `TRANSLATE_API_KEY` + `TRANSLATE_BASE_URL` + `TRANSLATE_MODEL`

## Data Storage

**Databases:**
- SQLite — sole persistent data store
  - DB file: `{DATA_DIR}/omnivoice.db` (path resolved in `backend/core/config.py`)
  - Client: Python stdlib `sqlite3` — WAL mode + foreign keys enforced on every connection
  - Connection factory: `backend/core/db.py` (`get_db()`, `db_conn()` context manager)
  - Schema: `backend/core/db.py` (`_BASE_SCHEMA`)
  - Migrations: in-band in `init_db()` via `PRAGMA user_version` (4 versions as of analysis date)
  - Tables: `voice_profiles`, `generation_history`, `dub_history`, `studio_projects`, `export_history`, `glossary_terms`, `jobs`, `job_events`
  - Alembic: configured in `alembic.ini` / `backend/migrations/` — used for formal migration authoring; URL set programmatically from `core.config.DB_PATH`

**File Storage:**
- Local filesystem only — all user data stored under `DATA_DIR`
  - `{DATA_DIR}/voices/` — reference audio for voice profiles
  - `{DATA_DIR}/outputs/` — generated audio files (served as `/audio` static mount)
  - `{DATA_DIR}/dub_jobs/` — dubbing job artifacts
  - `{DATA_DIR}/preview/` — preview audio clips
  - `{DATA_DIR}/outputs/marketplace/` — locally published `.omnivoice` voice bundles
  - Voice profiles exported as `.omnivoice` ZIP bundles (metadata.json + audio, `backend/api/routers/marketplace.py`)
- Docker: `/app/omnivoice_data` volume (`deploy/docker-compose.yml`)

**Caching:**
- HuggingFace Hub cache: `{HF_HOME}` / `{HF_HUB_CACHE}` (models, tokenizers)
- PyTorch hub cache: `{TORCH_HOME}`
- No Redis or in-memory external cache — job event replay uses `job_events` SQLite table

## Authentication & Identity

**Auth Provider:** None — OmniVoice ships with no built-in authentication layer.
- The Docker Compose config explicitly warns to put OmniVoice behind a reverse proxy with auth if exposed externally (`deploy/docker-compose.yml`, comments)
- Default port binding: `127.0.0.1:3900` (localhost only)
- CORS: restricted to `localhost:3901`, `127.0.0.1:3901`, `tauri://localhost`, `http://tauri.localhost` by default; override with `OMNIVOICE_ALLOWED_ORIGINS`

## AI Model Integrations

**TTS Backends** (registry in `backend/services/tts_backend.py`):
- `omnivoice` (default) — OmniVoice zero-shot diffusion model, 600+ languages, 24 kHz
- `kittentts` — KittenML KittenTTS, English-only, ONNX, 8 preset voices, CPU realtime
- `mlx-audio` — Blaizzy/mlx-audio, mac-ARM only; wraps Kokoro, CSM, Dia, Qwen3-TTS, Chatterbox, MeloTTS, OuteTTS, Spark, Higgs-Audio; model via `OMNIVOICE_MLX_AUDIO_MODEL`
- `cosyvoice` — CosyVoice 2 (optional install)
- `indextts2` — IndexTTS 2 (optional install)
- `gpt-sovits` — GPT-SoVITS (optional install)
- `sherpa-onnx` — Sherpa-ONNX (optional install)
- `voxcpm2` — VoxCPM2 (stub, install hint on call)
- `moss-tts-nano` — Moss TTS Nano (optional install)
- Backend selection: `OMNIVOICE_TTS_BACKEND` env var or `OMNIVOICE_MLX_AUDIO_MODEL`

**ASR Backends** (registry in `backend/services/asr_backend.py`):
- `whisperx` (default cross-platform) — WhisperX + faster-whisper + wav2vec2 forced alignment; model via `ASR_MODEL_WHISPERX` env var (default `large-v3`); CUDA float16 or CPU int8
- `faster-whisper` — CTranslate2 standalone fallback
- `mlx-whisper` — Apple Silicon only; preloaded at startup for low-latency dictation
- `pytorch-whisper` — last-resort fallback using `_asr_pipe`
- Backend selection: `OMNIVOICE_ASR_BACKEND` env var (default: auto-detect)
- Capture ASR: separate backend for real-time dictation, preloaded at app startup in `backend/main.py`

**Speaker Diarization:**
- `pyannote.audio` Pipeline — gated HuggingFace model; requires `HF_TOKEN`
  - Implementation: `backend/services/model_manager.py` (~line 391)

**Audio Watermarking:**
- AudioSeal (Meta) — invisible neural watermarks in generated speech; 16-bit message payload ("OM" ASCII marker)
  - Implementation: `backend/services/watermark.py`

**Voice Conversion:**
- RVC (Retrieval-based Voice Conversion) — optional; `rvc_python` package; no-ops unless enabled
  - Implementation: `backend/services/rvc.py`

**Audio Source Separation:**
- Demucs ≥4.0.1 — vocal/music separation for dubbing ingestion

**Audio DSP:**
- Pedalboard ≥0.9.14 — compressor, reverb, highpass filter, EQ; used in `backend/services/audio_dsp.py`

## Real-Time Communication

**WebSocket:**
- Streaming ASR endpoint — `/capture_ws` — streams PCM/WebM audio from browser, returns partial + final transcription JSON
  - Router: `backend/api/routers/capture_ws.py`
  - Protocol: binary audio frames in, JSON messages out (`{"type": "partial"|"final"|"error", ...}`)

**Server-Sent Events (SSE):**
- Task/job progress streaming — clients connect with `EventSource` and receive durable SSE events
  - Router: `backend/api/routers/events.py`
  - Durable replay: events persisted to `job_events` SQLite table; reconnect with `?after_seq=N`
  - Event bus: `backend/core/event_bus.py` fans events to all connected WebSocket listener queues
  - HF Hub download progress also forwarded to SSE via `backend/utils/hf_progress.py` tqdm patch

## OpenAI-Compatible API

OmniVoice exposes an OpenAI drop-in TTS/STT API so any tool speaking the OpenAI protocol can use OmniVoice as a local backend:
- `POST /v1/audio/speech` — TTS (text → wav/mp3/opus/flac)
- `POST /v1/audio/transcriptions` — STT (audio file → text/json)
- `GET  /v1/audio/voices` — list voice profiles (OmniVoice extension)
- Router: `backend/api/routers/openai_compat.py`

## MCP (Model Context Protocol)

OmniVoice exposes voice synthesis as AI-agent tools via an MCP server:
- Standalone: `python -m backend.mcp_server`
- Transport: stdio (Claude Desktop) or SSE (`--sse` flag, remote agents)
- SDK: `mcp[cli]` package (lazy import, not a core dependency)
- Tools: `generate_speech`, `list_voices`, `list_languages`, `list_personalities`
- Resources: `voice://{profile_id}`, `history://recent`
- Implementation: `backend/mcp_server.py`

## FFmpeg

- Used extensively for audio/video processing, format conversion, muxing, and export
- Resolution order in `backend/services/ffmpeg_utils.py`: bundled Tauri binary → `imageio_ffmpeg` → system PATH
- Bundled in Tauri desktop packages as external binary (`frontend/src-tauri/tauri.conf.json` `externalBin`)
- System install on Docker (`apt-get install ffmpeg` in `deploy/Dockerfile`)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, or similar)

**Crash Logging:**
- Local crash log at `{DATA_DIR}/crash_log.txt` — written on unhandled FastAPI exceptions (`backend/main.py`)

**Runtime Logs:**
- Rolling file log at `{DATA_DIR}/omnivoice.log` — `RotatingFileHandler`, 2 MB max, 3 backups; readable from Settings UI
- JSON log format optional via `OMNIVOICE_JSON_LOGS=1`
- Log level: `OMNIVOICE_LOG_LEVEL` env var (default `INFO`)

## CI/CD & Deployment

**CI Pipeline:**
- GitHub Actions — `.github/workflows/ci.yml`
  - Triggers: PR to main, push to main
  - Jobs: pytest (backend), pytest (backend/tests isolated), Vitest (frontend), TypeScript typecheck, Tauri `cargo check` (macOS/Windows/Linux matrix)
  - Runner: ubuntu-22.04 (tests), macOS-14/Windows-2022/ubuntu-22.04 (Tauri check)

**Docker CI/CD:**
- GitHub Actions — `.github/workflows/docker.yml`
  - Triggers: semver tag push (`v*`), `workflow_dispatch`
  - Registry: `ghcr.io` (GitHub Container Registry)
  - Image: `ghcr.io/debpalash/omnivoice-studio:latest` + semver tags
  - Cache: GitHub Actions cache (`type=gha`)

**Desktop Release:**
- GitHub Actions — `.github/workflows/release.yml`
  - Triggers: semver tag push (`v*`), `workflow_dispatch`
  - Produces: platform-signed Tauri bundles (`.dmg`/`.app`, `.msi`, `.deb`/`.AppImage`)
  - Signing: `TAURI_SIGNING_PRIVATE_KEY` GitHub secret
  - Updater: publishes `latest.json` to GitHub Releases; Tauri updater plugin polls on client boot

**Hosting:**
- Docker: self-hosted (pull from GHCR or build from source)
- Desktop: self-updating binaries distributed via GitHub Releases

## Webhooks & Callbacks

**Incoming:** None

**Outgoing:**
- HuggingFace Hub API — model weight downloads (via HF Hub SDK + httpx)
- OpenAI-compatible endpoints — LLM translation and glossary calls (user-configured, opt-in)
- GitHub Releases — Tauri auto-updater polls `latest.json` for desktop update checks
- yt-dlp — HTTP requests to YouTube/URLs for video download

## Environment Configuration

**Required env vars (for gated features):**
- `HF_TOKEN` — HuggingFace access token; required for pyannote speaker diarization and other gated models
- `TRANSLATE_API_KEY` / `OPENAI_API_KEY` — LLM API key; required for AI translation and glossary features
- `TRANSLATE_BASE_URL` — LLM base URL; required when using non-OpenAI endpoints (Ollama, LM Studio, etc.)
- `DEEPL_API_KEY` — required for DeepL translation engine
- `MICROSOFT_API_KEY` — required for Microsoft Azure Translator engine

**Optional env vars:**
- `OMNIVOICE_DATA_DIR` — override platform data directory
- `OMNIVOICE_CACHE_DIR` — override HF/Torch cache directory
- `OMNIVOICE_TTS_BACKEND` — select TTS engine (default: `omnivoice`)
- `OMNIVOICE_ASR_BACKEND` — select ASR engine (default: auto-detect)
- `OMNIVOICE_LLM_BACKEND` — select LLM backend (default: auto-detect)
- `OMNIVOICE_MLX_AUDIO_MODEL` — mlx-audio model key or HF repo ID
- `ASR_MODEL_WHISPERX` — WhisperX model size (default: `large-v3`)
- `TRANSLATE_MODEL` — LLM model name (default: `gpt-4o-mini`)
- `OMNIVOICE_IDLE_TIMEOUT` — VRAM idle timeout in seconds (default: `900`)
- `OMNIVOICE_CPU_POOL` — CPU thread pool size (default: `min(8, cpu_count)`)
- `OMNIVOICE_LLM_TIMEOUT` — LLM call timeout in seconds (default: `45`)
- `OMNIVOICE_ALLOWED_ORIGINS` — comma-separated CORS origins
- `OMNIVOICE_LOG_LEVEL` — log level (default: `INFO`)
- `OMNIVOICE_JSON_LOGS` — set to `1` for JSON log format
- `OMNIVOICE_DISABLE_FILE_LOG` — suppress rolling file log
- `OMNIVOICE_FROZEN` — mark process as frozen (Tauri/PyInstaller bundle)
- `HSA_OVERRIDE_GFX_VERSION` — AMD ROCm GFX version override (auto-set for known consumer GPUs)

**Secrets location:**
- `.env` file at repo root (loaded by `python-dotenv` in `backend/main.py`)
- Persistent user config: `~/.config/omnivoice/env` (survives desktop launcher restarts)
- Docker: environment section in `deploy/docker-compose.yml` referencing host env vars
- CI: GitHub Actions secrets (`TAURI_SIGNING_PRIVATE_KEY`, `GITHUB_TOKEN` for GHCR)

---

*Integration audit: 2026-05-16*
