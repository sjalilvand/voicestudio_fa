import SwiftUI
import VoiceStudioKit
import UniformTypeIdentifiers

struct DubView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var upload = BackgroundUpload.shared
    @State private var importing = false
    @State private var selectedFile: URL?
    @State private var sourceURL = ""
    @State private var selected = Set<String>()
    @State private var profile = ""
    @State private var selectingLanguages = false
    @State private var languageQuery = ""
    @State private var shared: SharedFile?
    var languages: [DubLanguage] { model.languages.dubOptions }
    var body: some View {
        Page {
            Text(model.t("mobile.dub.runs_on_host"))
            Card {
                Button(model.t("mobile.dub.pick_media"), systemImage: "doc.badge.plus") { importing = true }
                if let selectedFile { Text(model.t("mobile.ios.file_name", ["name": selectedFile.lastPathComponent])) }
                TextField(model.t("mobile.dub.paste_url"), text: $sourceURL).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("dub.source_url")
                Button { selectingLanguages = true } label: {
                    SelectionRow(label: model.t("mobile.dub.target_languages"), value: ListFormatter.localizedString(byJoining: languages.filter { selected.contains($0.code) }.map(\.name)))
                }.buttonStyle(VSButtonStyle(kind: .tertiary))
                ScrollView(.horizontal) {
                    HStack(spacing: VSTokens.spacingGap) {
                        ForEach(languages.filter { selected.contains($0.code) }) { language in
                            Button { selected.remove(language.code) } label: {
                                HStack(spacing: VSTokens.spacingGap) { Text(language.name); Image(systemName: "xmark") }
                            }.accessibilityLabel(model.t("mobile.dub.remove_language", ["language": language.name]))
                        }
                    }
                }
                VoicePicker(selection: $profile, sourceDefault: true)
                Button(model.t("mobile.dub.start")) { Task { await start() } }
                    .buttonStyle(VSButtonStyle(kind: .primary)).disabled(model.busy || upload.pending != nil || selected.isEmpty || (selectedFile == nil && sourceURL.isEmpty) || model.dub.monitoring)
            }
            if upload.pending != nil {
                Card {
                    Text(model.t("mobile.dub.uploading", ["percent": String(Int(upload.fraction * 100))]))
                    ProgressView(value: upload.fraction).accessibilityLabel(model.t("mobile.ios.progress"))
                    Text(model.t("mobile.ios.upload_pending"))
                    Button(model.t("mobile.ios.upload_cancel"), role: .destructive) { Task { await upload.cancel() } }
                }
            }
            if let cp = model.dub.checkpoint {
                Card {
                    Text(model.t("mobile.ios.dub_stages." + cp.stage.rawValue))
                    ProgressView(value: model.dub.progress).accessibilityLabel(model.t("mobile.ios.progress"))
                    if cp.host != model.connection.active?.id { Text(model.t("mobile.ios.dub_resume_help")) }
                    else if cp.stage == .done { Button(model.t("mobile.dub.download")) { Task { await download(cp.jobID) } } }
                    else if cp.stage != .cancelled {
                        if !model.dub.monitoring { Button(model.t("mobile.ios.upload_resume")) { model.monitor() } }
                        Button(model.t("mobile.dub.abort"), role: .destructive) { Task { await model.perform { model.pauseMonitor(); try await model.dub.abort(api: model.api()) } } }
                    }
                }
            }
            Text(model.t("mobile.dub.history"))
            if model.dubHistory.isEmpty { Text(model.t("mobile.dub.empty_history")) }
            ForEach(model.dubHistory) { item in
                Card {
                    Text(item.filename ?? item.id)
                    Button(model.t("mobile.dub.download")) { Task { await download(item.job_id ?? item.id) } }
                }
            }
        }.navigationTitle(model.t("mobile.tabs.dub")).navigationBarTitleDisplayMode(.large)
        .fileImporter(isPresented: $importing, allowedContentTypes: [.movie, .audio]) { result in
            switch result { case .success(let url): selectedFile = url; sourceURL = ""; case .failure: model.error = ClientError("mobile.errors.file") }
        }
        .sheet(item: $shared) { file in ShareSheet(items: [file.url]).presentationCornerRadius(VSTokens.radiusLg) }
        .sheet(isPresented: $selectingLanguages) {
            NavigationStack {
                List(model.languages.search(languageQuery, includeAuto: false)) { language in
                    Button {
                        if let code = language.code {
                            if selected.contains(code) { selected.remove(code) } else { selected.insert(code) }
                        }
                    } label: {
                        HStack(spacing: VSTokens.spacingGap) {
                            VStack(alignment: .leading, spacing: VSTokens.spacingGap) {
                                Text(language.name).lineLimit(2).truncationMode(.tail)
                                if language.code == nil { Text(model.t("mobile.dub.language_unavailable")).foregroundStyle(theme.color("textMuted")) }
                            }
                            Spacer(minLength: 0)
                            Image(systemName: language.code.map { selected.contains($0) } == true ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(theme.color("messageAction")).accessibilityHidden(true)
                        }.frame(minHeight: 44).contentShape(Rectangle())
                    }.buttonStyle(VSButtonStyle(kind: .tertiary)).disabled(language.code == nil)
                        .accessibilityLabel(language.name)
                        .accessibilityValue(model.t(language.code.map { selected.contains($0) } == true ? "mobile.ios.selected" : "mobile.ios.not_selected"))
                        .listRowBackground(theme.color("surface"))
                }
                .scrollContentBackground(.hidden).background(theme.color("surfaceOverlay"))
                .searchable(text: $languageQuery, placement: .navigationBarDrawer(displayMode: .always), prompt: Text(model.t("common.search")))
                .keyboardAccessible()
                .navigationTitle(model.t("mobile.dub.target_languages"))
                .toolbar { Button(model.t("common.confirm")) { selectingLanguages = false }.buttonStyle(VSButtonStyle(kind: .tertiary)) }
            }.presentationBackground(theme.color("surfaceOverlay")).presentationCornerRadius(VSTokens.radiusLg)
        }
        .onChange(of: sourceURL) { _, value in if !value.isEmpty { selectedFile = nil } }
        .refreshable { await model.perform { model.dubHistory = try await model.api().dubHistory() }; model.monitor() }
    }
    private func start() async {
        await model.perform {
            let api = try model.api()
            let targets = languages.filter { selected.contains($0.code) }
            if let file = selectedFile {
                let access = file.startAccessingSecurityScopedResource(); defer { if access { file.stopAccessingSecurityScopedResource() } }
                let type = UTType(filenameExtension: file.pathExtension)
                try await upload.start(source: file, api: api, languages: targets, profile: profile, audioOnly: type?.conforms(to: .audio) == true)
                selectedFile = nil
            } else {
                let result = try await api.ingest(url: sourceURL, jobID: UUID().uuidString)
                try model.dub.begin(result, api: api, languages: targets, profile: profile)
                sourceURL = ""; model.monitor()
            }
        }
    }
    private func download(_ id: String) async {
        await model.perform {
            let api = try model.api()
            let reply = try await api.download(api.request("/dub/download/\(try APIClient.component(id))"))
            let disposition = reply.headers["content-disposition"] ?? ""
            // Derive only an extension, never a server-provided local path.
            let ext = disposition.contains(".mp4") ? "mp4" : (disposition.contains(".mkv") ? "mkv" : "m4a")
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension(ext)
            try FileManager.default.moveItem(at: reply.file, to: file); shared = SharedFile(url: file)
        }
    }
}
struct SharedFile: Identifiable { let id = UUID(); let url: URL }
struct ShareSheet: UIViewControllerRepresentable {
    let items: [URL]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
