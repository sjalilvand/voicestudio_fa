# VoiceStudio Android

Native Kotlin / Jetpack Compose app with phone-first speech and dictation,
plus an optional connection to a user-owned VoiceStudio computer. Installed
models run offline. No cloud relay, analytics transmission, crash reporter or
push service is used.

## Prerequisites

- JDK 21 (AGP does not support the machine's default JDK 27).
- Android SDK platform 36 and build tools; minimum device API 29.
- Internet for the first Gradle/dependency/native-source download; NDK
  27.1.12297006 and SDK CMake 3.22.1.
- Optional: a VoiceStudio computer with Network sharing enabled, or a private
  server/Tailscale URL, for computer tasks. Phone model installation and
  licence acceptance are available without a computer.

From this directory:

```sh
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
# Elsewhere, use your own JDK and SDK paths.
printf 'sdk.dir=%s\n' "$ANDROID_HOME" > local.properties
./gradlew assembleDebug
./gradlew testDebugUnitTest
./gradlew lint
./gradlew assembleDebugAndroidTest
```

Windows: Gradle uses `gradlew.bat`; native preparation also needs Bash and
Python 3, with equivalent JAVA_HOME / ANDROID_HOME settings. This host verifies
the macOS build path.
`local.properties`, build outputs and local IDE state are ignored. Gradle 8.13,
AGP 8.12.0, Kotlin 2.2.21 and direct dependencies are pinned in the wrapper and
`gradle/libs.versions.toml`. The wrapper was generated using installed Gradle
9.8.1. Compilation runs inside Gradle to avoid Kotlin daemon files outside
sandbox writable directories; parallel workers are capped for this shared host.
The version name/code are derived at configuration time from root `package.json`.

## Layout

- `app`: launcher, Navigation Compose, consent, generated asset packaging, JVM UI
  smoke/contract tests.
- `core/designsystem`: immutable generated `VSTokens`, token-to-Material role
  mapping, shapes, Inter typography, appearance preferences.
- `core/network`: typed REST responses and multipart operations, guarded OkHttp
  transport, private-address policy, cancellable requests and ticketed dictation.
- `core/data`: DataStore preferences/saved hosts, AES-GCM/Android Keystore session
  vault, durable WorkManager dub pipeline and local notifications.
- `core/local`: typed catalogue, resumable verified downloads, local licence
  receipts, per-model inference/deletion leases and the `LocalEngine` adapters.
- `core/l10n`: nested catalog lookup, interpolation, locale/plural fallback.
- `features`: separate `connect`, `speak`, `voices`, `dub`, `dictate`, `settings`
  packages with shared native controls, playback, capture and permission helpers.
  The six feature packages share one Gradle module to avoid six identical build
  configurations and cross-module UI plumbing in this companion-sized app.

## Screens and behavior

All five tabs are reachable without pairing. Consent dismissal means No.
Speak and Dictate offer This phone / My computer, remember the choice per task,
and prefer an installed phone model; otherwise they use a paired computer or
show an inline model download prompt. Settings opens Connect and Models.
Voices and Dub explain their computer requirement when unpaired; their
on-device feature flows are outside Phase A.
Connect supports CameraX/ZXing QR scanning, manual URL/PIN/API-key entry, saved
hosts, labels and last-seen timestamps. Public `/health` must carry the backend
marker and expected status/version; `/profiles` verifies consumption access.
Master keys only enter the session exchange and are never persisted. Session
and PIN ciphertext is stored using a Keystore AES-GCM key; DataStore contains
only connection metadata/preferences and dub checkpoints. A 401 returns to
pairing when it belongs to the active connection; a failed attempt on another
host leaves the active session intact. Disconnect revokes an administrator
session when one exists and clears local access even offline. PIN-only pairing
has no session to revoke. Reconnecting retains a saved host's label and updates
its last-seen timestamp. Unreadable preferences or malformed persisted JSON
fall back to defaults rather than preventing launch.

Connecting/reconnecting resets host data, the navigation tree and its saved
forms, pending document targets, players and dictation controllers. Switching to
a different host or disconnecting cancels the old host's WorkManager jobs and
clears dub checkpoints; checkpoint keys also include the host, and late writes
from inactive hosts are rejected. Reconnecting to the same host retains durable
job monitoring. Long jobs already running on the old computer continue there.

All forms resize their scroll viewport for the keyboard. Background taps,
primary/secondary actions and navigation dismiss focus; single-line fields have
the native Done action. The multiline Speak editor keeps Return for newlines
and offers a visible Done toolbar while focused. Rename and picker dialogs use
their own window's focus manager. Android retains its normal keyboard-first Back
handling; reaching Generate only requires scrolling or Done.

Picker labels take their intrinsic single-line width; values fill the remaining
space, align to the trailing edge and ellipsize to one line. The full value
remains in the accessibility description, and choice lists allow two lines per
name. This applies to voice, engine, language, palette and dub targets. Every
searchable list shows the query when no matches remain.

Tabs render their content without navigation fades. Language catalogs and locale
mapping load off the UI thread and are cached; Speak and Dub show inline loading
indicators with their controls already visible. History/profile refreshes show
inline progress rather than hiding the screen. Dictate keeps its controls visible
while checking readiness.

Speak has text, backend voice/engine/language pickers, generation, host-streamed
Media3 playback, an accessible seek/progress slider, system share/save, and
recent history with star/delete. Voices has search, previews, rename/delete,
permission-gated recording or file selection and explicit clone consent.

Dub keeps a device document's `OpenableColumns.DISPLAY_NAME` separately from its
private cached path, shows that name, and sends it as the upload filename so host
history retains it. Remove deselects the private copy and names the file for
accessibility. History uses grouped title/metadata rows with compact, named save
and share icons. Save opens the system document picker; Share opens the share
sheet.

Dub accepts device media or a link for the host to ingest, multiple target
languages and an explicit voice choice: **Default voice (engine preset)** or a
saved profile. There is no source-voice choice. Desktop source cloning uses
`dub-session.ts:readTranscript` and `/dub/transcribe-stream/{job_id}` to prepare
`cast_sources` / `speaker_clones`, then `applySpeakerCloneDefaults` assigns
`auto:` profile IDs carried into `/dub/generate/{job_id}` by `segmentGenInputs`.
The synchronous `/dub/transcribe/{job_id}` used by M1 returns no cast-reference
metadata. Both mobile apps therefore use the honest preset/profile choice;
an empty `profile_id` explicitly means the engine preset, never source cloning.

Before creating a job, Dub fetches `/engines/translation`, selects exactly its
`active` ID, and requires positive `installed` and `ready` fields. Missing or
unready engines direct the user to VoiceStudio Settings on the computer. An
`online` engine names the service and requires confirmation for that job using
equally styled Allow/Decline buttons; dismissal and decline start no upload or
translation. LLM engines also require that consent unless the resolved
`dub_translation` skill and provider metadata positively identify a loopback
endpoint on the host. `/api/settings/llm-skills` and `/api/settings/llm-providers`
expose this metadata on authorized server hosts; desktop LAN hosts forbid these
admin reads, so an unknown LLM route requires consent. The public translation
inventory's `configured_via` names the service when available. Provider names and
the provider's `local` flag alone do not prove locality: base URLs can be
overridden. Only literal loopback IPs and `localhost` qualify, without any DNS or
provider calls from the phone. Approval is scoped to a single durable job. The
worker rechecks the active provider and a fingerprint of its resolved endpoint
before starting/resuming and immediately before every translation request, and
refuses changed routing; every
`/dub/translate` body contains the explicit authorized `provider`. Existing jobs
without provider metadata fail with recovery advice instead of using a fallback.
WorkManager copies no credentials into job input. It
uploads, waits for prep, transcribes, translates each track, starts generation,
and replays persisted job events while polling. Checkpoints resume existing host
tasks after app process death or connectivity loss. Abort stops the host before
cancelling the worker. Downloads use the guarded client and a FileProvider share.
The worker requests a data-sync foreground service for long uploads. If Android
refuses that start, work continues within WorkManager's normal execution limits;
cancellation still stops it. The merged manifest declares `FOREGROUND_SERVICE`,
`FOREGROUND_SERVICE_DATA_SYNC` and a `dataSync` WorkManager service. Notification
permission is not required to upload/promote the service; it gates optional
completion notifications. Security failures and initialization/input failures
produce actionable Dub errors. Failed job receipts are shown once and acknowledged
in DataStore across screen recreation, app restarts and host switches. Cancelled
jobs show a cancellation status instead of a failure. Successful job download
actions remain available. Optional completion notifications are generated locally,
without a push service.

Dictate checks readiness and streams mono 16 kHz signed PCM over the host
WebSocket, using a one-use ticket for sessions. Tap/hold controls, partial/final
transcripts, copy/share and lifecycle-based microphone cleanup are included.
Sherpa utterance finals append without stopping capture. Only summary/legacy EOF
finals or socket termination end a session; authoritative/refined summary text
replaces the live transcript without duplication, and empty summaries preserve
committed phrases. Unknown final kinds are ignored, matching desktop. Callbacks
and cleanup are scoped to the recording generation, so an old stream ending
cannot close the next session.
Readiness names the missing ASR model and its size, with the desktop install
location. API-key/trusted-network advice appears only after an authorization
failure; a share PIN alone does not authorize dictation. Settings includes live appearance, per-appearance palettes,
system/desktop languages, notification permission, privacy, version and licenses.

## Shared inputs

Run these from the repository root only when intentionally regenerating shared
inputs (this Android implementation does not edit them):

```sh
uv run python scripts/export_openapi.py
bun scripts/export-mobile-tokens.ts
```

Gradle's `:app:bundleCatalogs` copies all Electron locale JSON files and
`mobile/contract/strings*.en.json` into generated assets on every input change.
It also bundles `electron/src/shared/languages.json` (the canonical display
names, with Auto first) and generates the manifest label from English `app.name`.
Only the selected locale's fallback chain is parsed, with catalogs and L10n
instances cached per locale. Chinese script/region tags map to the bundled
zh-CN (Hans) and zh-TW (Hant, HK, MO) catalogs before English fallback.
No copied catalogs are checked in. New Android-only keys live in
`mobile/contract/strings.android-additions.en.json`; untranslated mobile keys
fall back to English until the maintainer integrates their translations.
The checked-in generated token file is never edited by Android development.
OpenAPI is read as the contract; typed models reflect loose responses verified
against backend router implementations. No guessed endpoints are used.

Inter 4.1 variable TTF comes from the official rsms/inter GitHub release.
The release zip SHA-256 is
`9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`.
`OFL.txt`, `Apache-2.0.txt` and dependency notices are bundled under licenses and
available offline in About.

## Contract decisions and limits

- Android network-security XML cannot express IP CIDRs. The XML enables the
  transport; the sole OkHttp client is the security boundary: HTTP URLs must be
  loopback, RFC1918, CGNAT, IPv4/IPv6 link-local, IPv6 ULA, `.localhost`, `.local`
  or `.ts.net`. DNS results for HTTP must also be private, preventing rebinding
  to a public address. Other hosts require HTTPS with system trust. Redirects,
  unpaired origins, URL credentials and credential query parameters are rejected.
  Media3 uses this same client; no WebView/DownloadManager bypass exists.
- There is no `/languages` route. Both pickers use the build-bundled desktop
  `languages.json`; Speak defaults to Auto, or a selected profile's language.
  Dub excludes Auto, maps names to ISO codes through Android locale data when
  available, and preserves the canonical name for long-tail languages. The
  host determines which languages its selected translator/engine supports.
- `/engines` is loosely typed in OpenAPI; its router supplies `display_name`,
  `active`, `available`, `reason`, `hint` and `supports_cloning`. Select the active
  engine when eligible, otherwise an eligible fallback. A reference-bearing
  profile requires positive cloning support. Default voice sends no `profile_id`.
- Palette labels come directly from generated tokens, except Default uses the
  desktop `themeAppearance.default` translation. The large native screen title
  derives its scale from editor/UI tokens; controls/cards use 8/10 dp token radii.
- `/generate` returns a WAV with `X-Audio-*` headers, not JSON. Playback streams
  its canonical `/audio/...` host file. The progress scrubber satisfies the
  waveform/progress option; no synthetic waveform is fabricated.
- Dub is the host's ingest/prep → transcribe → translate → generate pipeline,
  with `/jobs/{id}/events` replay and `/jobs/{id}` status. WorkManager retries
  transient transport/service failures and keeps completed stage checkpoints.
  The backend has no atomic idempotency key for starting generation; a process
  dying after host acceptance but before checkpoint persistence can repeat that
  stage. Remote jobs themselves continue on the host.
- Models and their licence acceptance are managed on the phone for phone
  tasks. The separate computer model-licences link opens the paired host UI.
  Computer model setup remains on the host; no admin endpoint is exposed.
- No blur or custom motion is used. Compose follows the system animation scale;
  all content scrolls, text scales, touch targets are at least 48 dp. Large font
  scales show labelled navigation icons without squeezed tab text. A visible
  text field or backend-provided name is used for each interactive choice.

## On-device models and inference

Gradle bundles the generated `mobile/contract/models.json` with the locale
catalogues. Unknown fields are ignored; invalid revisions, checksums, file
paths, sizes, runtime/capability pairs and schema versions fail closed. No
catalogue or model is fetched when a tab is opened. Model IDs and declared
metadata are displayed from that bundle.

Models shows languages, declared licence, model size, actual on-disk storage,
Download / Cancel / Delete and the total space used. Models above the phone's
physical RAM are disabled, using decimal GB (`min_ram_gb * 1,000,000,000`).
Downloads start only from a user action, use Hugging Face with hf-mirror.com
fallback, resume with HTTP Range, enforce Wi-Fi unless mobile data is explicitly
allowed, and reject low storage. A server ignoring Range restarts that file.
Redirects stay HTTPS on Hugging Face/HF CDN or mirror hosts. The dedicated
client never carries computer credentials. Incomplete files remain resumable;
Delete removes them too. Every file must match size and SHA-256 before an
installation marker is written; files are hashed again before a native load.

Phone files and local licence receipts live under Android's `noBackupFilesDir`;
they are app-private and excluded from cloud and device backups. Non-commercial,
conditional, unknown and explicitly gated licences block download and load until
accepted locally. The dialog displays the bundled complete inert `licence.terms`
disclosure, attribution and fingerprint. Receipts store that fingerprint, app
version and timestamp; the latest 20 accept/withdraw actions are retained.
A changed fingerprint or withdrawal blocks use without deleting weights.

`LocalEngine` exposes cancellable, progress-reporting TTS, reference cloning,
offline transcription, streaming transcription and translation. Feature screens
call only this interface. sherpa uses Kitten/Kokoro for TTS, Whisper in at most
20-second windows for offline ASR, and Zipformer with utterance endpoint resets
for live dictation. Tap/hold capture releases on lifecycle stop and screen
exit; normal Stop drains the recognizer for its final transcript. Generated
speech supports local playback, scrubbing, sharing and Save. WAV exports pass
`markSynthetic`, which writes a RIFF INFO synthetic-audio provenance marker.

OmniVoice and llama are callable through the interface; no phone Voices or Dub
flow is included. OmniVoice accepts mono float PCM at 24 kHz plus reference text
and resolves the catalogue's tokenizer GGUF as its codec. Translation expands
the pinned model's prompt, tokenizes it once, and uses a bounded 2048-token
context and 512 generated-token limit with greedy sampling. Reference audio
and translation segmentation/mixing are responsibilities of their feature
callers. Native builds, checksums and cancellation boundaries are documented in
[`../native/android/README.md`](../native/android/README.md).

## Verification

Run from this directory with JDK 21 and the SDK environment above:

```sh
mkdir -p build/hf-empty
export HF_HUB_OFFLINE=1
export HF_HUB_CACHE="$PWD/build/hf-empty"
./gradlew assembleDebug
./gradlew testDebugUnitTest
./gradlew lint
./gradlew assembleDebugAndroidTest
```

The current host run passed all four Gradle tasks: 103 JVM tests, zero failures
or skips, and zero lint errors. Debug app and instrumentation APKs build for
arm64-v8a and x86_64; instrumentation is not executed here.

JVM checks cover existing M1 API/security, storage, worker, picker, protocol and
Compose smoke regressions, plus local catalogue/routing, licence persistence and
withdrawal, HTTP resume and restart, checksum rejection, mirror fallback,
Wi-Fi/mobile-data policy, low storage, cancellation, deletion, synthetic WAV
metadata, native cancellation control and microphone lifecycle cleanup. The
launch → consent → Settings → Connect → mock host → Speak → Play smoke preserves
the computer flow. Tests use local mock servers and an empty HF cache.
Robolectric's API 34 instrumented SDK is resolved by Gradle into app build
outputs and then used offline.

`LocalInferenceTest.allPinnedNativeLibrariesLoadTogether` checks native symbol
resolution on ART. The real model smoke is enabled only with instrumentation
argument `localInferenceSmoke=true`. It uses a separate private cache and requires
explicit prior review and `acceptModelLicencesForSmoke=true` for gated models.
`downloadSmokeModels=true` explicitly provisions the three smallest TTS/offline
ASR/streaming ASR selections; omit it on subsequent offline runs. It asserts
nonempty audible PCM, Whisper recognition of generated speech and a final
Zipformer transcript. No CI workflow is changed by this Android role; the
maintainer must wire/run it on the x86_64 emulator and physical devices.

This environment builds instrumentation only. Native loading on ART, real model
inference (including OmniVoice clone quality and llama translation), audible
playback, microphone permissions, device RAM behavior and background/notification
behavior require maintainer device/emulator verification. No adb or device
commands are used here.
