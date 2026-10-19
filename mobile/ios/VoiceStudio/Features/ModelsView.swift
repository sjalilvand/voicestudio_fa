import SwiftUI
import VoiceStudioKit

struct ModelsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var reviewing: PhoneModel?
    var body: some View {
        @Bindable var phone = model.phone
        Form {
            Section {
                Label(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: phone.used, countStyle: .file)]), systemImage: "internaldrive")
                Toggle(model.t("mobile.simple.mobile_data"), isOn: $phone.allowMobileData)
            }.listRowBackground(theme.color("surface"))
            if phone.error != nil {
                Text(model.t("mobile.simple.models_error")).foregroundStyle(theme.color("error"))
                Button(model.t("mobile.simple.retry")) { phone.error = nil; Task { await phone.refresh() } }
            }
            ForEach(phone.models) { item in
                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.name).font(.headline)
                            Text(model.t("mobile.simple." + item.capability.rawValue)).font(.subheadline).foregroundStyle(theme.color("textMuted"))
                        }
                        Spacer()
                        Button(model.t("mobile.local.review_licence"), systemImage: "info.circle") { reviewing = item }.labelStyle(.iconOnly).accessibilityIdentifier("model.licence."+item.id).studioButton(.tertiary)
                    }
                    Text(ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file)).font(.subheadline).foregroundStyle(theme.color("textMuted"))
                    if !item.fits() { Text(model.t("mobile.simple.ram", ["ram": String(item.min_ram_gb)])) }
                    if let value = phone.progress[item.id] {
                        ProgressView(value: value).accessibilityLabel(model.t("mobile.local.download"))
                        Button(model.t("common.cancel")) { phone.cancel(item) }
                    } else if phone.installed.contains(item.id) {
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item) } }
                    } else {
                        ModelDownloadButton(items: [item], titleKey: "mobile.local.download")
                    }

                }.listRowBackground(theme.color("surface"))
            }
        }.scrollContentBackground(.hidden).background(theme.color("canvas").ignoresSafeArea())
        .navigationTitle(model.t("mobile.local.models")).navigationBarTitleDisplayMode(.large)
        .task { await phone.refresh() }
        .sheet(item: $reviewing) { item in
            ModelLicenceSheet(item: item)
        }
    }
}

struct ModelLicenceSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    let item: PhoneModel
    var onAccepted: () -> Void = {}
    @State private var checked = false
    @State private var saving = false
    var body: some View {
        let canAccept = checked && !saving
        NavigationStack {
            Form {
                Section {
                    Label {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(item.name).font(.title2.weight(.semibold))
                            Text(model.t("mobile.simple." + item.capability.rawValue)).font(.subheadline).foregroundStyle(theme.color("textMuted"))
                        }
                    } icon: { Image(systemName: "waveform").font(.title2).foregroundStyle(theme.color("messageAction")) }
                    Text(model.t("mobile.local.licence_label", ["licence": item.licence.id, "category": item.licence.category])).font(.subheadline)
                    if !item.licence.rights_holder.isEmpty { Text(item.licence.rights_holder).font(.subheadline) }
                }.listRowBackground(theme.color("surface"))
                Section {
                    if let terms = item.licence.disclosure { Text(terms).textSelection(.enabled).fixedSize(horizontal: false, vertical: true) }
                    if !item.licence.credit.isEmpty { Text(item.licence.credit).font(.footnote).foregroundStyle(theme.color("textMuted")) }
                }.listRowBackground(theme.color("surface"))
                Section {
                    DisclosureGroup(model.t("mobile.simple.more")) {
                        Text(model.t("mobile.local.terms_fingerprint", ["fingerprint": item.licence.terms_fingerprint])).font(.footnote.monospaced()).textSelection(.enabled)
                        Text(ListFormatter.localizedString(byJoining: item.languages.map { Locale(identifier: model.l10n.locale).localizedString(forLanguageCode: $0) ?? $0 })).font(.subheadline)
                        Text(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: model.phone.modelBytes[item.id] ?? 0, countStyle: .file)]))
                    }
                }.listRowBackground(theme.color("surface"))
                if model.phone.progress[item.id] == nil && (model.phone.modelBytes[item.id] ?? 0) > 0 && !model.phone.installed.contains(item.id) {
                    Button(model.t("common.delete"), role: .destructive) { Task { await model.phone.delete(item); dismiss() } }
                }
                if item.licence.gated {
                    Section {
                        Toggle(model.t("mobile.local.licence_confirm"), isOn: $checked).accessibilityIdentifier("models.consent").disabled(saving)
                    } footer: { Text(model.t("mobile.local.licensor_notice")) }
                    .listRowBackground(theme.color("surface"))
                    if model.phone.accepted.contains(item.id) {
                        Button(model.t("mobile.local.withdraw"), role: .destructive) {
                            Task { saving = true; defer { saving = false }; if await model.phone.accept(item, accepted: false) { dismiss() } }
                        }
                    }
                }
            }.scrollContentBackground(.hidden)
            .navigationTitle(model.t("mobile.local.review_licence")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("common.close")) { dismiss() }.disabled(saving)
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if item.licence.gated {
                    Button {
                        Task {
                            saving = true; defer { saving = false }
                            if await model.phone.accept(item, accepted: true) { onAccepted(); dismiss() }
                        }
                    } label: {
                        HStack { if saving { ProgressView() }; Text(model.t("mobile.simple.accept")) }.frame(maxWidth: .infinity, minHeight: 44)
                    }.studioButton(.primary)
                    .disabled(!canAccept).accessibilityIdentifier("models.accept")
                    .padding(Theme.compactInset).background(.bar)
                }
            }
        }.interactiveDismissDisabled(saving)
            .presentationDetents([.large]).presentationDragIndicator(.visible)
    }
}

