#if os(macOS)
import Foundation
import Testing
@testable import VoiceStudioKit

/// A real loopback HTTP server exercises URLSession headers, redirects and binary bodies.
private final class LoopbackHost {
    let process = Process()
    let port: Int
    init() throws {
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-u", "-c", Self.script]
        process.standardOutput = pipe
        try process.run()
        var line = Data()
        while let byte = try pipe.fileHandleForReading.read(upToCount: 1), !byte.isEmpty {
            if byte == Data([10]) { break }; line.append(byte)
        }
        guard let port = Int(String(decoding: line, as: UTF8.self)) else { process.terminate(); throw ClientError("mobile.errors.invalid_response") }
        self.port = port
    }
    deinit { if process.isRunning { process.terminate(); process.waitUntilExit() } }
    private static let script = #"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Host(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def respond(self, body, code=200, headers={}):
        self.send_response(code)
        for key,value in headers.items(): self.send_header(key,value)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/redirect':
            self.respond(b'',302,{'Location':'http://127.0.0.1:1/leak'}); return
        if self.headers.get('X-OmniVoice-Pin') != '123456':
            self.respond(b'{"detail":"PIN required"}',401); return
        if self.path == '/health':
            self.respond(b'{"status":"ok","device":"cpu","version":"test"}',headers={'x-omnivoice-backend':'test'}); return
        if self.path == '/dub/download/socket':
            self.respond(b'RIFF-downloaded',headers={'Content-Type':'audio/wav'}); return
        self.respond(b'{"job":{"id":"prep_socket","status":"done"},"events":[] }')
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path == '/api/auth/session':
            if self.headers.get('Authorization') != 'Bearer master' or json.loads(body) != {'transport':'bearer'}:
                self.respond(b'{}',401); return
            self.respond(b'{"token":"session","expires_at":9999999999,"expires_in":3600}',201); return
        if self.headers.get('Authorization') != 'Bearer session' or self.headers.get('X-OmniVoice-Pin') != '123456':
            self.respond(b'{}',401); return
        if not self.headers.get('Content-Type','').startswith('multipart/form-data; boundary='):
            self.respond(b'{}',422); return
        if self.path == '/generate' and b'name="text"' in body:
            self.respond(b'RIFF-socket-wave',headers={'Content-Type':'audio/wav','X-Audio-Id':'socket'}); return
        if self.path == '/dub/upload' and b'name="video"' in body:
            self.respond(b'{"job_id":"socket","task_id":"prep_socket","filename":"clip.mp4"}',202); return
        self.respond(b'{}',422)
    def do_DELETE(self):
        self.respond(b'',204 if self.headers.get('Authorization') == 'Bearer session' else 401)
server=HTTPServer(('127.0.0.1',0),Host)
print(server.server_port,flush=True)
server.serve_forever()
"""#
}

@Test func urlSessionAgainstLoopbackMockServer() async throws {
    let host = try LoopbackHost()
    let address = try PairingAddress("http://127.0.0.1:\(host.port)/?pin=123456")
    let unauthenticated = APIClient(address: address)
    #expect(try await unauthenticated.health().version == "test")
    let session = try await unauthenticated.exchange(key: "master")
    let client = APIClient(address: address, credentials: Credentials(pin: address.pin, session: session.token))
    #expect(try await client.generate(text: "Hello", profile: "", engine: "", language: "").audio == data("RIFF-socket-wave"))
    var form = Multipart(); form.file("video", filename: "clip.mp4", bytes: data("clip"), mime: "video/mp4"); form.finish()
    let upload = try await client.uploadDub(form)
    #expect(try await client.events(upload.task_id, after: 0).job.terminal)
    let downloaded = try await client.download(client.request("/dub/download/socket"))
    defer { try? FileManager.default.removeItem(at: downloaded.file) }
    #expect(try Data(contentsOf: downloaded.file) == data("RIFF-downloaded"))
    try await client.revoke()
    do { _ = try await client.send(client.request("/redirect")); Issue.record("Redirect should be rejected") }
    catch let error as ClientError { #expect(error.key == "mobile.errors.redirect") }
    let noPIN = APIClient(address: try PairingAddress("http://127.0.0.1:\(host.port)"))
    do { _ = try await noPIN.health(); Issue.record("PIN should be required") }
    catch let error as ClientError { #expect(error.key == "mobile.connect.error_pin") }
}
#endif
