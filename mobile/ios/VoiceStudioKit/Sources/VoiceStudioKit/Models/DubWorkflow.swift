import Foundation
import Observation

public enum DubStage: String, Codable, Sendable { case preparing, transcribing, translating, rendering, done, failed, cancelled }
public struct DubLanguage: Codable, Hashable, Identifiable, Sendable {
    public let code: String
    public let name: String
    public var id: String { code }
    public init(code: String, name: String) { self.code = code; self.name = name }

}
public struct DubCheckpoint: Codable, Sendable {
    public let host: String
    public let jobID: String
    public var taskID: String?
    public var stage: DubStage
    public var afterSequence = 0
    public var segments: [Segment] = []
    public var languages: [DubLanguage]
    public var languageIndex = 0
    public var profileID: String
    public var title: String
    public init(host: String, upload: DubUpload, languages: [DubLanguage], profileID: String) {
        self.host = host; jobID = upload.job_id; taskID = upload.task_id; stage = .preparing
        self.languages = languages; self.profileID = profileID; title = upload.filename
    }
}

/// State is saved after each acknowledged host transition. UI navigation never owns the host job.
@MainActor @Observable public final class DubWorkflow {
    public private(set) var checkpoint: DubCheckpoint?
    public private(set) var progress: Double = 0
    public private(set) var error: ClientError?
    public private(set) var monitoring = false
    @ObservationIgnored private let defaults: UserDefaults
    public init(defaults: UserDefaults = .standard) { self.defaults = defaults; checkpoint = defaults.data(forKey: "dubCheckpoint").flatMap { try? JSONDecoder().decode(DubCheckpoint.self, from: $0) } }
    public func begin(_ upload: DubUpload, api: APIClient, languages: [DubLanguage], profile: String) throws {
        guard !languages.isEmpty else { throw ClientError("mobile.errors.choose_language") }
        checkpoint = DubCheckpoint(host: api.address.baseURL.absoluteString, upload: upload, languages: languages, profileID: profile)
        error = nil; progress = 0; save()
    }
    public func monitor(api: APIClient, pollInterval: Duration = .seconds(2)) async throws {
        guard !monitoring, checkpoint?.host == api.address.baseURL.absoluteString else { return }
        monitoring = true
        defer { monitoring = false }
        do {
            while var cp = checkpoint, ![.done, .failed, .cancelled].contains(cp.stage) {
                try Task.checkCancellation()
                switch cp.stage {
                case .preparing, .rendering:
                    guard let task = cp.taskID else { throw ClientError("mobile.errors.invalid_response") }
                    let page = try await api.events(task, after: cp.afterSequence)
                    try Task.checkCancellation()
                    for event in page.events {
                        cp.afterSequence = max(cp.afterSequence, event.seq)
                        if let eventProgress = DubProgress.parse(event) {
                            if ["error", "failed"].contains(eventProgress.stage) { cp.stage = .failed; checkpoint = cp; save(); throw ClientError("mobile.errors.dub_failed") }
                            progress = eventProgress.fraction
                        }
                    }
                    if page.job.status == "failed" { cp.stage = .failed; checkpoint = cp; save(); throw ClientError("mobile.errors.dub_failed") }
                    if page.job.status == "cancelled" { cp.stage = .cancelled }
                    if page.job.status == "done" {
                        progress = 0
                        if cp.stage == .preparing { cp.stage = .transcribing }
                        else { cp.languageIndex += 1; cp.stage = cp.languageIndex < cp.languages.count ? .translating : .done }
                        cp.taskID = nil; cp.afterSequence = 0
                    }
                    checkpoint = cp; save()
                    if !page.job.terminal { try await Task.sleep(for: pollInterval) }
                case .transcribing:
                    cp.segments = try await api.transcribe(cp.jobID).segments
                    try Task.checkCancellation()
                    cp.stage = .translating; checkpoint = cp; save()
                case .translating:
                    let language = cp.languages[cp.languageIndex]
                    let translated = try await api.translate(cp.jobID, segments: cp.segments, language: language.code)
                    try Task.checkCancellation()
                    guard !translated.translated.contains(where: { $0.error != nil }) else { throw ClientError("mobile.errors.translation") }
                    let byID = Dictionary(translated.translated.map { ($0.id, $0.text) }, uniquingKeysWith: { _, new in new })
                    let segments = try cp.segments.map { segment -> Segment in
                        guard let text = byID[segment.id], !text.isEmpty else { throw ClientError("mobile.errors.invalid_response") }
                        return Segment(id: segment.id, start: segment.start, end: segment.end, text: text, profile: cp.profileID, language: language.code)
                    }
                    let task = try await api.render(cp.jobID, segments: segments, language: language.code, languageName: language.name)
                    try Task.checkCancellation()
                    cp.taskID = task.task_id; cp.stage = .rendering; cp.afterSequence = 0
                    checkpoint = cp; save()
                case .done, .failed, .cancelled: break
                }
            }
        } catch is CancellationError { throw CancellationError() }
        catch let failure as ClientError { error = failure; throw failure }
        catch { let failure = ClientError("mobile.errors.dub_failed"); self.error = failure; throw failure }
    }
    public func abort(api: APIClient) async throws {
        guard var cp = checkpoint, cp.host == api.address.baseURL.absoluteString else { return }
        try await api.abort(cp.jobID, task: cp.taskID)
        cp.stage = .cancelled; checkpoint = cp; save()
    }
    private func save() { defaults.set(try? JSONEncoder().encode(checkpoint), forKey: "dubCheckpoint") }
}
