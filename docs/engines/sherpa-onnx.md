# VoiceStudio — Sherpa-ONNX Engine

Sherpa-ONNX (k2-fsa/sherpa-onnx) is a unified C++ ONNX runtime that wraps
20+ TTS model families (VITS, MeloTTS, Piper, Kokoro, Matcha, and more)
behind one API, with pre-built wheels for Linux, Windows, and macOS (x86 and
ARM). You bring the model: point VoiceStudio at any downloaded sherpa-onnx
TTS model directory.

## When to pick it

- You want a specific community model (e.g. a Piper or VITS voice for your
  language) that no other engine hosts.
- You need a dependable CPU engine with optional CUDA acceleration.

## Setup

1. Install the runtime:

   ```bash
   pip install sherpa-onnx
   ```

2. Download a TTS model from the
   [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases)
   and unpack it somewhere permanent.

3. Point VoiceStudio at the model directory and restart:

   ```bash
   export OMNIVOICE_SHERPA_MODEL=/path/to/model-dir
   ```

4. Select the engine via **Model Catalogue** (TTS tab → **Use**) or
   `OMNIVOICE_TTS_BACKEND=sherpa-onnx`.

<!-- CLEAN-ROOM (spec W5-sherpa §5): model-directory contents and availability-gate paragraph goes here. -->

## Configuration

<!-- CLEAN-ROOM (spec W5-sherpa §6, §7): configuration table and Piper-voice example go here. -->

<!-- CLEAN-ROOM (spec W5-sherpa §8): Licences section goes here. -->

## Behaviour notes

- Output defaults to 22.05 kHz (the VITS default); once a model is loaded,
  its own sample rate is used.
- CPU is the universal baseline; the CUDA onnxruntime provider is available
  on Linux/Windows installs.
- **No cloning**: voices come from the model itself. Multi-speaker VITS
  models select a voice by numeric speaker id; speed is supported.
- Languages depend entirely on the model you download.

## Known limits

- One model at a time — switching models means changing
  `OMNIVOICE_SHERPA_MODEL` and restarting.
- No voice design, no reference-audio cloning, no emotion controls
  (see [expressive-speech.md](../expressive-speech.md)).

## Troubleshooting

<!-- CLEAN-ROOM (spec W5-sherpa §9): setup-error and number-verbalization troubleshooting bullets go here. -->
- Other issues: [install/troubleshooting.md](../install/troubleshooting.md).

See also: [benchmarks.md](../benchmarks.md),
[languages.md](../languages.md),
[disk usage](disk-usage.md).
