import SwiftUI
import VoiceStudioKit

struct DictateView: View {
    @Environment(AppModel.self) private var model
    @State private var preference: TaskLocation?
    private var phoneModel: PhoneModel? { model.phone.preferred(.stream) }
    private var localReady: Bool { phoneModel.map(model.phone.ready) ?? false }
    private var route: TaskRoute { LocalRouting.route(preference: preference, installed: localReady, paired: model.connection.client != nil) }
    @State private var text = ""
    @State private var transcript = DictationTranscript()
    @State private var previousText = ""
    @State private var checking = true
    @State private var ready = false
    @State private var reason = ""
    @State private var listening = false
    @State private var finalizing = false
    @State private var capturing: Task<Void, Never>?
    @State private var receiving: Task<Void, Never>?
    @State private var audio = DictationAudio()
    @State private var stream = DictationStream()
    var body: some View {
        Page {
            RunOnPicker(preference: $preference, task: "dictate", installed: localReady).disabled(listening || finalizing)
            if route == .download { LocalDownloadPrompt(item: phoneModel) }
            if route == .connect { NavigationLink(model.t("mobile.settings.connection")) { ConnectView() } }
            if checking { ProgressView(model.t("common.loading")) }
            else if !ready { Text(model.t("mobile.dictate.not_ready", ["reason": reason])) }
            Button(model.t(listening ? "common.stop" : "mobile.dictate.tap_to_start"), systemImage: listening ? "stop.fill" : "mic.fill") {
                if listening { stop() } else { start() }
            }.buttonStyle(VSButtonStyle(kind: .primary)).disabled(!ready || finalizing).accessibilityHint(model.t("mobile.dictate.hold_to_talk")).accessibilityIdentifier("dictate.record")
            // The separate hold surface supports release-to-finish without competing with tap semantics.
            Text(model.t("mobile.dictate.hold_to_talk")).frame(minHeight: 44).frame(maxWidth: .infinity)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 0.2, pressing: { pressed in
                    if pressed && ready && !listening { start() }
                    else if !pressed && listening { stop() }
                }, perform: {})
                .accessibilityAddTraits(.isButton).accessibilityAction { if listening { stop() } else { start() } }
            if listening { Text(model.t("mobile.dictate.listening")) }
            Text(text).frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled).accessibilityLabel(model.t("mobile.ios.transcript"))
            Button(model.t("mobile.dictate.copy"), systemImage: "doc.on.doc") { UIPasteboard.general.string = text }.disabled(text.isEmpty)
            ShareLink(item: text) { Label(model.t("mobile.speak.share"), systemImage: "square.and.arrow.up") }.disabled(text.isEmpty)
        }.navigationTitle(model.t("mobile.tabs.dictate"))
        .task { preference = model.phone.preference("dictate"); await model.phone.refresh(); await readiness() }
        .onChange(of: preference) { _, _ in Task { await readiness() } }
        .onChange(of: route) { _, _ in Task { await readiness() } }
        .refreshable { await readiness() }
        .onDisappear { capturing?.cancel(); receiving?.cancel(); audio.stop(); listening = false; finalizing = false; Task { await stream.close() } }
    }
    private func readiness() async {
        let scope = model.hostState.scopeID
        let selectedRoute = route
        checking = true; defer { checking = false }
        if route != .computer {
            ready = route == .phone; reason = ready ? "" : model.t("mobile.local.model_required")
            return
        }
        do {
            let status = try await model.api().readiness()
            guard scope == model.hostState.scopeID, selectedRoute == route else { return }
            ready = status.ready; reason = status.reason(l10n: model.l10n)
        }
        catch is CancellationError {}
        catch let error as ClientError { guard scope == model.hostState.scopeID, selectedRoute == route else { return }; ready = false; reason = model.t(error.key, error.params); await model.connection.handle(error) }
        catch { guard scope == model.hostState.scopeID, selectedRoute == route else { return }; ready = false; reason = model.t("mobile.errors.offline") }
    }
    private func start() {
        guard ready, !listening, !finalizing else { return }
        let scope = model.hostState.scopeID
        listening = true; previousText = text; transcript = DictationTranscript()
        if route == .phone { startLocal(); return }
        capturing = Task {
            // Per session: a finished `receiving` from an earlier session must not count.
            var receiverCreated = false
            do {
                let api = try model.api()
                let messages = try await stream.start(api: api)
                // A stop during startup never creates `receiving`, so nothing else clears `finalizing`.
                guard scope == model.hostState.scopeID, listening, !Task.isCancelled else { finalizing = false; await stream.close(); return }
                receiving = Task {
                    do {
                        for try await message in messages {
                            try Task.checkCancellation()
                            guard scope == model.hostState.scopeID else { throw CancellationError() }
                            transcript.receive(message)
                            text = [previousText, transcript.text].filter { !$0.isEmpty }.joined(separator: "\n")
                            if transcript.finished { audio.stop(); listening = false; finalizing = false }
                        }
                    } catch { audio.stop(); listening = false; finalizing = false; if !Task.isCancelled && scope == model.hostState.scopeID { model.error = error as? ClientError ?? ClientError("mobile.errors.dictation") } }
                }
                receiverCreated = true
                let chunks = try await audio.start()
                guard scope == model.hostState.scopeID, listening, !Task.isCancelled else { audio.stop(); try? await stream.finish(); return }
                for try await chunk in chunks { try Task.checkCancellation(); try await stream.send(chunk) }
                try await stream.finish()
            } catch is CancellationError { if !receiverCreated { finalizing = false } } catch {
                audio.stop(); listening = false; finalizing = false; await stream.close()
                if scope == model.hostState.scopeID { model.error = error as? ClientError ?? ClientError("mobile.errors.audio") }
            }
        }
    }
    private func startLocal() {
        capturing = Task {
            defer { audio.stop(); listening = false; finalizing = false }
            do {
                guard let phoneModel, let engine = model.phone.engine else { throw ClientError("mobile.local.model_required") }
                let bytes = try await audio.start()
                guard listening, !Task.isCancelled else { audio.stop(); return }
                let (chunks, continuation) = AsyncThrowingStream<PCMChunk, any Error>.makeStream(bufferingPolicy: .bufferingOldest(64))
                let updates = try await engine.streamTranscribe(model: phoneModel, chunks: chunks, progress: { _ in })
                receiving = Task {
                    do {
                        for try await update in updates {
                            try Task.checkCancellation()
                            text = [previousText, update.text].filter { !$0.isEmpty }.joined(separator: "\n")
                        }
                    } catch is CancellationError {} catch { model.error = error as? ClientError ?? ClientError("mobile.local.inference_error") }
                    audio.stop()
                }
                do {
                    for try await chunk in bytes {
                        try Task.checkCancellation()
                        if case .dropped = continuation.yield(try PCMChunk(pcm16: chunk)) { throw ClientError("mobile.errors.audio") }
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: error); throw error }
                await receiving?.value
            } catch is CancellationError {} catch { model.error = error as? ClientError ?? ClientError("mobile.errors.audio") }
        }
    }
    private func stop() { finalizing = true; audio.stop(); listening = false }
}
