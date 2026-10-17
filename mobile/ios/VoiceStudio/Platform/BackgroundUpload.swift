import Foundation
import VoiceStudioKit
import Observation

struct PendingUpload: Codable, Sendable {
    let host: String
    let jobID: String
    let languages: [DubLanguage]
    let profile: String
    let file: URL
}
struct UploadReceipt: Codable, Sendable {
    let pending: PendingUpload
    let upload: DubUpload?
    let failure: ClientError?
}

private final class UploadBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data: [Int: Data] = [:]
    func append(_ bytes: Data, task: Int) { lock.lock(); defer { lock.unlock() }; data[task, default: Data()].append(bytes) }
    func take(task: Int) -> Data { lock.lock(); defer { lock.unlock() }; return data.removeValue(forKey: task) ?? Data() }
}

@MainActor @Observable final class BackgroundUpload: NSObject, URLSessionDataDelegate, URLSessionTaskDelegate {
    static let shared = BackgroundUpload()
    var fraction: Double = 0
    var pending: PendingUpload?
    var receipt: UploadReceipt?
    var eventsCompletion: (() -> Void)?
    var onReceipt: ((UploadReceipt) -> Void)?
    @ObservationIgnored private nonisolated let buffer = UploadBuffer()
    @ObservationIgnored private var session: URLSession!
    private override init() {
        super.init()
        pending = UserDefaults.standard.data(forKey: "pendingUpload").flatMap { try? JSONDecoder().decode(PendingUpload.self, from: $0) }
        receipt = UserDefaults.standard.data(forKey: "uploadReceipt").flatMap { try? JSONDecoder().decode(UploadReceipt.self, from: $0) }
        let config = URLSessionConfiguration.background(withIdentifier: "com.voicestudio.mobile.upload")
        config.isDiscretionary = false; config.sessionSendsLaunchEvents = true
        config.httpCookieStorage = nil; config.urlCredentialStorage = nil
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }
    func start(source: URL, api: APIClient, languages: [DubLanguage], profile: String, audioOnly: Bool) async throws {
        guard pending == nil, !languages.isEmpty else { throw ClientError("mobile.errors.choose_language") }
        let id = UUID().uuidString
        let directory = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let output = directory.appendingPathComponent("upload-\(id).multipart")
        let type = try await Task.detached {
            try Multipart.stageDub(source: source, output: output, jobID: id, audioOnly: audioOnly)
        }.value
        let meta = PendingUpload(host: api.address.baseURL.absoluteString, jobID: id, languages: languages, profile: profile, file: output)
        do {
            var request = try api.request("/dub/upload", method: "POST", contentType: type)
            request.httpBody = nil
            let task = session.uploadTask(with: request, fromFile: output)
            task.taskDescription = String(data: try JSONEncoder().encode(meta), encoding: .utf8)
            pending = meta; fraction = 0; receipt = nil
            UserDefaults.standard.set(try JSONEncoder().encode(meta), forKey: "pendingUpload")
            UserDefaults.standard.removeObject(forKey: "uploadReceipt")
            task.resume()
        } catch { try? FileManager.default.removeItem(at: output); throw error }
    }
    func cancel() async {
        for task in await session.allTasks { task.cancel() }
    }
    func clearReceipt() { receipt = nil; UserDefaults.standard.removeObject(forKey: "uploadReceipt") }
    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) { buffer.append(data, task: dataTask.taskIdentifier) }
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        let fraction = Double(totalBytesSent) / Double(max(1, totalBytesExpectedToSend))
        Task { @MainActor in self.fraction = min(1, fraction) }
    }
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
        let body = buffer.take(task: task.taskIdentifier)
        guard let description = task.taskDescription, let data = description.data(using: .utf8), let meta = try? JSONDecoder().decode(PendingUpload.self, from: data) else { return }
        let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        let authorization = task.originalRequest?.value(forHTTPHeaderField: "Authorization") != nil
        let receipt: UploadReceipt
        do {
            if error != nil { throw ClientError("mobile.ios.upload_failed") }
            _ = try APIClient.validate(HTTPReply(data: body, status: status), authenticated: authorization)
            let upload = try JSONDecoder().decode(DubUpload.self, from: body)
            receipt = UploadReceipt(pending: meta, upload: upload, failure: nil)
        } catch { receipt = UploadReceipt(pending: meta, upload: nil, failure: error as? ClientError ?? ClientError("mobile.ios.upload_failed")) }
        // Persist before iOS's background-session completion handler is called.
        UserDefaults.standard.set(try? JSONEncoder().encode(receipt), forKey: "uploadReceipt")
        UserDefaults.standard.removeObject(forKey: "pendingUpload")
        try? FileManager.default.removeItem(at: meta.file)
        Task { @MainActor in self.pending = nil; self.receipt = receipt; self.onReceipt?(receipt) }
    }
    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        Task { @MainActor in self.eventsCompletion?(); self.eventsCompletion = nil }
    }
}
