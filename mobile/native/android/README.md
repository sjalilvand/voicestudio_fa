# Android native runtimes

`build.sh` fetches sherpa-onnx's AAR and builds OmniVoice and llama.cpp for
`arm64-v8a` and `x86_64`, using the identities in `../pins.json` exclusively.
Gradle's app `preBuild` invokes it and packages both JNI libraries, their C++
runtime and the pinned sherpa AAR. No model is fetched by a build.

Requirements: Python 3, JDK 21, Android SDK 36, CMake 3.22.1 and NDK
**27.1.12297006** (also pinned in Gradle). Set `ANDROID_HOME` to the SDK root.
Run from any directory:

```sh
bash mobile/native/android/build.sh
# Fetch and verify only:
bash mobile/native/android/build.sh --fetch-only
```

Everything fetched or generated lives in the repository-ignored `build/`.
The AAR's SHA-256 comes from `pins.json`. Source archives use the pinned commit
in that file and a reviewed SHA-256 in `source-checksums.json`; a changed pin
without a matching checksum fails closed. The additional GGML pin is the
OmniVoice commit's `ggml` gitlink, `f3bc6505c4e2ede83a193e0fb4695938ff3804fd`.
No git command changes the app checkout or populates a nested git repository.
Every invocation rechecks archive hashes. Extracted sources and per-ABI CMake
outputs are reused; deleting `build/` produces a complete source rebuild.
The archive-only OmniVoice version generator embeds its pinned commit instead
of accidentally discovering the parent app repository. llama receives its
explicit build identity via CMake.

The two runtimes each statically link their own GGML into a separate JNI shared
library. Hidden archive symbols and internal symbol binding prevent their
incompatible GGML ABIs from interposing. Libraries use 16 KB ELF alignment and
CPU execution on both ABIs; no acceleration or network service is required.
Runtime MIT notices are copied into generated app assets; the app also includes
Apache-2.0 and dependency notices. Model terms travel in the shared catalogue
and require a separate local acceptance where applicable.

JNI implements reference-audio cloning using `ov_init`/`ov_synthesize` and
translation using llama's model/context, tokenization, prompt decode and greedy
autoregressive sampling. JNI receives UTF-16 strings as standard UTF-8 and
returns translation bytes without truncating multibyte characters. Logs from
these two engines are suppressed. Cooperative cancellation callbacks reach
native inference, and native allocations are released before calls return.
OmniVoice model initialization has no abort hook; cancellation during its load
is observed as soon as initialization returns. sherpa Whisper similarly has no
abort hook in this AAR: offline ASR decodes at most 20 seconds of audio between
cancellation checks. Online ASR checks between each decoder step. Model hashing
and streaming downloads check cancellation as they read.

Both ABIs compile on this host. Actual Android library loading, audio quality,
microphone behavior and OmniVoice/llama model compatibility require maintainer
instrumentation/device runs. `LocalInferenceTest` includes an unconditional
model-free library-loading test and an explicitly enabled TTS/Whisper/streaming
ASR smoke test, plus opt-in real voice-clone and dub pipeline tests.
`PhoneDubInferenceTest` also exercises platform AAC/AVC muxing without model
downloads; see `mobile/android/README.md`. No device commands are run by
this build script.
