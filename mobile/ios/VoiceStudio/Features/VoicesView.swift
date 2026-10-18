import SwiftUI
import VoiceStudioKit
import UniformTypeIdentifiers

private struct VoiceEntry: Identifiable {
    let id: String
    let name: String
    let phone: PhoneVoice?
    init(_ voice: PhoneVoice) { id = "phone:"+voice.id.uuidString; name = voice.name; phone = voice }
    init(_ voice: Profile) { id = voice.id; name = voice.name; phone = nil }
}
struct VoicesView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var preference: TaskLocation?
    @State private var query = ""
    @State private var creating = false
    @State private var player = AudioPlayer()
    @State private var renamed: VoiceEntry?
    @State private var deleting: VoiceEntry?
    @State private var name = ""
    @State private var hostScope: UUID?
    private var entries: [VoiceEntry] { model.phone.voices.map(VoiceEntry.init) + model.profiles.map(VoiceEntry.init) }
    private var filtered: [VoiceEntry] { entries.filter { query.isEmpty || $0.name.localizedCaseInsensitiveContains(query) } }
    private var localReady: Bool { model.phone.selectedModel("clone",.asr).map(model.phone.ready) ?? false }
    private var route: TaskRoute { LocalRouting.route(preference: preference, installed: localReady, paired: model.connection.client != nil) }
    var body: some View {
        Page {
            RunOnPicker(preference: $preference, task: "clone", installed: localReady)
            if route == .download { LocalDownloadPrompt(items: model.phone.selectedModel("clone",.asr).map { [$0] } ?? [], feature: "mobile.tabs.voices") }
            SearchField(prompt: model.t("mobile.voices.search"), text: $query)
            if entries.isEmpty && !model.loading {
                EmptyState(key: "mobile.simple.empty_voices", icon: "person")
                Button(model.t("mobile.voices.new_clone"), systemImage: "plus") { creating = true }.buttonStyle(VSButtonStyle(kind: .primary))
            } else {
                Card {
                    if filtered.isEmpty { SearchEmptyState(query: query) }
                    ForEach(filtered) { entry in
                        HStack(spacing: VSTokens.spacingGap) {
                            Text(String(entry.name.prefix(1)).uppercased()).frame(width: 44,height: 44).background(theme.color("input"),in: Circle()).accessibilityHidden(true)
                            VStack(alignment: .leading,spacing: 4) {
                                Text(entry.name).lineLimit(1)
                                Text(model.t(entry.phone == nil ? "mobile.simple.computer" : "mobile.simple.phone")).font(.caption).foregroundStyle(theme.color("textMuted"))
                            }.frame(maxWidth: .infinity,alignment: .leading)
                            Button(model.t("common.play"), systemImage: "play.fill") {
                                Task { await model.perform(onPhone: entry.phone != nil) {
                                    let bytes: Data
                                    if let voice = entry.phone, let store = model.phone.voiceStore { bytes = try Data(contentsOf: await store.preview(voice)) }
                                    else { bytes = try await model.api().profileAudio(entry.id) }
                                    try await player.load(bytes,extension: "wav"); player.play()
                                } }
                            }.labelStyle(.iconOnly).buttonStyle(VSButtonStyle(kind: .tertiary))
                            Menu {
                                Button(model.t("mobile.voices.rename"),systemImage: "pencil") { name = entry.name; renamed = entry }
                                Button(model.t("common.delete"),systemImage: "trash",role: .destructive) { deleting = entry }
                            } label: { Label(model.t("mobile.ios.more_actions"),systemImage: "ellipsis") }
                                .labelStyle(.iconOnly).buttonStyle(VSButtonStyle(kind: .tertiary)).frame(minWidth: 44,minHeight: 44).accessibilityIdentifier("voices.actions."+entry.id)
                        }
                        if entry.id != filtered.last?.id { Divider().overlay(theme.color("border")) }
                    }
                }
            }
            if player.file != nil { AudioPlayerView(player: player) }
        }.navigationTitle(model.t("mobile.tabs.voices")).navigationBarTitleDisplayMode(.large)
        .toolbar { Button(model.t("mobile.voices.new_clone"),systemImage: "plus") { creating = true }.accessibilityIdentifier("voices.create") }
        .task { preference = model.phone.preference("clone"); await model.phone.refresh() }
        .refreshable { await model.phone.refresh(); if model.connection.client != nil { await model.perform { model.profiles = try await model.api().profiles() } } }
        .sheet(isPresented: $creating) { NavigationStack { CloneView(preference: preference) }.environment(model).presentationBackground(theme.color("surfaceOverlay")) }
        .sheet(item: $renamed) { entry in
            NavigationStack {
                Page(backgroundRole: "surfaceOverlay") {
                    TextField(model.t("mobile.voices.name_label"),text: $name).accessibilityIdentifier("voices.rename.name")
                    Button(model.t("common.save"),systemImage: "checkmark") { Task { await model.perform(onPhone: entry.phone != nil) {
                        if let voice = entry.phone { try await model.phone.voiceStore?.rename(voice,name: name); await model.phone.refresh() }
                        else { try await model.api().rename(entry.id,name: name); model.profiles = try await model.api().profiles() }
                        renamed = nil
                    } } }.buttonStyle(VSButtonStyle(kind: .primary)).disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.busy)
                }.navigationTitle(model.t("mobile.voices.rename"))
                    .toolbar { Button(model.t("common.cancel")) { renamed = nil } }
            }.presentationBackground(theme.color("surfaceOverlay"))
        }
        .sheet(item: $deleting) { entry in
            DeleteConfirmation(title: model.t("mobile.voices.delete_confirm",["name": entry.name])) {
                Task { await model.perform(onPhone: entry.phone != nil) {
                    player.clear()
                    if let voice = entry.phone { try await model.phone.voiceStore?.delete(voice); await model.phone.refresh() }
                    else { try await model.api().deleteProfile(entry.id); model.profiles = try await model.api().profiles() }
                } }
            }
        }
        .onAppear { hostScope = model.hostState.scopeID }
        .onDisappear { if hostScope != model.hostState.scopeID { player.clear() } else { player.pause() } }
    }
}
struct CloneView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var phase
    var preference: TaskLocation?
    @State private var name = ""
    @State private var consent = false
    @State private var importing = false
    @State private var audio: SelectedMedia?
    @State private var recorder = Recorder()
    @State private var work: Task<Void,Never>?
    @State private var recordingTask: Task<Void,Never>?
    @State private var running = false
    @State private var progress = 0.0
    private var asr: PhoneModel? { model.phone.selectedModel("clone",.asr) }
    private var ready: Bool { asr.map(model.phone.ready) ?? false }
    private var route: TaskRoute { LocalRouting.route(preference: preference,installed: ready,paired: model.connection.client != nil) }
    var body: some View {
        Page(backgroundRole: "surfaceOverlay") {
            if route == .download { LocalDownloadPrompt(items: asr.map { [$0] } ?? [], feature: "mobile.tabs.voices") }
            if route == .connect { NavigationLink(model.t("mobile.simple.reconnect")) { ConnectView() } }
            if route != .computer {
                DisclosureGroup(model.t("mobile.simple.more")) {
                    ChoicePicker(label: model.t("mobile.local.models"), selection: Binding(get: { asr?.id ?? "" }, set: { model.phone.chooseModel("clone",$0) }), options: model.phone.candidates(.asr).map { SelectionOption(id: $0.id, title: $0.name, subtitle: model.t("mobile.simple." + $0.capability.rawValue), enabled: $0.fits()) })
                }
            }
            TextField(model.t("mobile.voices.name_label"),text: $name).accessibilityIdentifier("voices.clone.name")
            HStack {
                Toggle(model.t("mobile.simple.voice_consent"),isOn: $consent).frame(minHeight: 44)
                InfoButton(title: model.t("mobile.voices.consent_title"),detail: model.t("mobile.voices.consent_body"))
            }
            HStack {
                Button(model.t(recorder.recording ? "common.stop" : "mobile.voices.record"),systemImage: recorder.recording ? "stop.fill" : "mic.fill") {
                    recordingTask = Task { await model.performPhone {
                        if recorder.recording { recorder.stop(); audio = recorder.file.map { SelectedMedia(url: $0) } }
                        else { audio = nil; try await recorder.start() }
                    } }
                }.disabled(!consent || running)
                Button(model.t("mobile.voices.pick_file"),systemImage: "doc") { importing = true }.disabled(recorder.recording || running)
            }
            if recorder.recording { Text(model.t("mobile.voices.recording",["seconds": String(recorder.seconds)])) }
            if let audio { SelectedFileRow(name: audio.name) { self.audio = nil } }
            Button(model.t("mobile.ios.clone_create"),systemImage: "person.badge.plus") { create() }
                .buttonStyle(VSButtonStyle(kind: .primary))
                .disabled(!consent || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || name.count > 200 || audio == nil || recorder.recording || model.busy || model.phone.activeDub != nil || running || (route != .phone && route != .computer))
            if running {
                ProgressView(value: progress).accessibilityLabel(model.t("mobile.ios.progress"))
                Button(model.t("common.cancel")) { work?.cancel() }
            }
        }.navigationTitle(model.t("mobile.voices.new_clone"))
        .toolbar { Button(model.t("common.cancel")) { work?.cancel(); recorder.stop(); dismiss() } }
        .fileImporter(isPresented: $importing,allowedContentTypes: [.audio]) { result in
            switch result { case .success(let url): audio = SelectedMedia(url: url); case .failure: model.error = ClientError("mobile.errors.file") }
        }
        .onChange(of: recorder.seconds) { _, seconds in if seconds >= 29 && recorder.recording { recorder.stop(); audio = recorder.file.map { SelectedMedia(url: $0) } } }
        .onChange(of: phase) { _, value in if value != .active { work?.cancel(); if value == .background { recordingTask?.cancel() }; if recorder.recording { recorder.stop(); audio = nil } } }
        .onDisappear { work?.cancel(); recordingTask?.cancel(); recorder.stop(); if let file = recorder.file { try? FileManager.default.removeItem(at: file) } }
    }
    private func create() {
        guard let audio else { return }
        let route = route
        running = true
        work = Task {
            defer { running = false }
            await model.perform(onPhone: route == .phone) {
                if route == .phone {
                    guard let asr, let engine = model.phone.engine, let store = model.phone.voiceStore else { throw ClientError("mobile.local.model_required") }
                    _ = try await store.create(name: name,source: audio.url,consent: consent,asr: asr,engine: engine,decoder: AVPhoneAudioDecoder(),progress: { value in await MainActor.run { progress = value.fraction } })
                    await model.phone.refresh()
                } else {
                    let access = audio.url.startAccessingSecurityScopedResource(); defer { if access { audio.url.stopAccessingSecurityScopedResource() } }
                    _ = try await model.api().clone(name: name,filename: audio.uploadName,audio: Data(contentsOf: audio.url))
                    model.profiles = try await model.api().profiles()
                }
                try Task.checkCancellation(); dismiss()
            }
        }
    }
}
