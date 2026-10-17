import SwiftUI
import VoiceStudioKit

struct VoicePicker: View {
    @Environment(AppModel.self) private var model
    @Binding var selection: String
    var dubbing = false
    var body: some View {
        ChoicePicker(label: model.t("mobile.speak.voice"), selection: $selection, options:
            (dubbing ? [SelectionOption(id: DubVoiceChoice.unselected, title: model.t("mobile.dub.choose_voice"), enabled: false)] : []) +
            [SelectionOption(id: "", title: model.t(DubVoiceChoice.defaultLabelKey))] +
            model.profiles.map { SelectionOption(id: $0.id, title: $0.name, subtitle: model.languages.language($0.language)?.name) })
    }
}
struct SpeakView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var preference: TaskLocation?
    @State private var phoneModelID = ""
    @State private var speakerID = "0"
    @State private var localProgress: EngineProgress?
    @State private var generation: Task<Void, Never>?
    private var phoneModel: PhoneModel? { model.phone.candidates(.tts).first { $0.id == phoneModelID } ?? model.phone.preferred(.tts) }
    private var localReady: Bool { phoneModel.map(model.phone.ready) ?? false }
    private var route: TaskRoute { LocalRouting.route(preference: preference, installed: localReady, paired: model.connection.client != nil) }
    @State private var text = ""
    @State private var selection = SpeechSelection()
    @State private var player = AudioPlayer()
    @State private var generating = false
    @State private var deleting: HistoryItem?
    @State private var hostScope: UUID?
    private var engines: [SelectionOption] {
        (model.inventory?.tts.backends ?? []).map {
            SelectionOption(id: $0.id, title: $0.display_name,
                            subtitle: $0.explanation(for: selection.profile(in: model.profiles), l10n: model.l10n),
                            enabled: $0.selectable(for: selection.profile(in: model.profiles)))
        }
    }
    var body: some View {
        Page {
            RunOnPicker(preference: $preference, task: "speak", installed: localReady).disabled(generating)
            if route == .download { LocalDownloadPrompt(item: phoneModel) }
            if route == .connect { NavigationLink(model.t("mobile.settings.connection")) { ConnectView() } }
            TextEditor(text: $text).frame(minHeight: VSTokens.textEditor.lineHeight * 6)
                .scrollContentBackground(.hidden).padding(Theme.compactInset)
                .background(theme.color("input"), in: RoundedRectangle(cornerRadius: VSTokens.radiusControl))
                .accessibilityLabel(model.t("mobile.speak.placeholder")).accessibilityIdentifier("speak.text")
            if route != .computer {
                Card {
                    ChoicePicker(label: model.t("mobile.local.models"), selection: Binding(get: { phoneModel?.id ?? "" }, set: { phoneModelID = $0; speakerID = "0" }), options: model.phone.candidates(.tts).map { SelectionOption(id: $0.id, title: $0.id, enabled: $0.fits()) })
                    ChoicePicker(label: model.t("mobile.speak.voice"), selection: $speakerID, options: (0..<Int(phoneModel?.config["num_speakers"]?.number ?? 1)).map { SelectionOption(id: String($0), title: model.t("mobile.local.preset_voice", ["number": String($0 + 1)])) })
                }.disabled(generating)
            } else {
            Card {
                VoicePicker(selection: Binding(get: { selection.profileID }, set: {
                    selection.chooseProfile($0, profiles: model.profiles, inventory: model.inventory, catalog: model.languages)
                }))
                Divider().overlay(theme.color("border"))
                ChoicePicker(label: model.t("mobile.speak.engine"), selection: $selection.engineID, options: engines).accessibilityIdentifier("speak.engine")
                if let explanation = engines.first(where: { $0.id == selection.engineID })?.subtitle {
                    Text(explanation).foregroundStyle(theme.color("textMuted"))
                }
                Divider().overlay(theme.color("border"))
                ChoicePicker(label: model.t("mobile.speak.language"), selection: $selection.language,
                             options: model.languages.languages.map { SelectionOption(id: $0.value, title: $0.name) }).accessibilityIdentifier("speak.language")
            }
            }
            Button(model.t(generating ? "mobile.speak.generating" : "mobile.speak.generate")) {
                generation = Task {
                    generating = true; defer { generating = false; localProgress = nil }
                    await model.perform {
                        if route == .phone {
                            guard let phoneModel, let engine = model.phone.engine else { throw ClientError("mobile.local.model_required") }
                            let audio = try await engine.synthesize(model: phoneModel, text: text, speaker: Int(speakerID) ?? 0, speed: 1, progress: { value in await MainActor.run { localProgress = value } })
                            try await player.load(audio.markSynthetic(), extension: "wav")
                            return
                        }
                        let result = try await model.hostState.generate(api: model.api(), text: text, profile: selection.profileID, engine: selection.engineID, language: selection.language)
                        try await player.load(result.audio, extension: "wav")
                        model.history = try await model.api().history()
                    }
                }
            }.buttonStyle(VSButtonStyle(kind: .primary))
                .disabled(model.busy || generating || (route != .phone && route != .computer) || (route == .computer && !selection.canGenerate(in: model.inventory, profiles: model.profiles)) || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("speak.generate")
            if generating {
                if let value = localProgress { ProgressView(value: value.fraction).accessibilityLabel(model.t("mobile.ios.progress")) }
                Button(model.t("common.cancel")) { generation?.cancel() }
            }
            if player.file != nil || player.playing { AudioPlayerView(player: player) }
            Text(model.t("mobile.speak.recent")).font(.custom("InterVariable", size: Theme.controlTypeSize, relativeTo: .headline))
            if model.history.isEmpty && !model.loading { Text(model.t("mobile.speak.empty_recent")).foregroundStyle(theme.color("textMuted")) }
            else {
                Card {
                    ForEach(model.history) { item in
                        HStack(spacing: VSTokens.spacingGap) {
                            Text(item.text).frame(maxWidth: .infinity, alignment: .leading)
                            Button(model.t("common.play"), systemImage: "play.fill") { Task { await model.perform { let api = try model.api(); try await player.stream(request: api.historyAudioRequest(item.id), api: api) } } }
                                .labelStyle(.iconOnly).buttonStyle(VSButtonStyle(kind: .tertiary))
                            Menu {
                                Button(model.t(item.starred ? "mobile.speak.unstar" : "mobile.speak.star"), systemImage: item.starred ? "star.fill" : "star") { Task { await model.perform { try await model.api().star(item); model.history = try await model.api().history() } } }
                                Button(model.t("common.delete"), systemImage: "trash", role: .destructive) { deleting = item }
                            } label: { Label(model.t("mobile.ios.more_actions"), systemImage: "ellipsis") }
                                .labelStyle(.iconOnly).buttonStyle(VSButtonStyle(kind: .tertiary)).frame(minWidth: 44, minHeight: 44)
                        }
                        if item.id != model.history.last?.id { Divider().overlay(theme.color("border")) }
                    }
                }
            }
        }.navigationTitle(model.t("mobile.tabs.speak")).navigationBarTitleDisplayMode(.large)
        .onChange(of: model.inventory?.tts.active, initial: true) { _, _ in selection.reconcile(inventory: model.inventory, profiles: model.profiles) }
        .onChange(of: model.profiles.map(\.id)) { _, _ in selection.reconcile(inventory: model.inventory, profiles: model.profiles) }
        .refreshable { if model.connection.client != nil { await model.perform { try await model.refresh() } }; await model.phone.refresh(); selection.reconcile(inventory: model.inventory, profiles: model.profiles) }
        .sheet(item: $deleting) { item in
            DeleteConfirmation(title: model.t("mobile.ios.delete_generation")) {
                Task { await model.perform { try await model.api().deleteHistory(item.id); model.history = try await model.api().history() } }
            }
        }
        .onAppear { hostScope = model.hostState.scopeID; preference = model.phone.preference("speak") }
        .task { await model.phone.refresh() }
        .onDisappear { generation?.cancel(); if hostScope != model.hostState.scopeID { player.clear() } else { player.pause() } }
    }
}
