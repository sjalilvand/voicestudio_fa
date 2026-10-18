import SwiftUI
import VoiceStudioKit
import UniformTypeIdentifiers
import AVKit

struct PhoneDubView: View {
    var projectID: UUID? = nil
    var libraryOnly = false
    private var records: [PhoneDubRecord] { model.phone.dubs.filter { projectID == nil || $0.id == projectID } }
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    var connect = false
    @State private var source: SelectedMedia?
    @State private var importing = false
    @State private var targets = Set<String>()
    @State private var languages = false
    @State private var query = ""
    @State private var voice = ""
    @State private var consent = false
    @State private var audioOnly = false
    @State private var shared: SharedFile?
    @State private var saved: SharedFile?
    @State private var playing: SharedFile?
    @State private var creating: Task<Void,Never>?
    @State private var copying = false
    private var choices: [DubLanguage] { model.languages.dubOptions }
    private var ready: Bool { model.phone.dubReady && !connect }
    var body: some View {
        Page {
            if projectID == nil && !libraryOnly {
            if connect { NavigationLink(model.t("mobile.simple.reconnect")) { ConnectView() } }
            Label(model.t("mobile.simple.source"),systemImage: "doc")
            Button(model.t("mobile.dub.pick_media"),systemImage: "doc.badge.plus") { importing = true }.disabled(copying)
            if let source { SelectedFileRow(name: source.name) { self.source = nil } }
            Label(model.t("mobile.simple.languages"),systemImage: "globe")
            Button { languages = true } label: {
                HStack(spacing: VSTokens.spacingGap) {
                    Image(systemName: "globe").accessibilityHidden(true)
                    SelectionRow(label: model.t("mobile.dub.target_languages"),value: ListFormatter.localizedString(byJoining: choices.filter { targets.contains($0.code) }.map(\.name)))
                }
            }.buttonStyle(VSButtonStyle(kind: .tertiary)).accessibilityIdentifier("dub.languages")
            ScrollView(.horizontal) {
                HStack { ForEach(choices.filter { targets.contains($0.code) }) { language in
                    Button(language.name,systemImage: "xmark") { targets.remove(language.code) }.accessibilityLabel(model.t("mobile.dub.remove_language",["language": language.name]))
                } }
            }
            Label(model.t("mobile.simple.voice"),systemImage: "person")
            ChoicePicker(label: model.t("mobile.speak.voice"),selection: $voice,options: [SelectionOption(id: "",title: model.t("mobile.simple.reference"))]+model.phone.voices.map { SelectionOption(id: $0.id.uuidString,title: $0.name) },compact: true)
            HStack {
                Toggle(model.t("mobile.simple.voice_consent"),isOn: $consent).frame(minHeight: 44)
                InfoButton(title: model.t("mobile.voices.consent_title"),detail: model.t("mobile.voices.consent_body"))
            }
            DisclosureGroup(model.t("mobile.simple.more")) {
                Toggle(model.t("mobile.simple.audio_only"),isOn: $audioOnly).frame(minHeight: 44)
                phoneModel("dub-asr",.asr)
                phoneModel("dub-translate",.translate)
                phoneModel("dub",.clone)
            }.disabled(copying || model.phone.activeDub != nil)
            LocalDownloadPrompt(items: model.phone.dubModels, feature: "mobile.tabs.dub")
            Button(model.t("mobile.simple.dub"),systemImage: "film") { start() }.buttonStyle(VSButtonStyle(kind: .primary))
                .disabled(!ready || !consent || source == nil || targets.isEmpty || model.busy || copying || model.phone.activeDub != nil)
                .accessibilityIdentifier("dub.start")
            if copying { ProgressView().accessibilityLabel(model.t("mobile.ios.progress")) }
            }
            ForEach(records.filter { !$0.checkpoint.done }) { record in
                Card {
                    Text(record.request.title).lineLimit(1)
                    let progress = model.phone.activeDub == record.id ? model.phone.dubProgress : nil
                    let percent = progress?.percent ?? record.checkpoint.percent
                    HStack {
                        Text(model.t(progress?.stage ?? record.checkpoint.stage)).frame(maxWidth: .infinity,alignment: .leading)
                        Text(model.t("mobile.simple.percent",["percent": String(percent)]))
                    }
                    ProgressView(value: Double(percent)/100).accessibilityLabel(model.t("mobile.ios.progress"))
                    if model.phone.activeDub == record.id {
                        Button(model.t("common.cancel"),systemImage: "xmark") { model.phone.cancelDub() }
                    } else {
                        HStack {
                            Button(model.t("mobile.simple.resume"),systemImage: "play.fill") { model.phone.startDub(record.id) }.disabled(model.phone.activeDub != nil || model.busy)
                            Button(model.t("mobile.simple.remove_job"),systemImage: "trash",role: .destructive) { remove(record) }.labelStyle(.iconOnly)
                        }
                    }
                }
            }
            Text(model.t("mobile.dub.history"))
            if records.allSatisfy({ $0.checkpoint.outputs.isEmpty }) { EmptyState(key: "mobile.simple.empty_dubs",icon: "film") }
            ForEach(records) { record in
                ForEach(record.checkpoint.outputs) { output in
                    HStack {
                        VStack(alignment: .leading) { Text(record.request.title).lineLimit(1); Text(output.name).font(.caption).foregroundStyle(theme.color("textMuted")) }.frame(maxWidth: .infinity,alignment: .leading)
                        Button(model.t("common.play"),systemImage: "play.fill") { open(record,output,action: .play) }
                        Button(model.t("mobile.speak.share"),systemImage: "square.and.arrow.up") { open(record,output,action: .share) }
                        Button(model.t("common.save"),systemImage: "arrow.down.to.line") { open(record,output,action: .save) }
                        if record.checkpoint.done { Button(model.t("mobile.simple.remove_job"),systemImage: "trash",role: .destructive) { remove(record) } }
                    }.labelStyle(.iconOnly).buttonStyle(VSButtonStyle(kind: .tertiary))
                }
            }
        }.navigationTitle(projectID != nil ? (records.first?.request.title ?? model.t("projects.title")) : model.t(libraryOnly ? "projects.title" : "mobile.tabs.dub")).navigationBarTitleDisplayMode(.large)
        .fileImporter(isPresented: $importing,allowedContentTypes: [.movie,.audio]) { result in
            switch result { case .success(let url): source = SelectedMedia(url: url); case .failure: model.error = ClientError("mobile.simple.media_failed") }
        }
        .sheet(isPresented: $languages) {
            NavigationStack {
                List {
                    SearchField(prompt: model.t("common.search"),text: $query)
                    let filtered = model.languages.search(query,includeAuto: false).filter { $0.code != nil }
                    if filtered.isEmpty { SearchEmptyState(query: query) }
                    ForEach(filtered) { language in
                        Button {
                            if let code = language.code { if targets.contains(code) { targets.remove(code) } else { targets.insert(code) } }
                        } label: {
                            HStack { Text(language.name); Spacer(); Image(systemName: targets.contains(language.code ?? "") ? "checkmark.circle.fill" : "circle") }.frame(minHeight: 44)
                        }.buttonStyle(VSButtonStyle(kind: .tertiary))
                            .accessibilityValue(model.t(targets.contains(language.code ?? "") ? "mobile.ios.selected" : "mobile.ios.not_selected"))
                            .accessibilityAddTraits(targets.contains(language.code ?? "") ? .isSelected : [])
                            .listRowBackground(theme.color("surface"))
                    }
                }.scrollContentBackground(.hidden).background(theme.color("surfaceOverlay")).keyboardAccessible()
                    .navigationTitle(model.t("mobile.dub.target_languages"))
                    .toolbar { Button(model.t("common.confirm")) { languages = false } }
            }.presentationBackground(theme.color("surfaceOverlay"))
        }
        .sheet(item: $shared) { file in ShareSheet(items: [file.url]) }
        .sheet(item: $saved) { file in SaveFileSheet(url: file.url) }
        .sheet(item: $playing) { file in PhoneDubPlayback(url: file.url) }
        .onChange(of: model.phone.voices) { _, voices in if !voices.contains(where: { $0.id.uuidString == voice }) { voice = "" } }
        .refreshable { await model.phone.refresh() }
        .onDisappear { creating?.cancel() }
    }
    private func phoneModel(_ task: String,_ capability: ModelCapability) -> some View {
        ChoicePicker(label: model.t("mobile.simple."+capability.rawValue),selection: Binding(get: { model.phone.selectedModel(task,capability)?.id ?? "" },set: { model.phone.chooseModel(task,$0) }),options: model.phone.candidates(capability).map { SelectionOption(id: $0.id,title: $0.name,subtitle: model.t("mobile.simple." + $0.capability.rawValue),enabled: $0.fits()) })
    }
    private func start() {
        guard let source else { return }
        let selectedModels = model.phone.dubModels, selectedTargets = choices.filter { targets.contains($0.code) }.map { PhoneDubTarget(code: $0.code,name: $0.name) }
        let chosenVoice = model.phone.voices.first { $0.id.uuidString == voice }, exportAudio = audioOnly
        copying = true
        creating = Task {
            defer { copying = false }
            await model.performPhone {
                guard let store = model.phone.dubStore else { throw ClientError("mobile.simple.checkpoint_failed") }
                let reference: PCMChunk?
                if let chosenVoice { reference = try await model.phone.voiceStore?.reference(chosenVoice) } else { reference = nil }
                let request = try await store.create(source: source.url,title: source.name,targets: selectedTargets,models: selectedModels,consent: consent,reference: reference,referenceText: chosenVoice?.transcript,audioOnly: exportAudio)
                self.source = nil; consent = false; await model.phone.refresh(); model.phone.startDub(request.id)
            }
        }
    }
    private enum OutputAction { case play,share,save }
    private func open(_ record: PhoneDubRecord,_ output: PhoneDubOutput,action: OutputAction) {
        Task { await model.performPhone {
            guard let store = model.phone.dubStore else { throw ClientError("mobile.simple.media_failed") }
            let url = try await store.verifiedOutput(record.id,output)
            let file = SharedFile(url: url)
            switch action { case .play: playing = file; case .share: shared = file; case .save: saved = file }
        } }
    }
    private func remove(_ record: PhoneDubRecord) {
        Task { await model.performPhone { try await model.phone.dubStore?.delete(record.id); await model.phone.refresh() } }
    }
}
private struct PhoneDubPlayback: View {
    let url: URL
    @State private var player: AVPlayer?
    var body: some View {
        VideoPlayer(player: player).onAppear { player = AVPlayer(url: url); player?.play() }.onDisappear { player?.pause(); player = nil }
    }
}
