import SwiftUI
import UIKit
#if DEBUG
import OSLog
#endif

@MainActor enum Keyboard {
    static func dismiss(source: String = "submit") {
#if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-smoke") {
            probeDismiss(source: source)
            return
        }
#endif
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

#if DEBUG
    // DEBUG-keyboard-probe: temporary evidence, removed before this branch lands.
    private static let logger = Logger(subsystem: "sh.voicestudio.keyboard-diagnostics", category: "dismiss")
    private static var receipt = 0
    private static func responder(in view: UIView) -> String? {
        if view.isFirstResponder { return String(describing: type(of: view)) }
        return view.subviews.lazy.compactMap { responder(in: $0) }.first
    }
    private static func windows() -> [UIWindow] {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .filter { $0.activationState == .foregroundActive }
            .flatMap(\.windows)
    }
    private static func snapshot() -> String {
        windows().map { "\(type(of: $0)):key=\($0.isKeyWindow):responder=\(responder(in: $0) ?? "none")" }.joined(separator: ";")
    }
    private static func probeDismiss(source: String) {
        receipt += 1
        let identifier = receipt
        let mode = ProcessInfo.processInfo.environment["VOICESTUDIO_KEYBOARD_DISMISS_MODE"] ?? "responder"
        logger.notice("DEBUG-keyboard-probe received=\(identifier) source=\(source, privacy: .public) mode=\(mode, privacy: .public) before=\(snapshot(), privacy: .public)")
        let result: Bool
        if mode == "window" {
            result = windows().filter(\.isKeyWindow).map { $0.endEditing(true) }.contains(true)
        } else {
            result = UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        }
        logger.notice("DEBUG-keyboard-probe returned=\(identifier) result=\(result) after=\(snapshot(), privacy: .public)")
        DispatchQueue.main.async {
            logger.notice("DEBUG-keyboard-probe next-turn=\(identifier) state=\(snapshot(), privacy: .public)")
        }
    }
#endif
}

/// Keep SwiftUI's keyboard safe area: scrolling can always reveal the next field/action.
/// Shared by pages and picker sheets with search, including sheets opened from Settings.
private struct KeyboardAccessible: ViewModifier {
    @Environment(AppModel.self) private var model
    func body(content: Content) -> some View {
        content
            .scrollDismissesKeyboard(.interactively)
            .submitLabel(.done)
            .onSubmit(of: [.text, .search]) { Keyboard.dismiss() }
            .background(KeyboardDismissRegion().allowsHitTesting(false))
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(model.t("mobile.keyboard.done")) { Keyboard.dismiss(source: "toolbar") }
                        .studioButton(.tertiary)
                        .accessibilityIdentifier("keyboard.done")
                }
            }
    }
}

extension View {
    func keyboardAccessible() -> some View { modifier(KeyboardAccessible()) }
}

/// A non-cancelling gesture observes taps outside native text inputs. A SwiftUI tap
/// gesture on the whole page would also dismiss a field as the user tries to focus it.
private struct KeyboardDismissRegion: UIViewRepresentable {
    func makeUIView(context: Context) -> KeyboardDismissView { KeyboardDismissView() }
    func updateUIView(_ uiView: KeyboardDismissView, context: Context) {}
    static func dismantleUIView(_ uiView: KeyboardDismissView, coordinator: ()) { uiView.detach() }
}

private final class KeyboardDismissView: UIView, UIGestureRecognizerDelegate {
    private lazy var tap = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))

    override func didMoveToWindow() {
        super.didMoveToWindow()
        detach()
        tap.cancelsTouchesInView = false
        tap.delegate = self
        window?.addGestureRecognizer(tap)
    }

    func detach() { tap.view?.removeGestureRecognizer(tap) }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        // Include navigation headers and surrounding chrome, not just page whitespace.
        guard window != nil else { return false }
        var ancestor: UIView? = self
        while let view = ancestor {
            if view.isHidden || view.alpha == 0 { return false }
            ancestor = view.superview
        }
        ancestor = touch.view
        while let view = ancestor {
            if view is UITextField || view is UITextView || view is UISearchBar { return false }
            ancestor = view.superview
        }
        return true
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { true }

    @objc private func dismissKeyboard() { window?.endEditing(true) }
}
