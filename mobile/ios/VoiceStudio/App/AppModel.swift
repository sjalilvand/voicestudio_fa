import Foundation
import SwiftUI
import Observation
import VoiceStudioKit
import UserNotifications

@MainActor @Observable final class AppModel {
    let connection: ConnectionStore
    let dub: DubWorkflow
    var profiles: [Profile] = []
    var inventory: EngineInventory?
    let languages = LanguageCatalog()
    var loading = false
    var history: [HistoryItem] = []
    var dubHistory: [DubHistoryItem] = []
    var error: ClientError?
    var busy = false
    @ObservationIgnored private var activityCount = 0
    var consentAnswered: Bool
    var analytics: Bool { didSet { UserDefaults.standard.set(analytics, forKey: "analytics") } }
    var notifications: Bool { didSet { UserDefaults.standard.set(notifications, forKey: "notifications") } }
    var language: String { didSet { UserDefaults.standard.set(language, forKey: "language") } }
    var theme: ThemePreferences { didSet { UserDefaults.standard.set(try? JSONEncoder().encode(theme), forKey: "theme") } }
    private(set) var monitorTask: Task<Void, Never>?
    private var notified = Set<String>()
    let mockMode: Bool
    init() {
        mockMode = ProcessInfo.processInfo.arguments.contains("--ui-smoke")
        let d = UserDefaults.standard
        if mockMode {
            d.removeObject(forKey: "consentAnswered"); d.removeObject(forKey: "activeHost")
            connection = ConnectionStore(defaults: d, vault: SmokeVault(), transport: SmokeTransport())
        } else { connection = ConnectionStore() }
        dub = DubWorkflow()
        consentAnswered = d.bool(forKey: "consentAnswered")
        analytics = d.bool(forKey: "analytics"); notifications = d.bool(forKey: "notifications")
        language = d.string(forKey: "language") ?? ""
        theme = d.data(forKey: "theme").flatMap { try? JSONDecoder().decode(ThemePreferences.self, from: $0) } ?? ThemePreferences()
    }
    @ObservationIgnored private let translator = L10n()
    var l10n: L10n { var value = translator; value.locale = (language.isEmpty ? Locale.current.identifier : language).replacingOccurrences(of: "_", with: "-"); return value }
    func t(_ key: String, _ params: [String: String] = [:]) -> String { l10n.t(key, params) }
    func chooseConsent(_ choice: Bool) { analytics = choice; consentAnswered = true; UserDefaults.standard.set(true, forKey: "consentAnswered") }
    func api() throws -> APIClient { guard let api = connection.client else { throw ClientError("mobile.errors.offline") }; return api }
    func perform(_ work: @MainActor () async throws -> Void) async {
        activityCount += 1; busy = true
        defer { activityCount -= 1; busy = activityCount > 0 }
        do { try await work() }
        catch is CancellationError {}
        catch let failure as ClientError { error = failure; await connection.handle(failure) }
        catch { self.error = ClientError("mobile.errors.file") }
    }
    func refresh() async throws {
        loading = true; defer { loading = false }
        let client = try api()
        async let p = client.profiles(); async let e = client.engines()
        async let h = client.history(); async let d = client.dubHistory()
        let results = try await (p, e, h, d)
        profiles = results.0; inventory = results.1; history = results.2; dubHistory = results.3
    }
    func monitor() {
        guard monitorTask == nil, let api = connection.client, dub.checkpoint?.host == api.address.baseURL.absoluteString else { return }
        monitorTask = Task { [weak self] in
            guard let self else { return }
            defer { monitorTask = nil }
            do {
                try await dub.monitor(api: api)
                if let cp = dub.checkpoint, cp.stage == .done { await notify(cp, failed: false) }
                dubHistory = try await api.dubHistory()
            } catch is CancellationError {} catch let e as ClientError {
                guard connection.active?.id == api.address.baseURL.absoluteString else { return }
                error = e; await connection.handle(e)
                if let cp = dub.checkpoint, e.key == "mobile.errors.dub_failed" { await notify(cp, failed: true) }
            } catch { error = ClientError("mobile.errors.dub_failed") }
        }
    }
    func pauseMonitor() { monitorTask?.cancel(); monitorTask = nil }
    func notify(_ cp: DubCheckpoint, failed: Bool) async {
        let id = cp.host + cp.jobID + (failed ? "failed" : "done")
        guard notifications, !notified.contains(id), !UserDefaults.standard.bool(forKey: id) else { return }
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else { return }
        let content = UNMutableNotificationContent()
        content.title = t(failed ? "mobile.dub.failed_notification" : "mobile.dub.done_notification", ["title": cp.title])
        content.sound = .default
        do { try await center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil)); notified.insert(id); UserDefaults.standard.set(true, forKey: id) }
        catch { error = ClientError("mobile.permissions.denied") }
    }
    func enableNotifications(_ enabled: Bool) async {
        if !enabled { notifications = false; return }
        do { notifications = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            if !notifications { error = ClientError("mobile.permissions.denied") }
        } catch { self.error = ClientError("mobile.permissions.denied") }
    }
    func acceptUpload(_ receipt: UploadReceipt) {
        guard receipt.pending.host == connection.active?.id else { return }
        if let response = receipt.upload, dub.checkpoint?.jobID != response.job_id {
            do {
                try dub.begin(response, api: api(), languages: receipt.pending.languages, profile: receipt.pending.profile)
                BackgroundUpload.shared.clearReceipt()
                monitor()
                BackgroundMonitor.schedule()
            } catch { self.error = ClientError("mobile.errors.dub_failed") }
        } else if let failure = receipt.failure { error = failure; Task { await connection.handle(failure) } }
    }
}
