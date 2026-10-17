# VoiceStudio for iOS — M1 companion

Native SwiftUI companion for a paired VoiceStudio desktop/server. iOS 17+, iPhone and iPad. No inference, accounts, telemetry transmission, push services, third-party packages, or app requests to services other than the paired host.

## Prerequisites

- Swift 6 / Swift 6.2.3 Command Line Tools for the macOS package checks; Python 3 for resource generation and the real loopback mock-server test.
- XcodeGen 2.46 (`brew install xcodegen`).
- Full Xcode with the iOS SDK and an iOS 17+ simulator/device to compile/run the app and UI tests. Signing requires your own development team for a device.
- A running VoiceStudio host with Network sharing, Tailscale, or an HTTPS URL enabled. The phone never enables host sharing or downloads models. Install required models and accept their licenses on the host.

Run these from the repository root:

```sh
mobile/ios/scripts/check-swift.sh build
mobile/ios/scripts/check-swift.sh test
mobile/ios/scripts/check-platform.sh
xcodegen generate --spec mobile/ios/VoiceStudio/project.yml
python3 mobile/ios/scripts/prepare_resources.py \
  --output mobile/ios/.generated/bundle \
  --info-output mobile/ios/.generated/Info.plist
swiftc -frontend -parse mobile/ios/VoiceStudio/App/*.swift \
  mobile/ios/VoiceStudio/Features/*.swift mobile/ios/VoiceStudio/Platform/*.swift \
  mobile/ios/VoiceStudioUITests/*.swift
```

`check-swift.sh` runs `swift build` / `swift test` with package and scratch paths under `mobile/ios/`, redirects module caches there, and disables SwiftPM's nested sandbox for restricted development environments. For CLT installations, it supplies the installed `Testing.framework` search/link/rpath flags, disables the missing optional `_Testing_Foundation` cross-import overlay, and selects Swift Testing without XCTest; no test dependency download is necessary. On ordinary Xcode installations, `cd mobile/ios/VoiceStudioKit && swift build && swift test` also works.

With full Xcode:

```sh
open mobile/ios/VoiceStudio/VoiceStudio.xcodeproj
xcodebuild -project mobile/ios/VoiceStudio/VoiceStudio.xcodeproj \
  -scheme VoiceStudio -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild -project mobile/ios/VoiceStudio/VoiceStudio.xcodeproj \
  -scheme VoiceStudio -destination 'platform=iOS Simulator,name=iPhone 16' test
```

Choose an installed simulator name (`xcrun simctl list devices available`). Run the VoiceStudio scheme, decline or accept the local analytics preference, then scan the desktop Network QR or enter the host URL/PIN/API key. API keys are exchanged once for an administrator session and never saved. A PIN authorizes HTTP consumption, not remote dictation; dictation needs a session or a host-configured trusted network.

## Layout

- `VoiceStudioKit/`: Swift 6 package, iOS 17 and macOS 14. Typed HTTP client/models, redirect and cleartext policy, pairing parser, Keychain vault, observable session store, localization, theme resolution, dictation WebSocket, and persisted dub workflow.
- `VoiceStudioKit/Tests/`: Swift Testing contract tests, mock-transport integration tests, and a real Python loopback HTTP server exercising URLSession.
- `VoiceStudio/App/`: app lifecycle, Observation model, token-based native theme, consent and navigation.
- `VoiceStudio/Features/`: Connect, Speak, Voices/clone, Dub, Dictate, Settings/Privacy/About/licenses.
- `VoiceStudio/Platform/`: AVFoundation recording, PCM streaming, AVPlayer authenticated range loading and waveform extraction, AVCaptureSession QR, background URLSession upload/receipts, deterministic UI-smoke transport.
- `VoiceStudioUITests/`: launch → consent → mocked pairing → generate a valid WAV → play. `--ui-smoke` selects a transport that opens no sockets.
- `scripts/prepare_resources.py`: build-phase resource and version generation.

Speak includes backend engine/language and profile choices, playback, waveform/seeking, system share/save, history star/delete. Voices includes search, previews, consent-gated microphone/file cloning, rename/delete. Dub supports device media or host URL ingest, multiple target tracks, voice selection, persisted job/event polling, abort/history/download/share. Dictate sends mono PCM16 at 16 kHz with single-use WebSocket tickets and EOF finalization. Settings includes saved hosts, mode and independent light/dark palettes, system/desktop language choices, local notification permission, privacy, app/font licenses and a link to the paired host for model licenses.

Permissions are requested at first use. InfoPlist localization uses the mobile permission keys. No Bonjour, APNs, FCM, analytics SDK or crash reporter is linked. Disconnect attempts server revocation and clears the local session even if the host is unavailable. Session/PIN secrets use Keychain with `AfterFirstUnlockThisDeviceOnly`; host metadata and job checkpoints stay in local preferences. Requests reject redirects and public cleartext; TLS uses system certificate validation. Reduced transparency uses opaque token surfaces throughout, and there are no custom motion effects. Inter uses Dynamic Type scaling; controls have at least 44-point targets and content scrolls at large sizes.

