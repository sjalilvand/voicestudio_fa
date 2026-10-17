import SwiftUI
import VoiceStudioKit

struct SelectionOption: Identifiable {
    let id: String
    let title: String
    var subtitle: String? = nil
    var enabled = true
}

struct SelectionRow: View {
    @Environment(\.vsTheme) private var theme
    @Environment(\.dynamicTypeSize) private var typeSize
    let label: String
    let value: String
    var body: some View {
        HStack(spacing: VSTokens.spacingGap) {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: VSTokens.spacingGap) { Text(label); current }
                Spacer(minLength: 0)
            } else {
                Text(label).fixedSize(horizontal: true, vertical: false).layoutPriority(1)
                Spacer(minLength: VSTokens.spacingGap)
                current
            }
            Image(systemName: "chevron.right").foregroundStyle(theme.color("iconMuted")).accessibilityHidden(true)
        }
        .frame(minHeight: 44).contentShape(Rectangle())
        .accessibilityElement(children: .ignore).accessibilityLabel(label).accessibilityValue(value)
    }
    private var current: some View {
        Text(value).foregroundStyle(theme.color("textMuted"))
            .lineLimit(1).truncationMode(.tail).multilineTextAlignment(.trailing)
    }
}

struct ChoicePicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    let label: String
    @Binding var selection: String
    let options: [SelectionOption]
    @State private var presenting = false
    @State private var query = ""
    var body: some View {
        Button { query = ""; presenting = true } label: {
            SelectionRow(label: label, value: options.first { $0.id == selection }?.title ?? model.t("common.unknown"))
        }.buttonStyle(VSButtonStyle(kind: .tertiary))
        .sheet(isPresented: $presenting) {
            NavigationStack {
                choices
                    .navigationTitle(label).navigationBarTitleDisplayMode(.inline)
                    .toolbar { Button(model.t("common.close")) { presenting = false }.buttonStyle(VSButtonStyle(kind: .tertiary)) }
            }
            .presentationBackground(theme.color("surfaceOverlay"))
            .presentationCornerRadius(VSTokens.radiusLg)
        }
    }
    private var choices: some View {
        List {
            SearchField(prompt: model.t("common.search"), text: $query).listRowBackground(theme.color("surfaceOverlay"))
            ForEach(options.filter { query.isEmpty || $0.title.localizedCaseInsensitiveContains(query) || $0.id.localizedCaseInsensitiveContains(query) }) { option in
                Button {
                    selection = option.id; presenting = false
                } label: {
                    HStack(spacing: VSTokens.spacingGap) {
                        VStack(alignment: .leading, spacing: VSTokens.spacingGap) {
                            Text(option.title).foregroundStyle(theme.color(option.enabled ? "text" : "textMuted"))
                                .lineLimit(2).truncationMode(.tail)
                            if let subtitle = option.subtitle { Text(subtitle).font(.custom("InterVariable", size: VSTokens.textLabel.size, relativeTo: .caption)).foregroundStyle(theme.color("textMuted")) }
                        }
                        Spacer(minLength: 0)
                        if selection == option.id { Image(systemName: "checkmark").foregroundStyle(theme.color("messageAction")) }
                    }.frame(minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(VSButtonStyle(kind: .tertiary)).disabled(!option.enabled)
                    .accessibilityLabel(option.title).accessibilityValue(option.subtitle ?? "")
                    .accessibilityIdentifier("choice.option." + option.id).listRowBackground(theme.color("surface"))
            }
        }
        .scrollContentBackground(.hidden).background(theme.color("surfaceOverlay"))
        .keyboardAccessible()
    }
}

/// In-content search. The system `.searchable` bar never gets SwiftUI's keyboard
/// toolbar (no Done) and hides sheet toolbar items while active, so every search
/// in the app uses this plain field instead.
struct SearchField: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    let prompt: String
    @Binding var text: String
    var body: some View {
        HStack(spacing: VSTokens.spacingGap) {
            Image(systemName: "magnifyingglass").foregroundStyle(theme.color("textMuted")).accessibilityHidden(true)
            TextField(prompt, text: $text)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .submitLabel(.search)
                .accessibilityIdentifier("search.field")
            if !text.isEmpty {
                Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }
                    .labelStyle(.iconOnly).foregroundStyle(theme.color("textMuted"))
                    .frame(minWidth: 44, minHeight: 44).accessibilityLabel(model.t("common.clear"))
            }
        }
        .padding(.horizontal, VSTokens.spacingGap).frame(minHeight: 44)
        .background(theme.color("input"), in: RoundedRectangle(cornerRadius: VSTokens.radiusControl))
    }
}

/// Destructive confirmations use the same token surfaces/shapes as every other sheet.
struct DeleteConfirmation: View {
    @Environment(AppModel.self) private var model
    @Environment(\.vsTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    let title: String
    let onDelete: () -> Void
    var body: some View {
        NavigationStack {
            Page(backgroundRole: "surfaceOverlay") {
                Text(title)
                Button(model.t("common.delete"), role: .destructive) { onDelete(); dismiss() }
                    .buttonStyle(VSButtonStyle(kind: .secondary))
            }.navigationTitle(model.t("common.delete")).navigationBarTitleDisplayMode(.inline)
                .toolbar { Button(model.t("common.cancel")) { dismiss() }.buttonStyle(VSButtonStyle(kind: .tertiary)) }
        }.presentationBackground(theme.color("surfaceOverlay"))
            .presentationCornerRadius(VSTokens.radiusLg).presentationDetents([.medium, .large])
    }
}
