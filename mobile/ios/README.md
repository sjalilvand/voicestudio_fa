# VoiceStudio for iOS

Native SwiftUI app for iOS 17+, iPhone and iPad. Speak and Dictate run downloaded models on the phone, offline. Pairing a VoiceStudio computer adds its engines and the existing Voices and Dub workflows. All five tabs are available without pairing; Settings contains Connect and Models. Phone cloning and dubbing screens are outside this phase; the `LocalEngine` boundary already implements clone and translation for native integration tests.

## Build and checks

Swift 6 Command Line Tools, Python 3.9+ and CMake run the macOS package checks. XcodeGen 2.46 generates the app project. Full Xcode with the iOS SDK is required for the app, native xcframeworks and UI tests. Device signing uses your own development team. The root `package.json` supplies the app version; there is no mobile version mirror.

Run from the repository root:

```sh
mobile/ios/scripts/check-swift.sh build
mobile/ios/scripts/check-swift.sh test
mobile/ios/scripts/check-platform.sh
python3 mobile/ios/scripts/prepare_resources.py \
  --output mobile/ios/.generated/bundle \
  --info-output mobile/ios/.generated/Info.plist
swiftc -frontend -parse mobile/ios/VoiceStudio/App/*.swift \
  mobile/ios/VoiceStudio/Features/*.swift mobile/ios/VoiceStudio/Platform/*.swift \
  mobile/ios/VoiceStudioUITests/*.swift
```

`check-swift.sh` keeps build/module caches inside `mobile/ios/` and supplies the installed Testing.framework on CLT-only installations. Package tests do not download models. The optional `VOICESTUDIO_SWIFT_SCRATCH` selects a separate scratch directory. `check-platform.sh` type-checks the production host media loader, smoke transport and phone model coordinator against macOS; it does not compile SwiftUI/UIKit.

Explicit preparation and real inference (model terms are printed; test acceptance stays in the isolated fixture store):

```sh
mobile/native/ios/build.sh macos-runtimes
python3 mobile/ios/scripts/fetch-smoke-models.py --accept-test-licences
mobile/ios/scripts/real-inference.sh
mobile/ios/scripts/native-load-test.sh
# Additional engine-only cloning and translation smoke:
python3 mobile/ios/scripts/fetch-smoke-models.py --accept-test-licences --extended
mobile/ios/scripts/auxiliary-inference.sh
```

The smoke fetcher verifies every file's size and SHA-256 from the actual shared catalogue, then stores files under ignored `.cache/inference-models/`. Inference tests themselves use only these local files. Kitten produces actual audio, Whisper transcribes it back, and Zipformer emits incremental and final text. The same smoke cancels real TTS after observing native progress. The engine-only smoke clones synthetic reference speech with OmniVoice and translates English to French with Qwen through llama. These tests do not grant acceptance in the app's model store.

With full Xcode, prepare the native frameworks before generating or building the app:

```sh
mobile/native/ios/build.sh ios
xcodegen generate --spec mobile/ios/VoiceStudio/project.yml
xcodebuild -project mobile/ios/VoiceStudio/VoiceStudio.xcodeproj \
  -scheme VoiceStudio -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild -project mobile/ios/VoiceStudio/VoiceStudio.xcodeproj \
  -scheme VoiceStudio -destination 'platform=iOS Simulator,name=iPhone 16' test
```

Choose an installed simulator name. The native build verifies pinned artifacts, builds missing simulator slices and exposes the frameworks expected by `project.yml`; see `mobile/native/ios/README.md` for integrity details and transitive checksum limits. No native libraries or model binaries are committed.

## Phone inference and models

`VoiceStudioKit/LocalEngine` is the single feature-facing interface: synthesize, clone, transcribe, streamTranscribe and translate. C runtime handles remain on detached workers; an atomic cancellation token crosses tasks. TTS uses sherpa Kitten/Kokoro, offline ASR uses Whisper, and streaming ASR uses the catalogue's Zipformer family. Streaming preserves endpoint finals, produces a final session transcript and rejects sample-rate changes. Whisper handles long input in 30-second windows while reusing the recognizer. Its native decode has no abort callback: cancellation is checked between windows and the current decode must return before cleanup. TTS and OmniVoice cancel through their native callbacks; llama checks between tokens and through its CPU abort callback. Progress reports loading/running/finished; native APIs without fractional callbacks remain indeterminate during the current step. Every locally generated WAV passes `markSynthetic`, which adds a synthetic-audio INFO comment.

Speak and Dictate remember independent This phone / My computer choices. Without a choice, a compatible installed and accepted phone model wins; otherwise a paired computer wins; otherwise an inline model/size prompt links to Models. An explicit computer choice without a paired host links to Connect. Speak offers model and preset speaker choices and uses the existing playback, waveform, seeking, sharing and saving controls. Dictate captures mono PCM16 at 16 kHz and sends it directly to `LocalEngine` on the phone route. Neither phone path requires a computer or makes a network request.

Models decodes the generated `mobile/contract/models.json`, bundled at build time alongside the locale catalogs. Unknown fields are ignored. Invalid revisions, hashes, unsafe file paths, sizes, duplicate IDs and runtime/capability mismatches are rejected. Cards show size, languages, licence and actual disk usage. Unsupported RAM requirements stay visible with an explanation and cannot download or load. Models has Download, Cancel, Delete, a total storage counter and an explicit mobile-data toggle.

