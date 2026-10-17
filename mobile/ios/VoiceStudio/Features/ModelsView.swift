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
            Toggle(model.t("mobile.local.mobile_data"), isOn: $phone.allowMobileData).frame(minHeight: 44)
            if let error = phone.error {
                Text(model.t(error.key, error.params)).foregroundStyle(theme.color("error"))
                Button(model.t("common.dismiss")) { phone.error = nil }
            }
            ForEach(phone.models) { item in
                Card {
                    Text(item.id).font(.headline)
                    Text(model.t("mobile.local.model_details", ["size": ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file), "languages": item.languages.map { Locale(identifier: model.l10n.locale).localizedString(forLanguageCode: $0) ?? $0 }.joined(separator: ", "), "licence": item.licence.id]))
                    Text(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: phone.modelBytes[item.id] ?? 0, countStyle: .file)]))
                    if !item.fits() { Text(model.t("mobile.local.ram_required", ["ram": String(item.min_ram_gb)])) }
                    if let value = phone.progress[item.id] {
                        ProgressView(value: value).accessibilityLabel(model.t("mobile.local.downloading"))
                        Button(model.t("common.cancel")) { phone.cancel(item) }
                    } else if phone.installed.contains(item.id) {
                        Text(model.t("mobile.local.installed"))
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item) } }
                    } else {
                        Button(model.t("mobile.local.download")) {
                            if item.licence.gated && !phone.accepted.contains(item.id) { reviewing = item }
                            else { phone.download(item) }
                        }.disabled(!item.fits())
                    }
                    if phone.progress[item.id] == nil && !phone.installed.contains(item.id) && (phone.modelBytes[item.id] ?? 0) > 0 {
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item) } }
                    }
                    Button(model.t("mobile.local.licence")) { reviewing = item }
                    if item.licence.gated && phone.accepted.contains(item.id) {
                        Button(model.t("mobile.local.withdraw"), role: .destructive) { Task { await phone.accept(item, accepted: false) } }
                    }
                }
            }
        }.navigationTitle(model.t("mobile.local.models"))
        .task { await phone.refresh() }
        .sheet(item: $reviewing) { item in
            NavigationStack {
                Page(backgroundRole: "surfaceOverlay") {
                    Text(item.id).font(.headline)
                    Text(model.t("mobile.local.licence_terms", ["licence": item.licence.id, "category": model.t("mobile.local.category_" + item.licence.category), "holder": item.licence.rights_holder, "credit": item.licence.credit]))
                    if let terms = item.licence.disclosure { Text(terms).textSelection(.enabled) }
                    Text(model.t("mobile.local.fingerprint", ["fingerprint": item.licence.terms_fingerprint])).textSelection(.enabled)
                    if item.licence.gated {
                        Text(model.t("mobile.local.acceptance_help"))
                        HStack {
                            Button(model.t("mobile.local.accept")) { Task { await phone.accept(item, accepted: true); reviewing = nil } }
                            Button(model.t("mobile.local.decline")) { reviewing = nil }
                        }
                    }
                }.navigationTitle(model.t("mobile.local.licence"))
                .toolbar { Button(model.t("common.close")) { reviewing = nil } }
            }.environment(model).presentationBackground(theme.color("surfaceOverlay"))
        }
    }
}
struct RunOnPicker: View {
    @Environment(AppModel.self) private var model
    @Binding var preference: TaskLocation?
    let task: String
    let installed: Bool
    var body: some View {
        ChoicePicker(label: model.t("mobile.local.run_on"), selection: Binding(get: {
            preference?.rawValue ?? (installed || model.connection.client == nil ? TaskLocation.phone.rawValue : TaskLocation.computer.rawValue)
        }, set: {
            guard let value = TaskLocation(rawValue: $0) else { return }
            preference = value; model.phone.choose(task, value)
        }), options: [
            SelectionOption(id: TaskLocation.phone.rawValue, title: model.t("mobile.local.this_phone")),
            SelectionOption(id: TaskLocation.computer.rawValue, title: model.t("mobile.local.my_computer"))
        ])
    }
}
struct LocalDownloadPrompt: View {
    @Environment(AppModel.self) private var model
    let item: PhoneModel?
    var body: some View {
        Card {
            if let item {
                Text(model.t("mobile.local.download_prompt", ["model": item.id, "size": ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file)]))
            } else { Text(model.t("mobile.local.model_required")) }
            NavigationLink(model.t("mobile.local.models")) { ModelsView() }
        }
    }
}
