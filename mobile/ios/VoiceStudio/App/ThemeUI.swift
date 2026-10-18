import SwiftUI
import VoiceStudioKit

private struct ThemeKey: EnvironmentKey { static let defaultValue = Theme() }
extension EnvironmentValues {
    var vsTheme: Theme { get { self[ThemeKey.self] } set { self[ThemeKey.self] = newValue } }
}
extension Theme {
    func color(_ role: String) -> Color { let c = self[role]; return Color(.sRGB, red: c.r, green: c.g, blue: c.b, opacity: c.a) }
}
enum VSButtonKind { case primary, secondary, tertiary }
struct VSButtonStyle: ButtonStyle {
    @Environment(\.vsTheme) private var theme
    @Environment(\.isEnabled) private var enabled
    var kind: VSButtonKind = .secondary
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.custom("InterVariable", size: Theme.controlTypeSize, relativeTo: .body))
            .frame(minWidth: 44, minHeight: 44)
            .frame(maxWidth: kind == .primary ? .infinity : nil)
            .padding(.horizontal, kind == .tertiary ? 0 : VSTokens.spacingGap)
            .foregroundStyle(theme.color(!enabled ? "mutedForeground" : (configuration.role == .destructive ? "error" : (kind == .primary ? "messageActionForeground" : "text"))))
            .background {
                if kind != .tertiary {
                    RoundedRectangle(cornerRadius: VSTokens.radiusControl)
                        .fill(theme.color(!enabled ? "muted" : (kind == .primary ? (configuration.isPressed ? "messageActionHover" : "messageAction") : (configuration.isPressed ? "muted" : "surface"))))
                }
            }
            .overlay {
                if kind == .secondary { RoundedRectangle(cornerRadius: VSTokens.radiusControl).strokeBorder(theme.color("border")) }
            }
    }
}
struct VSFieldStyle: TextFieldStyle {
    @Environment(\.vsTheme) private var theme
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration.padding(Theme.compactInset).frame(minHeight: 44)
            .background(theme.color("input"), in: RoundedRectangle(cornerRadius: VSTokens.radiusControl))
            .tint(theme.color("focus"))
    }
}
struct Page<Content: View>: View {
    @Environment(\.vsTheme) private var theme
    @Environment(AppModel.self) private var model
    let content: Content
    let backgroundRole: String
    init(backgroundRole: String = "canvas", @ViewBuilder content: () -> Content) { self.backgroundRole = backgroundRole; self.content = content() }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: VSTokens.spacingGap) {
                if model.loading {
                    ProgressView(model.t("common.loading")).frame(minHeight: 44).accessibilityIdentifier("page.loading")
                }
                content
            }
                .padding(Theme.compactInset).frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(theme.color(backgroundRole))
        .keyboardAccessible()
    }
}
struct Card<Content: View>: View {
    @Environment(\.vsTheme) private var theme
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: VSTokens.spacingGap) { content }
            .frame(maxWidth: .infinity, alignment: .leading).padding(Theme.compactInset)
            .background(theme.color("surface"), in: RoundedRectangle(cornerRadius: VSTokens.radiusLg))
            .overlay(RoundedRectangle(cornerRadius: VSTokens.radiusLg).strokeBorder(theme.color("border")))
    }
}
struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var scheme
    @State private var recovery: String?
    var body: some View {
        let theme = Theme(palette: model.theme.palette(system: scheme == .dark ? .dark : .light), appearance: model.theme.appearance(system: scheme == .dark ? .dark : .light))
        Group {
            if !model.consentAnswered { ConsentView() }
            else {
                TabView {
                        NavigationStack { HomeView() }.tabItem { Label(model.t("nav.home"), systemImage: "house") }
                        NavigationStack { VoicesView() }.tabItem { Label(model.t("mobile.tabs.voices"), systemImage: "person.wave.2") }
                        NavigationStack { DubView() }.tabItem { Label(model.t("mobile.tabs.dub"), systemImage: "film") }
                        NavigationStack { DictateView() }.tabItem { Label(model.t("mobile.tabs.dictate"), systemImage: "mic") }
                    NavigationStack { SettingsView() }.tabItem { Label(model.t("mobile.tabs.settings"), systemImage: "gearshape") }
                }
                .id(model.hostState.scopeID)
                .toolbarBackground(theme.color("chrome"), for: .tabBar)
                .toolbarBackground(.visible, for: .tabBar)
            }
        }
        .task { await model.phone.refresh() }
        .onAppear { NativeTheme.apply(theme) }
        .onChange(of: model.theme) { _, _ in NativeTheme.apply(theme) }
        .onChange(of: scheme) { _, _ in NativeTheme.apply(theme) }
        .environment(\.vsTheme, theme)
        .font(.custom("InterVariable", size: VSTokens.textEditor.size, relativeTo: .body))
        .foregroundStyle(theme.color("text")).tint(theme.color("messageAction"))
        .buttonStyle(VSButtonStyle()).textFieldStyle(VSFieldStyle())
        .background(theme.color("canvas"))
        .toolbarBackground(theme.color("chrome"), for: .navigationBar)
        .sheet(isPresented: Binding(get: { recovery != nil },set: { if !$0 { recovery = nil } })) {
            NavigationStack {
                Group { if recovery == "models" { ModelsView() } else { ConnectView() } }
                    .toolbar { Button(model.t("common.close")) { recovery = nil } }
            }.environment(model).environment(\.vsTheme,theme)
        }
        .safeAreaInset(edge: .top) {
            if let error = model.error ?? model.phone.error {
                HStack(spacing: VSTokens.spacingGap) {
                    ErrorNotice(error: error).foregroundStyle(theme.color("error"))
                        .frame(maxWidth: .infinity,alignment: .leading)
                    if error.key.hasPrefix("mobile.local.") {
                        Button(model.t("mobile.simple.download_models")) { model.error = nil; model.phone.error = nil; recovery = "models" }
                    } else if error.key == "mobile.permissions.denied" {
                        Button(model.t("mobile.permissions.open_settings")) {
                            model.error = nil; model.phone.error = nil
                            if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                        }
                    } else if error.status == 401 || error.key.contains("offline") || error.key.contains("connection") {
                        Button(model.t("mobile.simple.reconnect")) { model.error = nil; model.phone.error = nil; recovery = "connect" }
                    } else {
                        Button(model.t("mobile.simple.retry")) {
                            model.error = nil; model.phone.error = nil
                            Task { await model.phone.refresh(); if model.connection.client != nil { await model.perform { try await model.refresh() } } }
                        }
                    }
                }.padding(Theme.compactInset).background(theme.color("errorSurface"))
                    .environment(\.vsTheme,theme).buttonStyle(VSButtonStyle(kind: .tertiary))
            }

        }
    }

}
struct ErrorNotice: View {
    @Environment(AppModel.self) private var model
    let error: ClientError
    var titleKey: String?
    var body: some View {
        let message = ErrorPresentation(error,l10n: model.l10n,titleKey: titleKey)
        VStack(alignment: .leading,spacing: 2) {
            Text(message.title)
            if let detail = message.detail { Text(detail).font(.footnote) }
        }.fixedSize(horizontal: false,vertical: true)
    }
}
struct ConsentView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        Page {
            Text(model.t("privacy.analytics_title")).font(.custom("InterVariable", size: VSTokens.textEditor.size, relativeTo: .title))
            Text(model.t("mobile.consent.phone_note"))
            InfoButton(title: model.t("mobile.simple.info"), detail: model.t("privacy.analytics_subtitle"))
            ViewThatFits(in: .horizontal) {
                HStack(spacing: VSTokens.spacingGap) { choice(true); choice(false) }
                VStack(spacing: VSTokens.spacingGap) { choice(true); choice(false) }
            }
            Button(model.t("common.dismiss")) { model.chooseConsent(false) }.accessibilityIdentifier("consent.dismiss")
        }.interactiveDismissDisabled()
    }
    func choice(_ value: Bool) -> some View {
        Button(model.t(value ? "common.yes" : "common.no")) { model.chooseConsent(value) }
            .buttonStyle(VSButtonStyle(kind: .secondary)).frame(maxWidth: .infinity).accessibilityIdentifier(value ? "consent.yes" : "consent.no")
    }
}
