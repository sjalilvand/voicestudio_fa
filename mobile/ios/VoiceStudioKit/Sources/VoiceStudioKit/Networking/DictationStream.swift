import Foundation

public actor DictationStream {
    private var socket: URLSessionWebSocketTask?
    private var receiver: Task<Void, Never>?
    private let session: URLSession
    public init() {
        let c = URLSessionConfiguration.ephemeral
        c.httpCookieStorage = nil; c.urlCredentialStorage = nil
        session = URLSession(configuration: c, delegate: HostSessionDelegate(), delegateQueue: nil)
    }
    public func start(api: APIClient) async throws -> AsyncThrowingStream<DictationMessage, any Error> {
        close()
        let request = try await api.dictationRequest()
        let socket = session.webSocketTask(with: request)
        self.socket = socket; socket.resume()
        let (stream, continuation) = AsyncThrowingStream<DictationMessage, any Error>.makeStream(bufferingPolicy: .bufferingOldest(64))
        receiver = Task {
            do {
                while !Task.isCancelled {
                    let message = try await socket.receive()
                    let bytes: Data
                    switch message {
                    case .string(let text): bytes = Data(text.utf8)
                    case .data(let data): bytes = data
                    @unknown default: continue
                    }
                    let decoded = try JSONDecoder().decode(DictationMessage.self, from: bytes)
                    if decoded.type == "error" { throw ClientError("mobile.errors.dictation") }
                    continuation.yield(decoded)
                    if decoded.type == "final" { continuation.finish(); return }
                }
                continuation.finish()
            } catch {
                if socket.closeCode.rawValue == 1008 { continuation.finish(throwing: ClientError("mobile.errors.forbidden")) }
                else if !Task.isCancelled { continuation.finish(throwing: ClientError("mobile.errors.dictation")) }
                else { continuation.finish() }
            }
        }
        continuation.onTermination = { @Sendable [weak self] _ in Task { await self?.close() } }
        return stream
    }
    public func send(_ pcm: Data) async throws { guard let socket else { throw ClientError("mobile.errors.dictation") }; try await socket.send(.data(pcm)) }
    public func finish() async throws { try await socket?.send(.string("EOF")) }
    public func close() { receiver?.cancel(); receiver = nil; socket?.cancel(with: .normalClosure, reason: nil); socket = nil }
}
