import SwiftUI
import VoiceStudioKit

struct ModelsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @State private var reviewing: PhoneModel?
    @State private var checked = false
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
                    Text(item.id).font(.headline)
                    Text(ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file))
                    HStack {
                        Text(model.t("mobile.simple." + item.capability.rawValue)).font(.caption)
                        Spacer()
                        Button(item.licence.id) { reviewing = item }.accessibilityIdentifier("model.licence."+item.id).buttonStyle(VSButtonStyle(kind: .tertiary))
                    }
                    if !item.fits() { Text(model.t("mobile.simple.ram", ["ram": String(item.min_ram_gb)])) }
                    if let value = phone.progress[item.id] {
                        ProgressView(value: value).accessibilityLabel(model.t("mobile.local.downloading"))
                        Button(model.t("common.cancel")) { phone.cancel(item) }
                    } else if phone.installed.contains(item.id) {
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item) } }
                    } else {
                        Button(model.t("mobile.local.download")) {
                            if item.licence.gated && !phone.accepted.contains(item.id) { reviewing = item }
                            else { phone.download(item) }
                        }.disabled(!item.fits())
                    }

                }
            }
        }.navigationTitle(model.t("mobile.local.models"))
        .task { await phone.refresh() }
        .sheet(item: $reviewing, onDismiss: { checked = false }) { item in
            NavigationStack {
                Page(backgroundRole: "surfaceOverlay") {
                    Text(item.id).font(.headline)
                    Text(model.t("mobile.local.licence_terms", ["licence": item.licence.id, "category": model.t("mobile.local.category_" + item.licence.category), "holder": item.licence.rights_holder, "credit": item.licence.credit]))
                    if let terms = item.licence.disclosure { Text(terms).textSelection(.enabled) }
                    Text(model.t("mobile.local.fingerprint", ["fingerprint": item.licence.terms_fingerprint])).textSelection(.enabled)
                    Text(item.languages.joined(separator: ", "))
                    Text(model.t("mobile.local.storage_used", ["size": ByteCountFormatter.string(fromByteCount: phone.modelBytes[item.id] ?? 0, countStyle: .file)]))
                    if phone.progress[item.id] == nil && (phone.modelBytes[item.id] ?? 0) > 0 && !phone.installed.contains(item.id) {
                        Button(model.t("common.delete"), role: .destructive) { Task { await phone.delete(item); reviewing = nil } }
                    }
                    if item.licence.gated {
                        Text(model.t("mobile.local.acceptance_help"))
                        Toggle(model.t("mobile.local.licence_confirm"), isOn: $checked).accessibilityIdentifier("models.consent").frame(minHeight: 44)
                        if phone.accepted.contains(item.id) {
                            Button(model.t("mobile.local.withdraw"), role: .destructive) { Task { await phone.accept(item, accepted: false); reviewing = nil } }
                        }
                        HStack {
                            Button(model.t("mobile.simple.accept")) { Task { await phone.accept(item, accepted: true); reviewing = nil } }.disabled(!checked).accessibilityIdentifier("models.accept")
                            Button(model.t("mobile.simple.decline")) { reviewing = nil }
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
    let item: PhoneModel?
    var body: some View {
        Card {
            Label(model.t("mobile.simple.models_error"), systemImage: "arrow.down.circle")
            if let item { Text(ByteCountFormatter.string(fromByteCount: item.total_bytes, countStyle: .file)).font(.caption) }
            NavigationLink(model.t("mobile.simple.download_models")) { ModelsView() }

        }
    }
}
