#if os(iOS) && canImport(VoiceStudio)
import AVFoundation
import Foundation
import Testing
@testable import VoiceStudio

@Test @MainActor func phoneDubPlaybackRestoresPlaybackAfterDictation() throws {
    let session = AVAudioSession.sharedInstance()
    try session.setCategory(.record, mode: .measurement)
    defer { try? session.setActive(false) }
    let player = try PhoneDubPlayback.startPlayback(url: URL(fileURLWithPath: "/tmp/dub.mp4"))
    defer { player.pause() }
    #expect(session.category == .playback)
    #expect(session.mode == .default)
    #expect(player.currentItem != nil)
}
#endif
