# VoiceStudio — audio.cpp Engine (Breeze-TTS-2)

[audio.cpp](https://github.com/0xShug0/audio.cpp) is a pure-C++ ggml audio
inference framework (prebuilt binaries for Windows/macOS/Linux, CUDA / HIP /
Vulkan / Metal / CPU, no Python dependency). VoiceStudio drives its
`audiocpp_server` over loopback HTTP — v1 serves the **`breeze_tts`**
family: **Breeze-TTS-2** (BreezeBlue, 3B params, English + Chinese, voice
clone + voice design + voice direction, 24 kHz).

> **Opt-in, and never a default.** Select `audiocpp` explicitly in **Model
> Catalogue → Engines** (or `OMNIVOICE_TTS_BACKEND=audiocpp`).

## License — read before enabling

- **audio.cpp code:** Apache-2.0.
- **Breeze-TTS-2 weights** (upstream `BreezeBlue/Breeze-TTS-2` and the
  `audio-cpp/audio.cpp-gguf` GGUF repack): **research and non-commercial
  use only** under the [BreezeBlue Research and Non-Commercial License](
  https://huggingface.co/BreezeBlue/Breeze-TTS-2/blob/main/LICENSE).
  Self-hosted outputs inherit the restriction; a BreezeBlue paid
  subscription covers hosted-platform outputs only, not this engine.

## Platform support

| Host | Binary | Compute |
|---|---|---|
| Windows x64 | prebuilt (Vulkan default; CUDA 12.4/13.3 opt-in) | GPU · CPU |
| Linux x64 | prebuilt (Vulkan default) | GPU · CPU |
| macOS arm64 / x64 | prebuilt (Metal) | GPU · CPU |
| Linux aarch64 | none upstream | unavailable in v1 |

Notes:

- Upstream ships **no Linux-CUDA prebuilt**. The Vulkan prebuilt runs on
  NVIDIA/AMD/Intel GPUs; for maximum CUDA speed, self-build audio.cpp with
  `ENGINE_ENABLE_CUDA=ON` and point `OMNIVOICE_AUDIOCPP_BIN` at it.
- The Windows CUDA zips additionally need the matching `cudart` archive
  extracted next to the binaries (upstream packaging, not VoiceStudio).
- **VRAM:** Q8_0 GGUF ≈ 3.2 GB weights + session workspace; 6 GB+ GPU
  recommended, 4 GB minimum.

## Install

1. Download the v0.7.2 prebuilt for your platform from
   [audio.cpp releases](https://github.com/0xShug0/audio.cpp/releases/tag/v0.7.2)
   (CPU/Vulkan ≈ 20–70 MB; Windows CUDA ≈ 270 MB + cudart) and extract it.
2. Set `OMNIVOICE_AUDIOCPP_BIN` to the `audiocpp_server` binary
   (`audiocpp_server.exe` on Windows):

   ```bash
   # macOS / Linux
   echo 'export OMNIVOICE_AUDIOCPP_BIN=$HOME/apps/audio.cpp/audiocpp_server' >> ~/.zshrc
   source ~/.zshrc
   ```

   Alternatively set `OMNIVOICE_AUDIOCPP_DIR` to the directory containing it.
3. Restart VoiceStudio. The ~3 GB `breeze-tts-2-q8_0.gguf` downloads from
   `audio-cpp/audio.cpp-gguf` (not gated) into the shared HF cache on first
   generate — resumable, hash-verified.
4. Pick `audiocpp` in **Model Catalogue → Engines**. The server starts
   lazily on first generate (`server.json` + `server.log` live under the app
   data `audiocpp/` directory).

## Voice modes

All three go through the one speech endpoint — reference presence selects:

- **Clone:** `ref_audio` + `ref_text` (exact transcript, as upstream).
- **Direction:** `ref_audio` + `ref_text` + `instruct`
  (e.g. "Speak slowly with a restrained, serious tone").
- **Design:** `description` (or `instruct`) with no `ref_audio`
  (e.g. "A warm, thoughtful young woman…"). Upstream strengthens
  instruction-following with `guidance_scale` ≈ 4.

## Optional env knobs

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMNIVOICE_AUDIOCPP_BIN` | — | Absolute path to `audiocpp_server`. |
| `OMNIVOICE_AUDIOCPP_DIR` | — | Directory containing `audiocpp_server`. |
| `OMNIVOICE_AUDIOCPP_MODEL` | auto-download | GGUF file or directory override. |
| `OMNIVOICE_AUDIOCPP_PACKAGE` | `breeze-tts-2-q8_0.gguf` | Package filename (`…-bf16.gguf` for full precision). |
| `OMNIVOICE_AUDIOCPP_BACKEND` | `metal` (macOS), `vulkan` (Win/Linux), `cpu` | Server compute backend. |
| `OMNIVOICE_AUDIOCPP_PORT` | `17860` | Loopback port. |
| `OMNIVOICE_AUDIOCPP_ASSET` | — | Reserved: release-asset override (not yet wired to auto-install). |

## Common errors

### `audiocpp_server not found ...`

The binary isn't installed. Follow **Install** — the message carries the
exact release URL and SHA for your platform.

### `audiocpp_server exited during startup ...`

Usually a backend the binary wasn't built with, or a taken port. Check the
`server.log` next to `server.json` in the app data `audiocpp/` directory;
set `OMNIVOICE_AUDIOCPP_BACKEND=cpu` as a fallback.

### `Breeze-TTS-2 package ... missing after download`

The upstream `audio.cpp-gguf` layout changed. File an issue with the
package listing — the allow-list in `bootstrap.py` needs updating.

---

audio.cpp runs as a managed native server (no Python venv, no
`transformers` conflict). Only the downloaded GGUF counts toward
[sidecar disk usage](disk-usage.md).
