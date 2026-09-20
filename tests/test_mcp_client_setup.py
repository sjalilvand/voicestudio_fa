"""Exercise desktop-exported client identities through the actual MCP transport."""
import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip('mcp')


@pytest.mark.parametrize('client_id', ['claude-code', 'cursor'])
def test_client_setup_initializes_lists_tools_and_preserves_voice_binding(monkeypatch, client_id):
    import httpx
    import mcp_server
    from services import mcp_bindings
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.testclient import TestClient

    resolved = []
    monkeypatch.setattr(mcp_bindings, 'resolve_voice', lambda client, profile: (
        resolved.append(client) or {'profile_id': 'test-profile'}
    ))
    monkeypatch.setattr(mcp_bindings, 'touch_last_seen', lambda client: None)
    from urllib.parse import parse_qs
    def generate(request):
        assert request.url.path == '/generate'
        assert parse_qs(request.content.decode())['profile_id'] == ['test-profile']
        return httpx.Response(200, content=b'test-audio', headers={'X-Audio-Id': 'test'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(generate)
    ))
    monkeypatch.setenv('OMNIVOICE_MCP_OUTPUT_MODE', 'resources')
    server = mcp_server.create_mcp_server()
    transport = server.streamable_http_app()
    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield
    app = Starlette(routes=[Mount('/mcp', app=transport)], lifespan=lifespan)
    headers = {'Accept': 'application/json, text/event-stream', 'X-OmniVoice-Client-Id': client_id}
    def result(response):
        assert response.status_code == 200, response.text
        if response.headers.get('content-type', '').startswith('text/event-stream'):
            return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))
        return response.json()
    with TestClient(app, base_url='http://127.0.0.1:3912') as client:
        initialized = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': client_id, 'version': 'test'},
            },
        })
        assert 'serverInfo' in result(initialized)['result']
        headers['Mcp-Session-Id'] = initialized.headers['mcp-session-id']
        assert client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'method': 'notifications/initialized',
        }).status_code == 202
        tools = result(client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list',
        }))
        assert 'generate_speech' in {t['name'] for t in tools['result']['tools']}
        called = result(client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'generate_speech', 'arguments': {'text': 'Hello'}},
        }))
        assert not called['result'].get('isError'), called
        assert resolved == [client_id]
