import SwiftUI
import VoiceStudioKit

struct ModelsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var reviewing: PhoneModel?
    var body: some View {
        @Bindable var phone = model.phone
        Page {
            Text(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: phone.used, countStyle: .file)]))
            Toggle(model.t("mobile.simple.mobile_data"), isOn: $phone.allowMobileData).frame(minHeight: 44)
            if phone.error != nil {
                Text(model.t("mobile.simple.models_error")).foregroundStyle(theme.color("error"))
                Button(model.t("mobile.simple.retry")) { phone.error = nil; Task { await phone.refresh() } }
            }
            ForEach(phone.models) { item in
                Card {
                    Text(item.name).font(.headline)
                    Text(ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file))
                    HStack {
                        Text(model.t("mobile.simple." + item.capability.rawValue)).font(.caption)
                        Spacer()
                        Button(model.t("mobile.simple.info"), systemImage: "info.circle") { reviewing = item }.accessibilityIdentifier("model.licence."+item.id).buttonStyle(VSButtonStyle(kind: .tertiary))
                    }
                    if !item.fits() { Text(model.t("mobile.simple.ram", ["ram": String(item.min_ram_gb)])) }
                    if let value = phone.progress[item.id] {
                        ProgressView(value: value).accessibilityLabel(model.t("mobile.local.downloading"))
                        Button(model.t("common.cancel")) { phone.cancel(item) }
                    } else if phone.installed.contains(item.id) {
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item) } }
                    } else {
                        ModelDownloadButton(items: [item], titleKey: "mobile.local.download")
                    }

                }
            }
        }.navigationTitle(model.t("mobile.local.models"))
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
        NavigationStack {
            Page(backgroundRole: "surfaceOverlay") {
                Text(item.name).font(.headline)
                Text(model.t("mobile.local.licence_terms", ["licence": item.licence.id, "category": model.t("mobile.local.category_" + item.licence.category), "holder": item.licence.rights_holder, "credit": item.licence.credit]))
                if let terms = item.licence.disclosure { Text(terms).textSelection(.enabled) }
                Text(model.t("mobile.local.fingerprint", ["fingerprint": item.licence.terms_fingerprint])).textSelection(.enabled)
                Text(item.languages.joined(separator: ", "))
                Text(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: model.phone.modelBytes[item.id] ?? 0, countStyle: .file)]))
                if model.phone.progress[item.id] == nil && (model.phone.modelBytes[item.id] ?? 0) > 0 && !model.phone.installed.contains(item.id) {
                    Button(model.t("common.delete"), role: .destructive) { Task { await model.phone.delete(item); dismiss() } }
                }
                if item.licence.gated {
                    Text(model.t("mobile.local.acceptance_help"))
                    Toggle(model.t("mobile.local.licence_confirm"), isOn: $checked).accessibilityIdentifier("models.consent").frame(minHeight: 44)
                    if model.phone.accepted.contains(item.id) {
                        Button(model.t("mobile.local.withdraw"), role: .destructive) {
                            Task { saving = true; defer { saving = false }; if await model.phone.accept(item, accepted: false) { dismiss() } }
                        }
                    }
                    HStack {
                        Button(model.t("mobile.simple.accept")) {
                            Task {
                                saving = true; defer { saving = false }
                                if await model.phone.accept(item, accepted: true) { onAccepted(); dismiss() }
                            }
                        }.disabled(!checked || saving).accessibilityIdentifier("models.accept")
                        Button(model.t("mobile.simple.decline")) { dismiss() }.disabled(saving)
                    }
                }
            }.navigationTitle(model.t("mobile.local.licence"))
                .toolbar { Button(model.t("common.close")) { dismiss() }.disabled(saving) }
        }.interactiveDismissDisabled(saving).presentationBackground(theme.color("surfaceOverlay"))
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
                    }.buttonStyle(VSButtonStyle(kind: .tertiary)).accessibilityIdentifier("models.open")
                    ModelDownloadButton(items: needed)
                }
                if let progress { ProgressView(value: progress).accessibilityLabel(model.t("mobile.local.downloading")) }
                if let item = needed.first(where: { !$0.fits() }) {
                    Text(model.t("mobile.simple.ram", ["ram": String(item.min_ram_gb)])).font(.caption)
                }
            }.accessibilityIdentifier("models.prompt")
        }
    }
}
