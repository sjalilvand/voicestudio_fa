import Foundation

/// GET /engines/translation: loose OpenAPI response, defined by routers/engines.py.
public struct TranslationEngines: Decodable, Sendable {
    public let active: String
    public let engines: [TranslationEngine]
    public func selected() throws -> TranslationEngine {
        guard !active.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let engine = engines.first(where: { $0.id == active }),
              engine.installed == true, engine.ready == true,
              ["offline", "online", "llm"].contains(engine.category) else {
            throw ClientError("mobile.dub.translation_setup")
        }
        return engine
    }
}

public struct TranslationEngine: Decodable, Sendable, Identifiable {
    public let id: String
    public let display_name: String
    public let category: String
    public let installed: Bool?
    public let ready: Bool?
    public var requiresConfirmation: Bool { category == "online" }
}
