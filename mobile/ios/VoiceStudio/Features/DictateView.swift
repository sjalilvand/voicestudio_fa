import SwiftUI
import VoiceStudioKit

struct DictateView: View {
    @Environment(AppModel.self) private var model
    @State private var text = ""
    @State private var partial = ""
    @State private var checking = true
    @State private var ready = false
    @State private var reason = ""
    @State private var listening = false
    @State private var capturing: Task<Void, Never>?
    @State private var receiving: Task<Void, Never>?
    @State private var audio = DictationAudio()
    @State private var stream = DictationStream()
    var body: some View {
        Page {
            if checking { ProgressView(model.t("common.loading")) }
            else if !ready { Text(model.t("mobile.dictate.not_ready", ["reason": reason])) }
            Button(model.t(listening ? "common.stop" : "mobile.dictate.tap_to_start"), systemImage: listening ? "stop.fill" : "mic.fill") {
                if listening { stop() } else { start() }
            }.buttonStyle(VSButtonStyle(kind: .primary)).disabled(!ready).accessibilityHint(model.t("mobile.dictate.hold_to_talk"))
            // The separate hold surface supports release-to-finish without competing with tap semantics.
            Text(model.t("mobile.dictate.hold_to_talk")).frame(minHeight: 44).frame(maxWidth: .infinity)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 0.2, pressing: { pressed in
                    if pressed && ready && !listening { start() }
                    else if !pressed && listening { stop() }
                }, perform: {})
                .accessibilityAddTraits(.isButton).accessibilityAction { if listening { stop() } else { start() } }
            if listening { Text(model.t("mobile.dictate.listening")) }
            Text(text + partial).frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled).accessibilityLabel(model.t("mobile.ios.transcript"))
            Button(model.t("mobile.dictate.copy"), systemImage: "doc.on.doc") { UIPasteboard.general.string = text + partial }.disabled(text.isEmpty && partial.isEmpty)
            ShareLink(item: text + partial) { Label(model.t("mobile.speak.share"), systemImage: "square.and.arrow.up") }.disabled(text.isEmpty && partial.isEmpty)
        }.navigationTitle(model.t("mobile.tabs.dictate"))
        .task { await readiness() }
        .refreshable { await readiness() }
        .onDisappear { capturing?.cancel(); receiving?.cancel(); audio.stop(); listening = false; Task { await stream.close() } }
    }
    private func readiness() async {
        checking = true; defer { checking = false }
        do { let status = try await model.api().readiness(); ready = status.ready; reason = status.reason(l10n: model.l10n) }
        catch is CancellationError {}
        catch let error as ClientError { ready = false; reason = model.t(error.key, error.params); await model.connection.handle(error) }
        catch { ready = false; reason = model.t("mobile.errors.offline") }
    }
    private func start() {
        guard !listening else { return }; listening = true; partial = ""
        capturing = Task {
            do {
                let api = try model.api()
                let messages = try await stream.start(api: api)
                guard listening, !Task.isCancelled else { await stream.close(); return }
                receiving = Task {
                    do {
                        for try await message in messages {
                            if message.type == "final" { text += (message.text ?? "") + "\n"; partial = ""; audio.stop(); listening = false }
                            else if message.type == "partial" { partial = message.text ?? "" }
                        }
                    } catch { audio.stop(); listening = false; if !Task.isCancelled { model.error = error as? ClientError ?? ClientError("mobile.errors.dictation") } }
                }
                let chunks = try await audio.start()
                guard listening, !Task.isCancelled else { audio.stop(); try? await stream.finish(); return }
                for try await chunk in chunks { try Task.checkCancellation(); try await stream.send(chunk) }
                try await stream.finish()
            } catch is CancellationError {} catch { audio.stop(); listening = false; await stream.close(); model.error = error as? ClientError ?? ClientError("mobile.errors.audio") }
        }
    }
    private func stop() { audio.stop(); listening = false }
}
