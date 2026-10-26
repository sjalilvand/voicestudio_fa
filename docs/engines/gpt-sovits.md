# VoiceStudio — GPT-SoVITS Engine

GPT-SoVITS (RVC-Boss) is one of the most popular open-source voice-cloning
systems (57k+ GitHub stars, MIT-licensed). It does zero-shot and few-shot
cloning with excellent naturalness in Chinese, English, Japanese, Cantonese,
and Korean, and it is very fast (RTF ~0.014 on suitable hardware).

Unlike VoiceStudio's other engines, GPT-SoVITS does not run inside the app.
It ships as a standalone API server, and VoiceStudio connects to it over
HTTP.

## When to pick it

- You already run (or want to run) a GPT-SoVITS server, e.g. with few-shot
  fine-tuned voices.
- You need fast, natural cloning in zh/en/ja/yue/ko.

## Setup

1. Install and start the GPT-SoVITS API server (upstream project):

   ```bash
   cd GPT-SoVITS
   python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
   ```

   <!-- CLEAN-ROOM (spec N-jaketame-2 §24): protocol compatibility note (api_v2 only) and how to use fine-tuned weights. -->

2. Select the engine via **Model Catalogue** (TTS tab → **Use**) or
   `OMNIVOICE_TTS_BACKEND=gpt-sovits`.

VoiceStudio marks the engine available only when the server responds
(2-second reachability probe).

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `OMNIVOICE_GPTSOVITS_URL` | `http://127.0.0.1:9880` | API server URL |
| `OMNIVOICE_GPTSOVITS_REF_LANG` | `auto` | Language of the clip (`zh`/`en`/`ja`/`yue`/`ko`) |
| `OMNIVOICE_TRUSTED_NETWORKS` | (unset) | Required to allow a non-loopback server |

<!-- CLEAN-ROOM (spec N-jaketame-2 §24): configuration rows for the default reference audio and transcript variables. -->

**Remote servers:** by default VoiceStudio only talks to loopback addresses
— part of the local-first guarantee. To point at a server on another
machine (e.g. a GPU box on your LAN), add its network to
`OMNIVOICE_TRUSTED_NETWORKS`; otherwise the connection is refused as an
untrusted endpoint.

Prefer `https://` (or a private tunnel such as Tailscale/WireGuard) for any
non-loopback server: with plain `http://` the text you synthesize and the
audio that comes back cross the network unencrypted. VoiceStudio does not
disable certificate verification, so a TLS endpoint needs a certificate the
system trusts.

## Behaviour notes

- Output is 32 kHz mono (server output is resampled if needed).
<!-- CLEAN-ROOM (spec N-jaketame-2 §24): behaviour notes on unsplit requests and the required reference clip. -->
<!-- CLEAN-ROOM (spec N-jaketame-2 §24): behaviour note on cloning reference clips and server-side paths. -->
- Speed control is forwarded as the server's `speed_factor`.
- The GPU is whatever the GPT-SoVITS server itself uses (CUDA preferred);
  VoiceStudio's side is just an HTTP client.

## Known limits

- Five languages only; for broader coverage use
  [OmniVoice](omnivoice.md) ([languages.md](../languages.md)).
- No voice design; server availability is your responsibility — if the
  server stops, generations fail with a "server not reachable" error.

## Troubleshooting

<!-- CLEAN-ROOM (spec N-jaketame-2 §24): troubleshooting bullet for the "server not reachable" error and probe semantics. -->
- "endpoint is outside loopback or OMNIVOICE_TRUSTED_NETWORKS": see
  Configuration above.
- Other issues: [install/troubleshooting.md](../install/troubleshooting.md).

See also: [benchmarks.md](../benchmarks.md),
[expressive-speech.md](../expressive-speech.md).

Reference transcripts from saved profiles and uploaded clips use api_v2's
`auto` language detection, independently of the output language. An English
reference can therefore produce Japanese speech without being interpreted as
Japanese. The configured default clip also uses `auto` unless
`OMNIVOICE_GPTSOVITS_REF_LANG` specifies its language; that setting never
applies to a different, explicitly supplied clip.
