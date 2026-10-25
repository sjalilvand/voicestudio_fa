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
    assert cue['profile_id'] == 'auto-seg:phone-cue'
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


def test_phone_voice_edit_replaces_stale_desktop_snapshot_bindings(handoff, tmp_path):
    from services import project_bundle as bundles
    client, routes, db = handoff
    source = tmp_path / 'new.wav'; source.write_bytes(b'new reference')
    project = {'name':'Story','mode':'stories','draft':{
        'voice':'old-default','cast':[{'id':'alice','name':'Alice','profileId':'old-cast'}],
        'lines':[{'id':'one','character':'alice','profileId':'old-override','text':'Hello'}]}}
    document = bundles.manuscript_document(project)
    document['defaultVoice'] = 'new'
    document['cast'] = {role:'new' for role in document['cast']}
    output = tmp_path / 'edit.vsproject'
    bundles.write_bundle({'kind':'stories','title':'Story','document':document,'voices':[{'id':'new','reference':'voices/new.wav','metadata':{}}]}, {'voices/new.wav':source}, output)
    response = client.post('/project-bundles/import?allow_voices=true',content=output.read_bytes())
    assert response.status_code == 200, response.text
    draft = response.json()['project']['draft']
    assert draft['voice'] and draft['voice'] == draft['lines'][0]['profileId']
    assert draft['cast'][0]['profileId'] is None  # Unused, unbundled snapshot bindings are discarded.
    assert 'old-' not in json.dumps(draft)
    assert client.post('/project-bundles/export',json={'kind':'stories','project':response.json()['project']}).status_code == 200


def test_canonical_missing_voice_is_still_rejected(handoff, tmp_path):
    from services import project_bundle as bundles
    client, _, _ = handoff
    output = tmp_path / 'missing.vsproject'
    bundles.write_bundle({'kind':'audiobook','title':'Book','document':{'script':'Hello','defaultVoice':'missing','cast':{}},'voices':[]}, {}, output)
    assert client.post('/project-bundles/import?allow_voices=true',content=output.read_bytes()).status_code == 400


def test_rendered_output_import_uses_downloadable_relative_path(handoff, tmp_path):
    from services import project_bundle as bundles
    client, routes, _ = handoff
    source = routes.OUTPUTS_DIR / 'rendered.mp3'; source.write_bytes(b'rendered audio')
    project = {'name':'Rendered','mode':'audiobook','draft':{'script':'Hello','output':'rendered.mp3'}}
    exported = client.post('/project-bundles/export',json={'kind':'audiobook','project':project})
    assert exported.status_code == 200, exported.text
    imported = client.post('/project-bundles/import',content=exported.content)
    assert imported.status_code == 200, imported.text
    output = imported.json()['project']['draft']['output']
    assert not Path(output).is_absolute()
    assert (routes.OUTPUTS_DIR / output).read_bytes() == b'rendered audio'
    from fastapi.staticfiles import StaticFiles
    client.app.mount('/audio',StaticFiles(directory=routes.OUTPUTS_DIR))
    assert client.get('/audio/'+output).content == b'rendered audio'
    assert client.post('/project-bundles/export',json={'kind':'audiobook','project':imported.json()['project']}).status_code == 200


@pytest.mark.parametrize('binding,expected,mode', [
    ('auto:speaker_1','line','per_line'),
    ('auto:speaker_2','speaker','per_line'),
    ('auto-seg:other','other','per_line'),
    ('auto:speaker_1','other','consistent'),
    ('auto-seg:one','other','consistent'),
    ('auto:missing',None,'per_line'),
])
def test_source_voice_dub_export_resolves_automatic_bindings(handoff, tmp_path, monkeypatch, binding, expected, mode):
    from services import dub_pipeline, project_bundle as bundles
    client, routes, db = handoff
    source = routes.DUB_DIR / 'source.wav'; source.write_bytes(b'source')
    references = {}
    for name in ('line','speaker','other'):
        path = routes.DUB_DIR / (name+'.wav'); path.write_bytes(name.encode())
        references[name] = {'ref_audio':str(path),'ref_text':name+' transcript'}
    segment = {'id':'one','start':0,'end':1,'text':'Hello','speaker_id':'Speaker 1','profile_id':binding}
    state = {'dubJobId':'job','dubSegments':[segment],'dubLangCode':'fr','dubLang':'French','inputType':'audio','voiceMatch':mode}
    job = {'video_path':str(source),'segments':[segment], 'segment_clones':{'one':references['line'],'other':references['other']}, 'speaker_clones':{'Speaker 1':references['other'],'Speaker 2':references['speaker']}}
    monkeypatch.setattr(dub_pipeline,'get_job',lambda _:job)
    with db.db_conn() as conn:
        conn.execute('INSERT INTO studio_projects (id,name,audio_path,duration,state_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',('project','Interview',str(source),1,json.dumps(state),0,0))
    response = client.post('/project-bundles/export',json={'kind':'dub','project_id':'project'})
    if expected is None:
        assert response.status_code == 400
        assert list(routes._root().iterdir()) == []
        return
    assert response.status_code == 200, response.text
    archive = tmp_path / 'source-voice.vsproject'; archive.write_bytes(response.content)
    manifest, files = bundles.read_bundle(archive,tmp_path/'source-voice')
    assert manifest['voices'] == []
    cue = manifest['document']['segments'][0]
    assert not cue.get('voiceID') and not cue.get('profile_id')
    assert files[cue['reference']].read_bytes() == expected.encode()
    assert cue['referenceText'] == expected+' transcript'
    assert not routes._voice_ids(manifest['document'])
    imported = client.post('/project-bundles/import?allow_voices=true',content=response.content)
    assert imported.status_code == 200, imported.text
    with db.db_conn() as conn:
        imported_job = json.loads(conn.execute('SELECT job_data FROM dub_history WHERE id=?',(imported.json()['projectId'],)).fetchone()[0])
    assert imported_job['segments'][0]['profile_id'] == 'auto-seg:one'
    assert Path(imported_job['segment_clones']['one']['ref_audio']).read_bytes() == expected.encode()


