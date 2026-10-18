import Foundation
import CryptoKit

public enum ModelCapability: String, Codable, Sendable { case tts, asr, stream = "asr-stream", clone, translate }
public enum ModelRuntime: String, Codable, Sendable { case sherpa = "sherpa-onnx", omni = "omnivoice.cpp", llama = "llama.cpp" }
public enum JSONValue: Codable, Sendable, Equatable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null
    public init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    public var string: String? { if case .string(let v) = self { v } else { nil } }
    public var number: Double? { if case .number(let v) = self { v } else { nil } }
}
public struct PhoneModel: Codable, Identifiable, Sendable {
    public struct File: Codable, Sendable {
        public let path: String
        public let size: Int64
        public let sha256: String
        public let role: String
    }
    public struct Licence: Codable, Sendable {
        public let id: String
        public let category: String
        public let requires_acceptance: Bool
        public let credit: String
        public let rights_holder: String
        public let terms_fingerprint: String
        public let terms: [String: JSONValue]?
        public var disclosure: String? {
            guard let terms else { return nil }
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .prettyPrinted, .withoutEscapingSlashes]
            return (try? encoder.encode(terms)).flatMap { String(data: $0, encoding: .utf8) }
        }
        public var gated: Bool { category != "commercial-ok" || requires_acceptance }
    }
    public let id: String
    public let name: String
    public let capability: ModelCapability
    public let runtime: ModelRuntime
    public let repo: String
    public let revision: String
    public let files: [File]
    public let total_bytes: Int64
    public let languages: [String]
    public let min_ram_gb: Double
    public let licence: Licence
    public let config: [String: JSONValue]
    public func fits(ram: UInt64 = ProcessInfo.processInfo.physicalMemory) -> Bool { Double(ram) >= min_ram_gb * 1_000_000_000 }
    public func selectingLanguage(_ language: String) throws -> PhoneModel {
        guard capability == .tts, languages.contains(language) else { throw ClientError("mobile.local.model_incompatible") }
        var options = config; options["lang"] = .string(language)
        return PhoneModel(id: id,name: name,capability: capability,runtime: runtime,repo: repo,revision: revision,files: files,total_bytes: total_bytes,languages: languages,min_ram_gb: min_ram_gb,licence: licence,config: options)
    }
    public func path(role: String, root: URL) -> String { files.first { $0.role == role }.map { root.appendingPathComponent($0.path).path } ?? "" }
    public func option(_ key: String, fallback: String = "") -> String { config[key]?.string ?? fallback }
}
public struct ModelCatalogue: Codable, Sendable {
    public let schema_version: Int
    public let models: [PhoneModel]
    public static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.schema_version == 1, Set(value.models.map(\.id)).count == value.models.count else { throw ClientError("mobile.local.catalogue_failed") }
        for m in value.models {
            guard safe(m.id), !m.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  m.repo.split(separator: "/").count == 2, m.repo.split(separator: "/").allSatisfy({ safe(String($0)) }),
                  hex(m.revision, count: 40), !m.files.isEmpty, m.min_ram_gb.isFinite, m.min_ram_gb > 0,
                  hex(m.licence.terms_fingerprint, count: 64), ["commercial-ok", "non-commercial", "conditional", "unidentified"].contains(m.licence.category),
                  Set(m.files.map(\.path)).count == m.files.count,
                  m.files.allSatisfy({ $0.size > 0 && hex($0.sha256, count: 64) && !$0.path.hasPrefix("/") && $0.path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy({ safe(String($0)) }) }),
                  m.files.reduce(0.0, { $0 + Double($1.size) }) == Double(m.total_bytes),
                  m.runtime == (m.capability == .clone ? .omni : m.capability == .translate ? .llama : .sherpa)
            else { throw ClientError("mobile.local.catalogue_failed") }
        }
        return value
    }
    private static func hex(_ value: String, count: Int) -> Bool { value.count == count && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } }
    private static func safe(_ value: String) -> Bool { !value.isEmpty && value != "." && value != ".." && value.utf8.allSatisfy { (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || [45,46,95].contains($0) } }
}
public enum ModelHash {
    public static func file(_ url: URL) throws -> String {
        let reader = try FileHandle(forReadingFrom: url); defer { try? reader.close() }
        var hash = SHA256()
        while let bytes = try reader.read(upToCount: 1_048_576), !bytes.isEmpty { try Task.checkCancellation(); hash.update(data: bytes) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
public enum TaskLocation: String, Codable, Sendable { case phone, computer }
public enum TaskRoute: Equatable, Sendable { case phone, computer, download, connect }
public enum LocalRouting {
    public static func route(preference: TaskLocation?, installed: Bool, paired: Bool) -> TaskRoute {
        if preference == .computer && paired { return .computer }
        if preference == .phone { return installed ? .phone : .download }
        return installed ? .phone : paired ? .computer : .download
    }
}
