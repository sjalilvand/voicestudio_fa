"""Editable handoff publishes a whole import or rolls it back, even on disk errors."""
import asyncio
import json
import threading
import wave
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    from core import db
    from api.routers import project_bundles as routes
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'library.db')
    db.init_db()
    for name in ('OUTPUTS_DIR', 'VOICES_DIR', 'DUB_DIR'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setattr(routes, name, directory)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), routes, db


def archive(tmp_path, *, voice=True):
    from services import project_bundle as bundles
    files = {}
    voices = []
    if voice:
        source = tmp_path / 'reference.wav'
        with wave.open(str(source), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
            out.writeframes(b'\0\0' * 24000)
        files['voices/reference.wav'] = source
        voices = [{'id':'foreign','reference':'voices/reference.wav','metadata':{'profile_name':'Imported voice','ref_text':'Reference words','kind':'clone','verified_own_voice':True}}]
    value = {'kind':'audiobook','title':'Phone edit','document':{'script':'Updated phone text','defaultVoice':'foreign' if voice else 'preset:0','cast':{},'speed':1},'voices':voices,'assets':[]}
    output = tmp_path / ('voice.vsproject' if voice else 'text.vsproject')
    bundles.write_bundle(value, files, output)
    return output.read_bytes()


def test_import_requires_permission_and_allocates_new_unverified_voice(handoff, tmp_path):
    client, routes, db = handoff
    data = archive(tmp_path)
    assert client.post('/project-bundles/import', content=data).status_code == 403
    assert list(routes._root().iterdir()) == []
    response = client.post('/project-bundles/import?allow_voices=true', content=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['project']['draft']['script'] == 'Updated phone text'
    with db.db_conn() as conn:
        profiles = [dict(row) for row in conn.execute('SELECT * FROM voice_profiles')]
    assert len(profiles) == 1
    assert profiles[0]['id'] != 'foreign'
    assert profiles[0]['verified_own_voice'] == 0
    assert result['project']['draft']['voice'] == profiles[0]['id']
    assert client.get('/project-bundles/' + result['id'] + '/document').json()['project'] == result['project']


def test_metadata_write_failure_rolls_back_database_and_copied_voice(handoff, tmp_path, monkeypatch):
    client, routes, db = handoff
    data = archive(tmp_path)
    original = Path.write_text
    def failing(self, *args, **kwargs):
        if self.name == 'result.json': raise OSError('Disk full')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', failing)
    with pytest.raises(OSError, match='Disk full'):
        client.post('/project-bundles/import?allow_voices=true', content=data)
    with db.db_conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM voice_profiles').fetchone()[0] == 0
    assert list(routes.VOICES_DIR.iterdir()) == []
    assert list(routes._root().iterdir()) == []


def test_invalid_archive_returns_client_error_and_leaves_no_inbox(handoff):
    client, routes, _ = handoff
    assert client.post('/project-bundles/import', content=b'not a zip').status_code == 400
    assert list(routes._root().iterdir()) == []
    assert client.get('/project-bundles/not-an-id').status_code == 400


def test_disconnect_waits_for_transaction_and_keeps_successful_import(handoff, tmp_path, monkeypatch):
    _, routes, db = handoff
    data = archive(tmp_path)
    entered = threading.Event(); release = threading.Event()
    original = routes._import
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(routes, '_import', slow)
    class Request:
        async def stream(self): yield data
    async def run():
        task = asyncio.create_task(routes.import_project_bundle(Request(), allow_voices=True))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
    try: asyncio.run(run())
    finally: release.set()
    assert len(routes.list_project_bundles()) == 1
    with db.db_conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM voice_profiles').fetchone()[0] == 1


def test_native_dub_import_keeps_canonical_edits_cast_and_atomic_history(handoff, tmp_path):
    from services import project_bundle as bundles
    client, routes, db = handoff
    source = tmp_path / 'source.wav'
    with wave.open(str(source), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        out.writeframes(b'\0\0' * 24000)
    document = {'duration':1,'source':'assets/source.wav','audioOnly':True,'targets':[{'code':'fr','name':'French'}],
                'segments':[{'id':'phone-cue','start':0,'end':1,'text':'Phone edit','translations':{'fr':'Texte traduit'},'speaker':'Alice','muted':True,'reference':'assets/source.wav','referenceText':'Reference words'}]}
    output = tmp_path / 'dub.vsproject'
    bundles.write_bundle({'kind':'dub','title':'Interview','document':document,'voices':[],'assets':[]}, {'assets/source.wav':source}, output)
    assert client.post('/project-bundles/import', content=output.read_bytes()).status_code == 403
    response = client.post('/project-bundles/import?allow_voices=true', content=output.read_bytes())
    assert response.status_code == 200, response.text
    identifier = response.json()['projectId']
    with db.db_conn() as conn:
        state = json.loads(conn.execute('SELECT state_json FROM studio_projects WHERE id=?', (identifier,)).fetchone()[0])
        job = json.loads(conn.execute('SELECT job_data FROM dub_history WHERE id=?', (identifier,)).fetchone()[0])
    cue = state['dubSegments'][0]
    assert cue['text_original'] == 'Phone edit'
    assert cue['text'] == 'Texte traduit'
    assert cue['speaker_id'] == 'Alice'
    assert cue['gain'] == 0
    assert job['segments'] == state['dubSegments']
    assert Path(job['segment_clones']['phone-cue']['ref_audio']).is_file()
    assert job['segment_clones']['phone-cue']['ref_text'] == 'Reference words'


def test_asset_collection_strips_secret_fields_before_reading_files(handoff, tmp_path):
    _, routes, _ = handoff
    secret = routes.OUTPUTS_DIR / 'secret.txt'
    secret.write_text('private credentials')
    files = {}
    result = routes._collect_paths({'credentials':{'path':str(secret)},'name':'Book'},files,[routes.OUTPUTS_DIR])
    assert result == {'name':'Book'}
    assert files == {}
    assert routes._restore_paths({'audio_path':'../../private.wav','output':'http://external/audio','title':'Book'}, {}) == {'audio_path':None,'output':'','title':'Book'}


def test_phone_archive_survives_desktop_edit_and_reexport_with_foreign_assets(handoff, tmp_path):
    from services import project_bundle as bundles
    client, routes, _ = handoff
    cached = tmp_path / 'checkpoint.json'; cached.write_text('{"completed":true}')
    output = tmp_path / 'portable.vsproject'
    native = {'platform':'ios','project':{'script':'Original phone text'},'configuration':'phone-model-pin','model':{'path':'model/encoder.onnx'}}
    bundles.write_bundle({'kind':'audiobook','title':'Portable','document':{'script':'Original phone text','defaultVoice':'preset:0','cast':{},'native':native},'voices':[],'assets':[]}, {'native/production/checkpoint.json':cached},output)
    imported = client.post('/project-bundles/import',content=output.read_bytes()).json()['project']
    imported['draft']['script'] = 'Edited on desktop'
    response = client.post('/project-bundles/export',json={'kind':'audiobook','project':imported})
    assert response.status_code == 200, response.text
    exported = tmp_path / 'return.vsproject'; exported.write_bytes(response.content)
    manifest, files = bundles.read_bundle(exported,tmp_path/'returned')
    assert manifest['document']['script'] == 'Edited on desktop'
    assert manifest['document']['native'] == native
    assert files['native/production/checkpoint.json'].read_text() == '{"completed":true}'
    assert 'handoff' not in manifest['document']['desktop']['draft']


def test_imported_filename_cannot_capture_an_unrelated_host_asset(handoff):
    _, routes, _ = handoff
    private = routes.OUTPUTS_DIR / 'private.wav'; private.write_bytes(b'unrelated recording')
    restored = routes._restore_paths({'extra':{'filename':str(private)},'script':'asset:literal text'}, {})
    files = {}
    collected = routes._collect_paths(restored,files,[routes.OUTPUTS_DIR])
    assert collected['extra']['filename'] is None
    assert collected['script'] == 'asset:literal text'
    assert files == {}