## Shared inputs and version

Do not edit `VoiceStudioKit/Sources/VoiceStudioKit/Theme/Tokens.generated.swift`.

The maintainer regenerates shared inputs from the repository root:

```sh
bun scripts/export-mobile-tokens.ts
uv run python scripts/export_openapi.py
```

Those commands update shared files and both platforms; they are intentionally not part of an iOS build. The package theme maps generated roles and falls back to the default palette for missing appearances. Dark/default is the initial preference.

Each app build copies the actual `electron/src/renderer/src/i18n/locales/*.json`, `mobile/contract/strings*.en.json`, and `electron/src/shared/languages.json` into `Catalogs/`; no catalog copies are committed. It also extracts the desktop `LANG_CODES` mapping from `electron/src/shared/utils/languages.js` into a derived `language-codes.json`. The same script creates localized permission descriptions and reads root `package.json` into the derived Info.plist `CFBundleShortVersionString`. There is no mobile version mirror. Existing translations use locale → language → English → key fallback. New mobile strings fall back to the contract English until the maintainer merges translations into desktop catalogs. iOS additions live only in `mobile/contract/strings.ios-additions.en.json`.

InterVariable.ttf is from the official [Inter 4.1 release](https://github.com/rsms/inter/releases/tag/v4.1). Its SIL OFL is bundled as `Resources/Licenses/OFL.txt`; VoiceStudio's AGPL license is bundled alongside it and both appear in About.

## Verification and remaining device checks

Verified here: macOS Swift package build and 51 Swift Testing tests (including parameterized cases), strict-concurrency macOS type-checking of the background-upload, media-loader and smoke-transport wrappers, all palette/role values against the contract JSON, interpolation/plural/fallback/key coverage, QR/manual IPv4/IPv6 parsing, private/public cleartext boundaries, health fingerprint, PIN/session exchange/revoke/401 handling, multipart TTS and dub upload, job progress, persisted multi-language dub pipeline, host-only redirect rejection, XcodeGen generation, resource/version generation and app-source syntax parsing.

This machine has Command Line Tools only. The SwiftUI app and XCTest UI smoke have **not been compiled or run with an iOS SDK**. Full Xcode build, simulator smoke, real-device QR/microphone/local-network permission prompts, VoiceOver/largest Dynamic Type, Inter rendering, authenticated media playback, background upload/relaunch, task scheduling, notification delivery, and live-host end-to-end TTS/clone/dub/dictation remain unverified. Simulator/device testing is a release gate, not implied by syntax parsing.

## Contract interpretations and platform limits

- Health has no named OpenAPI response schema: require `status=ok`, `device`, `version`, and the real backend's `x-omnivoice-backend` version marker (`backend/main.py`). This rejects unrelated `/health` services.
- The session exchange returns `token`; the WebSocket ticket response returns **`ticket`**, which is sent under the **`ws_ticket`** query name. These loose-schema fields come from `backend/api/routers/auth.py`.
- Non-streaming `/generate` returns WAV bytes and `X-Audio-Id`, not JSON. Recent WAV playback uses the actual `/audio/<id>.wav` StaticFiles mount in `backend/main.py`; static mounts are absent from FastAPI's OpenAPI. Using the documented `.ogg` conversion endpoint would require an additional decoder on iOS 17. WAV range requests keep credentials in headers.
- There is no generic `/languages` endpoint. Both pickers use the bundled desktop language names in desktop order. Speak starts with Auto (omitted from the request) and accepts a profile language as either a name or ISO code. Dub excludes Auto; target codes come from desktop `LANG_CODES`, with ISO names resolved by Foundation for the remaining languages. Names without a resolvable code remain visible but disabled with an explanation; the app does not invent codes. The host validates model and translation compatibility.
- There is no single “start dub” endpoint. The app follows upload/ingest → persisted prep-job events → transcribe → translate → generate per target → persisted render-job events. The polling key is the returned **task ID**, distinct from the dub media job ID. Acknowledged transitions and event sequence cursors are saved. The backend has no client idempotency key for render; termination between host acceptance and checkpoint persistence can require host-side inspection before retrying.
- iOS background URLSession continues file upload and persists completion receipts through relaunch. Host generation runs independently. BGProcessing is opportunistic: iOS does not promise continuous polling or an immediate completion notification while suspended/force-quit. Monitoring and local completion notifications resume at the next granted runtime/foreground launch. There is no push relay.
- Model-license navigation opens the paired host interface; M1 does not accept licenses or install models from the phone.

## PR #2965 review fixes, round 3

All four findings were present on iOS. Prior-round behavior and checks remain in place.

| Finding | Resolution and main files | Regression coverage (`VoiceStudioKit/Tests/VoiceStudioKitTests/Round3RegressionTests.swift`) |
|---|---|---|
| Implicit Google translation | `TranslationEngine.swift`, `APIClient.swift`, `DubWorkflow.swift`, `DubView.swift`: fetch `/engines/translation`, require its active engine to be installed/ready, and send its ID explicitly as `provider`. Online services display their host-supplied name with equal-weight Allow/Decline buttons. Declining sends no translate request. Approval belongs to the persisted host/job/provider, never a global preference; changing online services requires confirmation again. | `dubTranslationAlwaysNamesTheHostProvider`, `onlineTranslationRequiresPerJobConsent`, `changedOnlineEngineRequiresAnotherConfirmation`, `translationApprovalResumesOnlyItsPersistedJob`, `unavailableTranslationNeverFallsBack`, `emptyTranslationProviderCannotReachHost`. |
| Dictation stopped at first phrase | `Models.swift`, `DictationStream.swift`, `DictationTranscript.swift`, `DictateView.swift`: decode `final_kind` and `refined_text`. Utterance finals commit text and continue capturing; unknown/empty utterances are ignored. Only summary/legacy EOF finals finish. The whole-session summary replaces live text without duplication. | `sherpaUtteranceFinalsKeepTheActualStreamOpen` replays two phrases through the actual stream; `dictationSummaryReplacesCommittedPhrasesAndUsesRefinement`, `dictationLegacyEOFAndEmptySummaryTerminate` cover display state and termination. |
| Misleading source-voice option | `DubVoiceChoice.swift`, `SpeakView.swift`, `DubView.swift`: require an explicit voice choice and reuse the shared **Default voice (engine preset)** label. An empty `profile_id` means the engine preset; selecting a saved profile sends that ID. Source-voice cloning is not offered. This matches Android's chosen fallback. | `dubDefaultVoiceLabelDescribesEnginePreset`, `dubRequiresAnExplicitVoiceChoiceBeforeStarting`, `dubPresetAndClonedVoiceRequestsMatchTheirLabels`. |
| State retained across computers | `HostState.swift`, `SessionStore.swift`, `AppModel.swift`, `ThemeUI.swift`: synchronous scope changes clear generations, profiles, engines, both histories, dub checkpoints/approval, errors, and cancel work/monitoring. A new SwiftUI view identity discards host-specific selections, transcripts and share sheets; player teardown removes files/playback. `Audio.swift` rejects late loads; `BackgroundUpload.swift` scopes receipts; `DubUploadLedger.swift` serializes persisted completion against host changes. `ConnectView.swift`, `SettingsView.swift`, `SpeakView.swift`, `VoicesView.swift`, `DictateView.swift` connect those lifetimes to the UI. | `hostTransitionClearsAllStateAndPreventsOldAudioOnNewHost` covers switch, disconnect and 401, including cancellation before a stale audio ID can reach the new host. `lateGenerationCannotRepopulateAnotherHostPlayer`, `hostSwitchStopsDubMonitoringAndDiscardsLateEvents` cover delayed responses; `oldUploadCompletionCannotOverwriteAnotherHost` covers upload persistence. |

The translation inventory has a loose OpenAPI response. Its `active`, `engines`, `category`, `installed`, `ready`, and `display_name` fields follow `backend/api/routers/engines.py` and `backend/services/translation_engines.py`. Missing readiness never implies permission to translate. Checkpoints from earlier builds have no online approval and require confirmation before online translation.

The allowed source-voice fallback was chosen because desktop [readTranscript](../../electron/src/renderer/src/features/dub/dub-session.ts#L890) uses `/dub/transcribe-stream/{job_id}` to prepare speaker references and reads `cast_sources`/`speaker_clones`; [applySpeakerCloneDefaults](../../electron/src/shared/utils/segments.js#L182) binds `auto:<speaker>` profile IDs; desktop [generateDub](../../electron/src/renderer/src/features/dub/dub-session.ts#L1476) preserves those per-segment generation inputs. M1's current synchronous `/dub/transcribe/{job_id}` path explicitly clears references (`backend/api/routers/dub_core.py`) and does not prepare them. An empty profile is therefore an engine preset, and is no longer described as source-voice cloning. No endpoints, backend behavior, or generated tokens were changed.

Round-3 verification uses the six commands documented above: package build/test, platform wrapper type-check, XcodeGen, resources, and source parsing. The package tests verify the non-UI connection/dub lifetimes and scripted dictation protocol. Actual AVPlayer teardown, recording continuity, translated-job consent interaction, and host-switch screen reset still require the full Xcode simulator/device checks listed above; a macOS package test does not verify those iOS runtime behaviors.