Downloads start only from a user action. Four-MiB HTTP ranges persist across cancellation and relaunch; servers ignoring ranges can return a complete file. Hugging Face is attempted first, then hf-mirror.com. A dedicated cookie/credential-free session permits only HTTPS HF/mirror delivery domains (including signed HF CDN redirects); host credentials and referrers are never forwarded. Wi-Fi-only is enforced by both the local path check and URLSession's cellular/expensive-network policy unless mobile data was allowed. Files stay under private Application Support, excluded from backup. Each file is size/SHA-256 verified before installation and hashed again before native loading. Active leases prevent delete/replacement during inference. Downloads interrupted by suspension resume from persisted ranges when the user starts them again; continuous background model downloading is not promised.

Every non-commercial, conditional, unidentified or explicitly gated model requires acceptance before download and load. The phone shows all supplied licence metadata and full catalogue terms, records the supplied terms fingerprint, actual app version and time, and retains the latest 20 actions locally. Changed terms block loading again; withdrawal immediately blocks new use and downloads. Acceptance is independent of the computer. Delete removes weights and partial files, preserving licence history.

OmniVoice's `tokenizer` role is its audio codec. The clone adapter takes mono 24-kHz reference audio plus its transcript. Translation uses the catalogue's prompt template and a bounded 2,048-token context. These methods are integrated and tested without adding phone Voices or Dub flows.

## Computer workflows

Connect accepts the desktop Network QR or manual URL/PIN/API key. Health validation rejects unrelated services. API keys are exchanged once for bearer sessions and never saved. Keychain uses `AfterFirstUnlockThisDeviceOnly`; host metadata and job checkpoints use local preferences. PIN-only pairing authorizes HTTP consumption, not remote dictation. Disconnect revokes bearer sessions and clears local credentials even when the host is unavailable. Failed pairing preserves the current host; host changes cancel old operations and clear host-scoped media/data. Redirects are rejected for every paired-host request. Public hosts require HTTPS and system certificate validation; private/LAN/Tailnet hosts may use HTTP.

Computer Speak retains engine/language/profile choices, generation, authenticated playback, waveform/seeking, sharing/saving and history star/delete. Voices retains search, previews, consent-gated recording/file cloning, rename and delete. Dub retains device file/URL ingest, multiple target tracks, voice selection, persisted upload/job monitoring, abort/history/download/share and completion notifications. Computer Dictate uses authenticated WebSocket tickets, PCM16/16 kHz and EOF finalization. Remote or undiscoverable LLM translation destinations require equal-weight consent per host/job/provider; only verified host-loopback endpoints avoid this prompt.

Background URLSession persists computer uploads and completion receipts through relaunch. A refused background session falls back to a foreground transfer with retained staging; that fallback needs app runtime. BGProcessing monitoring is opportunistic and resumes at the next foreground/granted runtime; there is no push relay or guarantee while force-quit. Original media filenames persist through picker display, multipart staging, checkpoints and history. The host pipeline follows upload/ingest → prep events → transcribe → translate → generate → render events; backend task IDs and dub media job IDs are distinct. A crash between host acceptance and client checkpoint persistence can require host inspection before retrying because render has no client idempotency key.

## Resources, privacy and accessibility

Theme roles are generated from Electron; never edit `Tokens.generated.swift`. The maintainer regenerates shared inputs with `bun scripts/export-mobile-tokens.ts`, `uv run python scripts/export_openapi.py` and `uv run python scripts/export_mobile_models.py`. These affect both platforms and are not iOS build steps. Resource preparation copies the actual Electron catalogs, shared/platform mobile additions, desktop language catalog and models catalogue. New iOS keys live only in `mobile/contract/strings.ios-additions.en.json` until translation merge. Localization supports interpolation, plurals, language/English fallback and Chinese script/region selection.

Settings, appearance and language work without pairing. Permissions are requested at first use. No analytics SDK, push service, Bonjour discovery, account or crash reporter is linked; analytics consent records only a local preference. On-device tasks send nothing; networking is limited to explicitly started model downloads and paired-host requests. Inter and the app/runtime licences are shown under About. All colors come from theme tokens; controls use Dynamic Type, minimum 44-point targets, scrollable layouts and localized accessibility labels.

## Verification limits and interpretations

Verified with CLT: the strict Swift 6 package suite (92 tests including three opt-in native tests), macOS platform-wrapper type-checks, resource generation, XcodeGen generation and app/UI-test syntax parsing. Separate opt-in runs verify all three actual native libraries, Kitten/Whisper/Zipformer inference, OmniVoice cloning and Qwen translation. The tiny Zipformer recognizes the ending phrase of the synthetic smoke sentence; this is an inference check, not a transcription-accuracy claim.

The iOS xcframework build/link, SwiftUI compilation, simulator UI tests, physical-device model RAM/thermal behavior, download/cellular transitions, microphone/local-network/QR permissions, VoiceOver/largest Dynamic Type, signing, background uploads and real-host end-to-end workflows require full Xcode/device validation. macOS inference does not prove iOS execution.

Contract interpretations: the optional catalogue `licence.terms` contains the full disclosure and is displayed when supplied; the fingerprint remains catalogue-authoritative. HF's signed delivery CDNs are allowed only within its HF-owned delivery domains, because normal model resolve URLs redirect there. Downloads resume at verified range boundaries rather than URLSession opaque resume blobs. The pinned llama prebuilt lacks a simulator slice, so that slice is built from the same pinned source. Missing transitive SHA-256 fields in shared pins are documented in the native README. No phone clone/dub UI or local voice persistence is included in this phase.
