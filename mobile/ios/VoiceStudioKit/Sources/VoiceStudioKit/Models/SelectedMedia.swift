import Foundation

/// The picked name remains independent of any staging or upload URL.
public struct SelectedMedia: Sendable {
    public let url: URL
    public let name: String
    public init(url: URL, name: String? = nil) {
        self.url = url
        self.name = name?.nilIfBlank ?? url.lastPathComponent
    }
}