/// Reused by Models and every compact feature prompt; starting a batch never bypasses terms.
struct ModelDownloadButton: View {
    @Environment(AppModel.self) private var model
    let items: [PhoneModel]
    var titleKey = "mobile.simple.get"
    @State private var queue = ModelDownloadQueue([])
    @State private var reviewing: PhoneModel?
    @State private var continueDownloads = false
    private var downloading: Bool { items.contains { model.phone.progress[$0.id] != nil } }
    var body: some View {
        Button(model.t(downloading ? "common.cancel" : titleKey)) {
            if downloading {
                queue = ModelDownloadQueue([])
                for item in items { model.phone.cancel(item) }
            } else {
                queue = ModelDownloadQueue(items); advance()
            }
        }.disabled(items.isEmpty || !items.allSatisfy { $0.fits() })
            .accessibilityIdentifier("models.get")
            .sheet(item: $reviewing, onDismiss: {
                if continueDownloads { continueDownloads = false; advance() }
                else { queue = ModelDownloadQueue([]) }
            }) { item in
                ModelLicenceSheet(item: item, onAccepted: { continueDownloads = true }).id(item.id)
            }
    }
    private func advance() {
        while let step = queue.next(installed: model.phone.installed, accepted: model.phone.accepted) {
            switch step {
            case .licence(let item): reviewing = item; return
            case .download(let item): model.phone.download(item)
            }
        }
    }
}

struct RunOnPicker: View {
    @Environment(AppModel.self) private var model
    @Binding var preference: TaskLocation?
    let task: String
    let installed: Bool
    var body: some View {
        if model.connection.client != nil {
            Picker(model.t("mobile.local.run_on"), selection: Binding(get: {
                preference ?? (installed ? .phone : .computer)
            }, set: { value in
                preference = value; model.phone.choose(task, value)
            })) {
                Text(model.t("mobile.local.this_phone")).tag(TaskLocation.phone)
                Text(model.t("mobile.simple.computer")).tag(TaskLocation.computer)
            }.pickerStyle(.segmented).frame(minHeight: 44)
        }

    }
}
struct LocalDownloadPrompt: View {
    @Environment(AppModel.self) private var model
    let items: [PhoneModel]
    let feature: String
    private var needed: [PhoneModel] { items.filter { !model.phone.ready($0) } }
    private var progress: Double? {
        guard needed.contains(where: { model.phone.progress[$0.id] != nil }) else { return nil }
        let total = needed.reduce(0.0) { $0 + Double($1.total_bytes) }
        return needed.reduce(0.0) { $0 + Double($1.total_bytes) * (model.phone.progress[$1.id] ?? 0) } / max(1, total)
    }
    private var size: String { ByteCountFormatter.string(fromByteCount: needed.reduce(0) { $0 + $1.total_bytes }, countStyle: .file) }
    private var title: String {
        if let item = needed.first, needed.count == 1 {
            return model.t("mobile.simple.download_one", ["name": item.name, "size": size])
        }
        return model.l10n.t("mobile.simple.downloads", ["feature": model.t(feature), "count": String(needed.count), "size": size], count: needed.count)
    }
    var body: some View {
        if !needed.isEmpty {
            Card {
                HStack(spacing: VSTokens.spacingGap) {
                    NavigationLink { ModelsView() } label: {
                        HStack(spacing: VSTokens.spacingGap) {
                            Image(systemName: "arrow.down.circle").accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(title)
                                if let item = needed.first, needed.count == 1 {
                                    Text(model.t("mobile.simple." + item.capability.rawValue)).font(.caption)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }.studioButton(.tertiary).accessibilityIdentifier("models.open")
                    ModelDownloadButton(items: needed)
                }
                if let progress { ProgressView(value: progress).accessibilityLabel(model.t("mobile.local.download")) }
                if let item = needed.first(where: { !$0.fits() }) {
                    Text(model.t("mobile.simple.ram", ["ram": String(item.min_ram_gb)])).font(.caption)
                }
            }.accessibilityElement(children: .contain).accessibilityIdentifier("models.prompt")
        }
    }
}
