import Foundation
import CryptoKit
import Darwin
import Testing
@testable import VoiceStudioKit

private func localDirectory() throws -> URL {
    let url = repository.appendingPathComponent("mobile/ios/.generated/local-test-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}
private func localFixture(bytes: Data = Data("model".utf8), gated: Bool = false, capability: String = "tts", fingerprint: String = String(repeating: "a", count: 64)) throws -> PhoneModel {
    let runtime = capability == "clone" ? "omnivoice.cpp" : capability == "translate" ? "llama.cpp" : "sherpa-onnx"
    let object: [String: Any] = ["schema_version": 1, "models": [[
        "id": "fixture", "name": "Fixture", "capability": capability, "runtime": runtime, "repo": "owner/model", "revision": String(repeating: "b", count: 40),
        "files": [["path": "model.bin", "size": bytes.count, "sha256": SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), "role": "model"]],
        "total_bytes": bytes.count, "languages": ["en"], "min_ram_gb": 1,
        "licence": ["id": "test", "category": gated ? "non-commercial" : "commercial-ok", "requires_acceptance": false, "credit": "Fixture", "rights_holder": "Fixture", "terms_fingerprint": fingerprint],
        "config": ["model_type": "kitten", "prompt_template": "Translate {text} from {source_language} to {target_language}"]
    ]]]
    return try ModelCatalogue.decode(JSONSerialization.data(withJSONObject: object)).models[0]
}
private actor RangeServer: HTTPTransport {
    let bytes: Data
    var failAfter: Int?
    var corrupted = false
    var slowAfter: Int?
    private(set) var requests: [URLRequest] = []
    let events: AsyncStream<Int>
    let continuation: AsyncStream<Int>.Continuation
    init(bytes: Data, failAfter: Int? = nil, slowAfter: Int? = nil, corrupted: Bool = false) {
        self.bytes = bytes; self.failAfter = failAfter; self.slowAfter = slowAfter; self.corrupted = corrupted
        (events, continuation) = AsyncStream.makeStream()
    }
    func finishEvents() { continuation.finish() }
    func send(_ request: URLRequest) async throws -> HTTPReply { throw ClientError("mobile.local.download_error") }
    func download(_ request: URLRequest) async throws -> DownloadReply {
        requests.append(request); continuation.yield(requests.count)
        if let slowAfter, requests.count > slowAfter { try await Task.sleep(for: .seconds(30)) }
        if let failAfter, requests.count > failAfter { throw ClientError("mobile.local.download_error") }
        let range = request.value(forHTTPHeaderField: "Range")!.dropFirst(6).split(separator: "-").compactMap { Int($0) }
        let start = range[0], end = min(range[1], bytes.count - 1)
        var chunk = bytes.subdata(in: start..<(end + 1)); if corrupted { chunk[0] ^= 1 }
        let path = repository.appendingPathComponent("mobile/ios/.generated/range-" + UUID().uuidString)
        try chunk.write(to: path)
        return DownloadReply(file: path, status: 206, headers: ["content-range": "bytes \(start)-\(end)/\(bytes.count)"])
    }
}

@Test func localCatalogueValidatesPinsAndTraversal() throws {
    let url = repository.appendingPathComponent("mobile/contract/models.json")
    let actual = try ModelCatalogue.decode(Data(contentsOf: url))
    #expect(actual.models.count >= 7)
    #expect(actual.models.allSatisfy { !$0.files.isEmpty })
    for capability in ["tts", "asr", "asr-stream", "clone", "translate"] { _ = try localFixture(capability: capability) }
    let good = try JSONEncoder().encode(localFixture())
    let malformed = String(decoding: good, as: UTF8.self).replacingOccurrences(of: "model.bin", with: "../outside")
    let wrapper = "{\"schema_version\":1,\"models\":[" + malformed + "]}"
    #expect(throws: (any Error).self) { try ModelCatalogue.decode(Data(wrapper.utf8)) }
}
@Test func localDownloadResumesAcrossStoreRelaunchAndFallsBack() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let bytes = Data(repeating: 17, count: 4_194_304 + 73)
    let model = try localFixture(bytes: bytes)
    let first = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    let failing = RangeServer(bytes: bytes, failAfter: 1)
    await #expect(throws: (any Error).self) { try await first.download(model, wifi: { true }, transport: failing) }
    #expect(await !first.installed(model))
    #expect(await failing.requests.last?.url?.host == "hf-mirror.com")
    let restored = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    let server = RangeServer(bytes: bytes)
    try await restored.download(model, wifi: { true }, transport: server)
    #expect(await server.requests.first?.value(forHTTPHeaderField: "Range") == "bytes=4194304-4194376")
    #expect(await restored.installed(model))
    let path = try await restored.authorize(model)
    #expect(try Data(contentsOf: path.appendingPathComponent("model.bin")) == bytes)
    #expect(getxattr(root.path, "com.apple.metadata:com_apple_backup_excludeItem", nil, 0, 0, 0) > 0)
    try await restored.delete(model)
    #expect(await !restored.installed(model))
}
@Test func localDownloadChecksumFailureNeverInstalls() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let model = try localFixture(); let store = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    await #expect(throws: (any Error).self) { try await store.download(model, wifi: { true }, transport: RangeServer(bytes: Data("model".utf8), corrupted: true)) }
    #expect(await !store.installed(model))
    await #expect(throws: (any Error).self) { try await store.authorize(model) }
}
@Test func localDownloadWifiAndStorageStopBeforeNetwork() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let model = try localFixture(); let store = try ModelStore(root: root)
    let host = RangeServer(bytes: Data("model".utf8))
    await #expect(throws: (any Error).self) { try await store.download(model, wifi: { false }, transport: host) }
    #expect(await host.requests.isEmpty)
    let full = try ModelStore(root: root, available: { _ in 0 })
    await #expect(throws: (any Error).self) { try await full.download(model, wifi: { true }, transport: host) }
    #expect(await host.requests.isEmpty)
    try await store.download(model, policy: DownloadPolicy(allowMobileData: true), wifi: { false }, transport: host)
    #expect(await store.installed(model))
}
@Test func localDownloadCancellationRetainsRangeForResume() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let bytes = Data(repeating: 19, count: 4_194_304 + 8)
    let model = try localFixture(bytes: bytes), store = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    let host = RangeServer(bytes: bytes, slowAfter: 1)
    let work = Task {
        do { try await store.download(model, wifi: { true }, transport: host) }
        catch { await host.finishEvents(); throw error }
        await host.finishEvents()
    }
    for await count in host.events { if count == 2 { break } }
    work.cancel()
    await #expect(throws: CancellationError.self) { try await work.value }
    #expect(await !store.installed(model))
    let next = RangeServer(bytes: bytes)
    try await store.download(model, wifi: { true }, transport: next)
    #expect(await next.requests.first?.value(forHTTPHeaderField: "Range") == "bytes=4194304-4194311")
}
@Test func localLicenceGatePersistsWithdrawalAndTermsChanges() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let model = try localFixture(gated: true), store = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    let host = RangeServer(bytes: Data("model".utf8))
    await #expect(throws: (any Error).self) { try await store.download(model, wifi: { true }, transport: host) }
    #expect(await host.requests.isEmpty)
    try await store.accept(model, fingerprint: model.licence.terms_fingerprint, appVersion: "test-version", accepted: true)
    try await store.download(model, wifi: { true }, transport: host)
    _ = try await store.authorize(model)
    let restored = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    #expect(await restored.allowed(model))
    #expect(await restored.acceptance(model)?.appVersion == "test-version")
    let changed = try localFixture(gated: true, fingerprint: String(repeating: "c", count: 64))
    #expect(await !restored.allowed(changed))
    try await restored.accept(model, fingerprint: model.licence.terms_fingerprint, appVersion: "test-version", accepted: false)
    await #expect(throws: (any Error).self) { try await restored.authorize(model) }
    let engine = NativeLocalEngine(store: restored)
    await #expect(throws: (any Error).self) { try await engine.synthesize(model: model, text: "Speech") }
}
@Test func localLoadVerifiesBytesAndProtectsActiveLease() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let model = try localFixture(), store = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    try await store.download(model, wifi: { true }, transport: RangeServer(bytes: Data("model".utf8)))
    let path = try await store.acquire(model)
    await #expect(throws: (any Error).self) { try await store.delete(model) }
    await store.release(model)
    try Data("other".utf8).write(to: path.appendingPathComponent("model.bin"))
    await #expect(throws: (any Error).self) { try await store.authorize(model) }
    try await store.delete(model)
}
@Test func localLowRamNeverDownloads() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let model = try localFixture(), store = try ModelStore(root: root, ram: 1)
    let host = RangeServer(bytes: Data("model".utf8))
    await #expect(throws: (any Error).self) { try await store.download(model, wifi: { true }, transport: host) }
    #expect(await host.requests.isEmpty)
}
@Test func localTaskRoutesWithoutAComputer() {
    #expect(LocalRouting.route(preference: nil, installed: true, paired: false) == .phone)
    #expect(LocalRouting.route(preference: nil, installed: false, paired: false) == .download)
    #expect(LocalRouting.route(preference: nil, installed: false, paired: true) == .computer)
    #expect(LocalRouting.route(preference: nil, installed: true, paired: true) == .phone)
    #expect(LocalRouting.route(preference: .phone, installed: false, paired: true) == .download)
    #expect(LocalRouting.route(preference: .computer, installed: true, paired: false) == .phone)
    #expect(LocalRouting.route(preference: .computer, installed: false, paired: false) == .download)
}
@Test func localRedirectsStayWithinModelDeliveryOrigins() {
    for url in ["https://huggingface.co/resolve", "https://cdn-lfs.hf.co/model", "https://cas-bridge.xethub.hf.co/model", "https://hf-mirror.com/model"] { #expect(ModelRedirectDelegate.allowed(URL(string: url)!)) }
    for url in ["http://huggingface.co/model", "https://huggingface.co.evil.test/model", "https://example.org/model", "https://user:password@huggingface.co/model"] { #expect(!ModelRedirectDelegate.allowed(URL(string: url)!)) }
}
@Test func localSyntheticAudioHasValidRiffSizeAndMark() throws {
    let bytes = try LocalAudio(samples: [0, 0.5, -0.5], sampleRate: 24000).markSynthetic()
    let size = bytes[4..<8].enumerated().reduce(UInt32(0)) { $0 | UInt32($1.element) << (8 * $1.offset) }
    #expect(Int(size) == bytes.count - 8)
    #expect(bytes.range(of: Data("VoiceStudio synthetic audio".utf8)) != nil)
    #expect(try PCMChunk(pcm16: Data([0,128,255,127])).samples == [-1, Float(32767) / 32768])
}
@Test func localCloneAndTranslateValidateInputsAndRuntimeBoundary() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let store = try ModelStore(root: root, available: { _ in 100_000_000_000 }), engine = NativeLocalEngine(store: store)
    let clone = try localFixture(capability: "clone"), translate = try localFixture(capability: "translate")
    #expect(!NativeLocalEngine.runtimeAvailable(.omni, library: "/does-not-exist"))
    #expect(!NativeLocalEngine.runtimeAvailable(.llama, library: "/does-not-exist"))
    await #expect(throws: (any Error).self) { try await engine.clone(model: clone, text: "Hello", reference: PCMChunk(samples: [0], sampleRate: 16000), referenceText: "Reference") }
    try await store.download(translate, wifi: { true }, transport: RangeServer(bytes: Data("model".utf8)))
    await #expect(throws: (any Error).self) { try await engine.translate(model: translate, text: "Hello", sourceLanguage: "en", targetLanguage: "fr") }
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["VOICESTUDIO_REAL_INFERENCE"] == "1"))
func realSherpaSynthesizesAndTranscribesOffline() async throws {
    let catalogue = try ModelCatalogue.decode(Data(contentsOf: repository.appendingPathComponent("mobile/contract/models.json")))
    let tts = try #require(catalogue.models.first { $0.id == "kitten-mini-en-fp16" })
    let asr = try #require(catalogue.models.first { $0.id == "whisper-tiny-int8" })
    let streaming = try #require(catalogue.models.first { $0.id == "zipformer-en-20m-int8" })
    let library = try #require(ProcessInfo.processInfo.environment["SHERPA_ONNX_LIBRARY"])
    #expect(NativeLocalEngine.runtimeAvailable(.sherpa, library: library))
    let store = try ModelStore(root: repository.appendingPathComponent("mobile/ios/.cache/inference-models"))
    // Isolated test fixtures. No app acceptance is granted and no network is used here.
    for model in [tts, asr] { try await store.accept(model, fingerprint: model.licence.terms_fingerprint, appVersion: "inference-test", accepted: true) }
    let engine = NativeLocalEngine(store: store, libraries: [.sherpa: library])
    let audio = try await engine.synthesize(model: tts, text: "The quick brown fox jumps over the lazy dog.")
    #expect(audio.samples.count > audio.sampleRate)
    #expect(audio.samples.contains { abs($0) > 0.01 })
    let pcm = PCMChunk(samples: audio.samples, sampleRate: audio.sampleRate)
    let transcript = try await engine.transcribe(model: asr, audio: pcm)
    print("Whisper real inference:", transcript)
    #expect(transcript.lowercased().contains("fox"))
    let (chunks, feed) = AsyncThrowingStream<PCMChunk, any Error>.makeStream()
    let updates = try await engine.streamTranscribe(model: streaming, chunks: chunks)
    for start in stride(from: 0, to: audio.samples.count, by: 4800) { feed.yield(PCMChunk(samples: Array(audio.samples[start..<min(start + 4800, audio.samples.count)]), sampleRate: audio.sampleRate)) }
    feed.finish()
    var last: TranscriptUpdate?
    for try await update in updates { last = update }
    print("Zipformer real inference:", last?.text ?? "")
    #expect(last?.finished == true)
    #expect(last?.text.lowercased().contains("dog") == true)
    let (events, signal) = AsyncStream<Void>.makeStream(bufferingPolicy: .bufferingNewest(1))
    let generation = Task {
        defer { signal.finish() }
        return try await engine.synthesize(model: tts, text: String(repeating: "The quick brown fox jumps over the lazy dog. ", count: 20), progress: { value in
            if value.stage == .running && value.fraction > 0 { signal.yield(()) }
        })
    }
    var observedProgress = false
    for await _ in events { observedProgress = true; generation.cancel(); break }
    #expect(observedProgress)
    await #expect(throws: CancellationError.self) { try await generation.value }
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["VOICESTUDIO_REAL_NATIVE"] == "1"))
func realNativePinnedRuntimesAreLoadable() throws {
    for (runtime, key) in [(ModelRuntime.omni, "OMNIVOICE_LIBRARY"), (.llama, "LLAMA_LIBRARY")] {
        let library = try #require(ProcessInfo.processInfo.environment[key])
        #expect(NativeLocalEngine.runtimeAvailable(runtime, library: library))
    }
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["VOICESTUDIO_REAL_AUX"] == "1"))
func realAuxiliaryCloneAndTranslation() async throws {
    let models = try ModelCatalogue.decode(Data(contentsOf: repository.appendingPathComponent("mobile/contract/models.json"))).models
    let tts = try #require(models.first { $0.id == "kitten-mini-en-fp16" })
    let clone = try #require(models.first { $0.capability == .clone })
    let translate = try #require(models.first { $0.capability == .translate })
    let env = ProcessInfo.processInfo.environment
    let store = try ModelStore(root: repository.appendingPathComponent("mobile/ios/.cache/inference-models"))
    for m in [tts, clone] { try await store.accept(m, fingerprint: m.licence.terms_fingerprint, appVersion: "inference-test", accepted: true) }
    let engine = NativeLocalEngine(store: store, libraries: [.sherpa: try #require(env["SHERPA_ONNX_LIBRARY"]), .omni: try #require(env["OMNIVOICE_LIBRARY"]), .llama: try #require(env["LLAMA_LIBRARY"])])
    let referenceText = "The quick brown fox jumps over the lazy dog."
    let reference = try await engine.synthesize(model: tts, text: referenceText)
    let audio = try await engine.clone(model: clone, text: "Hello world.", reference: PCMChunk(samples: reference.samples, sampleRate: reference.sampleRate), referenceText: referenceText)
    #expect(audio.sampleRate == 24000)
    #expect(audio.samples.count > 1000)
    #expect(audio.samples.contains { abs($0) > 0.001 })
    let translated = try await engine.translate(model: translate, text: "Hello, how are you?", sourceLanguage: "English", targetLanguage: "French")
    print("Real translation:", translated)
    #expect(translated.lowercased().contains("bonjour"))
}

#if os(macOS)
private final class LoopbackRangeHost {
    let process = Process()
    let port: Int
    init() throws {
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-u", "-c", #"""
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    calls = 0
    def log_message(self, *args): pass
    def do_GET(self):
        Handler.calls += 1
        if Handler.calls in (2, 3):
            self.send_response(503); self.send_header('Content-Length', '0'); self.end_headers(); return
        start, end = map(int, self.headers['Range'][6:].split('-'))
        self.send_response(206)
        self.send_header('Content-Range', f'bytes {start}-{end}/4194313')
        self.send_header('Content-Length', str(end-start+1))
        self.end_headers(); self.wfile.write(bytes([17])*(end-start+1))
server = HTTPServer(('127.0.0.1', 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
"""#]
        process.standardOutput = output
        try process.run()
        var line = Data()
        while let byte = try output.fileHandleForReading.read(upToCount: 1), !byte.isEmpty { if byte == Data([10]) { break }; line.append(byte) }
        guard let port = Int(String(decoding: line, as: UTF8.self)) else { process.terminate(); throw ClientError("mobile.local.download_error") }
        self.port = port
    }
    deinit { if process.isRunning { process.terminate(); process.waitUntilExit() } }
}
private struct LoopbackRangeTransport: HTTPTransport {
    let port: Int
    let transport = URLSessionTransport()
    func send(_ request: URLRequest) async throws -> HTTPReply { throw ClientError("mobile.local.download_error") }
    func download(_ request: URLRequest) async throws -> DownloadReply {
        var local = request
        local.url = URL(string: "http://127.0.0.1:\(port)/model")!
        return try await transport.download(local)
    }
}
@Test func localDownloadResumesUsingRealURLSessionAndLoopbackServer() async throws {
    let root = try localDirectory(); defer { try? FileManager.default.removeItem(at: root) }
    let server = try LoopbackRangeHost()
    let transport = LoopbackRangeTransport(port: server.port)
    let bytes = Data(repeating: 17, count: 4_194_313)
    let model = try localFixture(bytes: bytes)
    let first = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    await #expect(throws: (any Error).self) { try await first.download(model, wifi: { true }, transport: transport) }
    #expect(await !first.installed(model))
    let restored = try ModelStore(root: root, available: { _ in 100_000_000_000 })
    try await restored.download(model, wifi: { true }, transport: transport)
    let path = try await restored.authorize(model)
    #expect(try Data(contentsOf: path.appendingPathComponent("model.bin")) == bytes)
}
#endif

@Test func modelProductNameIsRequiredAndSurvivesLanguageSelection() throws {
    let fixture = try localFixture()
    #expect(fixture.name == "Fixture")
    #expect(try fixture.selectingLanguage("en").name == fixture.name)
    let encoded = try JSONEncoder().encode(fixture)
    var object = try JSONSerialization.jsonObject(with: encoded) as! [String: Any]
    for invalid: String? in [nil, "", " \n "] {
        object["name"] = invalid
        let data = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "models": [object]])
        #expect(throws: (any Error).self) { try ModelCatalogue.decode(data) }
    }
}

@Test func downloadBatchRequiresEveryReceiptAndSkipsInstalledModels() throws {
    let first = try localFixture(gated: true)
    var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(first)) as! [String: Any]
    object["id"] = "second"; object["name"] = "Second"
    let second = try ModelCatalogue.decode(JSONSerialization.data(withJSONObject: ["schema_version": 1, "models": [object]])).models[0]
    var queue = ModelDownloadQueue([first, second, first])
    // Repeated calls cannot skip an unaccepted model (including persistence failure).
    for _ in 0..<2 {
        guard case .licence(let item) = queue.next(installed: [], accepted: []) else { Issue.record("Missing first licence gate"); return }
        #expect(item.id == first.id)
    }
    guard case .download(let item) = queue.next(installed: [], accepted: [first.id]) else { Issue.record("Missing first download"); return }
    #expect(item.id == first.id)
    guard case .licence(let item) = queue.next(installed: [], accepted: [first.id]) else { Issue.record("Missing second licence gate"); return }
    #expect(item.id == second.id)
    // Accepting an installed model authorizes use without downloading it again.
    #expect(queue.next(installed: [second.id], accepted: [first.id, second.id]) == nil)
    var permissive = ModelDownloadQueue([try localFixture()])
    guard case .download = permissive.next(installed: [], accepted: []) else { Issue.record("Permissive model was gated"); return }
    #expect(permissive.next(installed: [], accepted: []) == nil)
}
