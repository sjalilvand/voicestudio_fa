# iOS native runtimes

`build.sh` reads `../pins.json`; it never chooses a newer runtime or changes git state. Native binaries, downloads, extracted sources, CMake trees and receipts stay in ignored `build/`. Generated C headers stay in ignored `mobile/ios/VoiceStudioKit/Sources/VSNative/include/generated/`.

Requirements: Python 3.9+, curl, CMake and macOS. `ios` additionally requires full Xcode, its iOS/device and simulator SDKs, and the tools used by the pinned upstream build scripts. Command Line Tools are sufficient for all macOS checks below.

```sh
# From the repository root:
mobile/native/ios/build.sh macos-sherpa
mobile/native/ios/build.sh macos-runtimes
mobile/native/ios/build.sh ios
```

- `macos-sherpa` downloads the arm64 shared archive, verifies the SHA-256 in `pins.json`, verifies the pinned sherpa source tree and prepares its C header. It prints `SHERPA_ONNX_LIBRARY`.
- `macos-runtimes` also builds the pinned OmniVoice and llama shared libraries for CPU tests, fetches OmniVoice's exact ggml gitlink, and prepares all C headers. It prints each library path. No model is downloaded.
- `ios` checks for an iOS SDK before fetching anything. It invokes sherpa's pinned `build-ios.sh`, verifies and uses llama's pinned prebuilt device framework, builds llama's missing simulator slice with its pinned `build-xcframework.sh ios-sim`, and builds OmniVoice for device arm64 and simulator arm64/x86_64 using CMake/Xcode. It exposes all four frameworks under `build/xcframeworks/` for XcodeGen: sherpa, ONNXRuntime, llama, and OmniVoice.

The llama framework and OmniVoice framework are dynamic and must be embedded/signed. Sherpa and ONNXRuntime are static. OmniVoice includes its own static ggml with only `ov_*` symbols exported, keeping its ggml ABI separate from llama's. Metal is enabled for iOS and its shader source is embedded. The macOS test builds use CPU and do not require a Metal compiler. Archive-built OmniVoice is stamped with its actual pinned commit, rather than the enclosing VoiceStudio checkout's commit.

Source archives are addressed by the full commit in `pins.json`. Every extracted source blob is verified against the GitHub Git tree for that commit (including the exact ggml submodule); the cache records each archive's SHA-256. Unused absolute symlinks in upstream Go examples become inert text with the same Git blob bytes. No git clone/checkout is used. Downloaded prebuilt artifacts must match the SHA-256 in `pins.json`. Build outputs are hashed into a receipt and checked before cache reuse; the iOS cache key includes the pins, build script hash and Xcode/SDK versions. Incomplete builds are discarded before retry.

ONNXRuntime's dependency version is taken from sherpa's pinned `build-ios.sh`; environment overrides to a different version are rejected. Its archive is downloaded and SHA-256 checked against the release asset's recorded digest before upstream runs, avoiding upstream's unchecked wget download. Sherpa's other CMake dependencies use its pinned source's URL hashes. **The shared `pins.json` does not contain source-archive or transitive ONNXRuntime SHA-256 entries.** Source integrity therefore uses the pinned Git tree, and ONNXRuntime uses its upstream release digest; these are distinct from a complete, self-contained SHA-256 lockfile. The platform script does not invent or modify shared pins.

The iOS frameworks and their combined device/simulator linkage require Xcode validation. They cannot be built or linked on a CLT-only installation. Use `mobile/ios/scripts/native-load-test.sh` and the real model tests described in `mobile/ios/README.md` for macOS verification; those do not imply an iOS SDK build passed.

The `VSNative` shim owns fixed C callback signatures, copied result memory and cancellation flags. Its Whisper segment adapter enables token timestamps on the pinned C API and returns owned speech envelopes for 20-second windows. Streaming fixes its sample rate from the first chunk and pads its tail at that rate. Voice and dub features use the `VoiceStudioKit.LocalEngine` protocol with this same shim on macOS and iOS. `mobile/ios/scripts/auxiliary-inference.sh` runs the real reference/clone and audio-dub workflows sequentially; the application uses the xcframeworks without changing feature code.