def test_bundle_directory_rejects_symlink_escape(handoff, tmp_path):
    import uuid
    client, routes, _ = handoff
    identifier = str(uuid.uuid4())
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside/'project.vsproject').write_bytes(b'private')
    (routes._root()/identifier).symlink_to(outside, target_is_directory=True)
    assert client.get('/project-bundles/'+identifier).status_code == 400


@pytest.mark.parametrize('limited_by', ['age','count','bytes'])
def test_export_retention_preserves_imports_and_active_downloads(handoff, monkeypatch, limited_by):
    import uuid
    client, routes, _ = handoff
    now = routes.time.time()
    def entry(created, incoming=False):
        identifier = str(uuid.uuid4()); directory = routes._directory(identifier); directory.mkdir()
        (directory/'index.json').write_text(json.dumps({'id':identifier,'incoming':incoming,'createdAt':created}))
        (directory/'project.vsproject').write_bytes(b'12345678')
        return directory
    older = entry(now-10)
    latest = entry(now)
    imported = entry(0,True)
    if limited_by == 'age':
        monkeypatch.setattr(routes,'EXPORT_RETENTION_SECONDS',5)
    elif limited_by == 'count':
        monkeypatch.setattr(routes,'MAX_RETAINED_EXPORTS',1)
    else:
        monkeypatch.setattr(routes,'MAX_RETAINED_EXPORT_BYTES',8)
    # Hold a real response lease while the body is being sent. Both retention
    # scans and finally cleanup are exercised without relying on wall time.
    response = routes.download_project_bundle(older.name)
    async def send(message):
        if message['type'] == 'http.response.body':
            routes.list_project_bundles()
            assert older.exists() and imported.exists()
    async def receive():
        return {'type':'http.request'}
    asyncio.run(response({'type':'http','method':'GET','headers':[]},receive,send))
    assert imported.exists()
    assert not older.exists()
    assert routes._active_transfers == {}
    assert latest.exists()


def test_retention_ignores_unfinished_exports_and_imported_asset_directories(handoff):
    import uuid
    _, routes, _ = handoff
    unfinished = routes._directory(str(uuid.uuid4())); unfinished.mkdir()
    (unfinished/'project.vsproject').write_bytes(b'incomplete')
    malformed = routes._directory(str(uuid.uuid4())); malformed.mkdir()
    (malformed/'index.json').write_text('[]')
    routes.list_project_bundles()
    assert unfinished.exists() and malformed.exists()


@pytest.mark.parametrize('filename',['project.vsproject','result.json'])
def test_bundle_file_rejects_symlink_escape(handoff,tmp_path,filename):
    import uuid
    client,routes,_ = handoff
    directory = routes._directory(str(uuid.uuid4())); directory.mkdir()
    outside = tmp_path/'private.json'; outside.write_text('{"secret":true}')
    (directory/filename).symlink_to(outside)
    url = '/project-bundles/'+directory.name+('/document' if filename=='result.json' else '')
    assert client.get(url).status_code == 400


@pytest.mark.parametrize('index',[[],{}, {'createdAt':'yesterday'}, {'createdAt':None}, {'createdAt':float('nan')}])
def test_list_skips_malformed_index_before_sorting(handoff,index):
    import uuid
    client,routes,_ = handoff
    directory = routes._directory(str(uuid.uuid4())); directory.mkdir()
    (directory/'index.json').write_text(json.dumps(index))
    response = client.get('/project-bundles')
    assert response.status_code == 200
    assert response.json() == []
