import json
import pytest
import store
import app
import services
from conftest import project_with_options


def test_project_isolation_duplicate_and_delete(client):
    first=project_with_options();second=project_with_options()
    store.put(first);store.put(second)
    response=client.patch(f'/api/projects/{first["id"]}/recordings/a',json={'ownership_override':True})
    assert response.status_code==200
    assert store.get(first['id'])['recordings']['a']['ownership_override'] is True
    assert store.get(second['id'])['recordings']['a']['ownership_override'] is None
    duplicate=client.post(f'/api/projects/{first["id"]}/duplicate',json={}).json()
    assert duplicate['id']!=first['id']
    assert duplicate['recordings']['a']['ownership_override'] is True
    assert client.delete(f'/api/projects/{first["id"]}').status_code==200
    assert store.get(second['id'])


def test_export_paths_order_duplicates_and_missing(client,isolated_store):
    p=project_with_options(); path=isolated_store/'song-a.mp3';path.write_bytes(b'fixture')
    p['recordings']['a']['owned']=True
    p['local_files']=[dict(id='file',path=str(path),recording_id='a',status='matched',duration=180)]
    store.put(p)
    response=client.post(f'/api/projects/{p["id"]}/export?format=m3u8&extinf=true&slashes=macos')
    assert response.status_code==200
    assert response.text.count(str(path))==2
    assert response.text.startswith('#EXTM3U\n#EXTINF:180,Artist - a\n')
    assert store.get(p['id'])['exports'][-1]['count']==2
    path.unlink()
    assert client.post(f'/api/projects/{p["id"]}/export').status_code==400


def test_export_excludes_skipped_owned_recording(client,isolated_store):
    p=project_with_options();path=isolated_store/'file.flac';path.touch()
    p['recordings']['a'].update(owned=True,included=False)
    p['local_files']=[dict(id='file',path=str(path),recording_id='a',status='matched')]
    store.put(p)
    assert client.get(f'/api/projects/{p["id"]}/export-preview').json()['count']==0


def test_secret_is_not_returned_or_exported(client):
    secret='test-private-secret'
    assert client.post('/api/settings',json={'spotify_id':'example','spotify_secret':secret}).status_code==200
    assert secret not in client.get('/api/settings').text
    p=store.put(project_with_options())
    assert secret not in client.get(f'/api/projects/{p["id"]}/backup').text


def test_csrf_origin_and_host_checks(client):
    assert client.post('/api/projects',json={},headers={'X-App-Token':''}).status_code==403
    assert client.post('/api/projects',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/settings',headers={'Host':'evil.example'}).status_code==403


def test_bad_backup_and_valid_restore(client):
    assert client.post('/api/restore',json={'format':'other'}).status_code==400
    p=store.put(project_with_options())
    blob=client.get(f'/api/projects/{p["id"]}/backup').json()
    restored=client.post('/api/restore',json=blob)
    assert restored.status_code==200
    assert restored.json()['id']!=p['id']
    assert restored.json()['local_files']==[]


def test_oauth_state_is_single_use_and_expires(isolated_store):
    import asyncio
    services.AUTH_PENDING.clear()
    with pytest.raises(ValueError): asyncio.run(services.oauth_complete('code','invalid'))
    store.save_setting('spotify_id','example')
    url=services.oauth_start()
    assert 'code_challenge_method=S256' in url
    assert 'playlist-read-private' in url


def test_playlist_parser_rejects_untrusted_urls():
    pid='a'*22
    assert services.playlist_id(f'https://open.spotify.com/playlist/{pid}?si=abc')==pid
    assert services.playlist_id(f'spotify:playlist:{pid}')==pid
    for value in ('https://evil.example/playlist/'+pid,'/playlist/'+pid,'not a playlist'):
        with pytest.raises(ValueError): services.playlist_id(value)


def test_busy_project_blocks_mutation(client):
    p=store.put(project_with_options());app.BUSY.add(p['id'])
    try:
        assert client.patch(f'/api/projects/{p["id"]}/recordings/a',json={'owned':True}).status_code==400
    finally: app.BUSY.discard(p['id'])


def test_reimport_preserves_order_and_decisions(isolated_store,monkeypatch):
    import asyncio
    p=project_with_options();p['source_url']='spotify:playlist:'+'a'*22
    p['recordings']['a']['owned']=True
    async def token(): return 'token'
    async def request(method,url,**kwargs):
        if url.endswith('/items'):
            track=dict(type='track',id='a',name='a',artists=[{'name':'Artist'}],album={'name':'Album'},duration_ms=180000,explicit=False)
            return {'items':[{'item':track},{'track':track}],'next':None,'total':2}
        return {'name':'Updated playlist','snapshot_id':'stable','tracks':{'total':2}}
    monkeypatch.setattr(services,'spotify_token',token);monkeypatch.setattr(services,'request',request)
    asyncio.run(services.import_playlist(p,lambda message:None))
    assert len(p['tracks'])==2 and {t['recording_id'] for t in p['tracks']}=={'a'}
    assert len(p['recordings'])==3  # Removed recordings remain catalogued for future updates.
    assert p['recordings']['a']['owned']


def test_export_format_path_options_and_preview(client, isolated_store):
    p=project_with_options()
    path=isolated_store/'Beyoncé.mp3'; path.write_bytes(b'fixture')
    p['recordings']['a']['owned']=True
    p['local_files']=[dict(id='f',path=str(path),recording_id='a',status='matched',duration=180)]
    store.put(p)
    url=f'/api/projects/{p["id"]}'
    default=client.post(url+'/export')
    assert default.status_code==200
    assert 'playlist-owned.m3u"' in default.headers['content-disposition']
    assert '#EXT' not in default.text
    assert default.text.splitlines()==[str(path).replace('/',chr(92))]*2
    params=dict(format='m3u8',extinf='true',slashes='windows',custom_path='true',path_from=str(isolated_store),path_to='iTunes')
    preview=client.get(url+'/export-preview',params=params).json()
    exported=client.post(url+'/export',params=params)
    assert preview['count']==2
    assert preview['text']==exported.text
    assert exported.text.count('iTunes'+chr(92)+'Beyoncé.mp3')==2
    assert exported.text.count('#EXTINF:')==2
    assert 'playlist-owned.m3u8"' in exported.headers['content-disposition']
    params.update(slashes='macos',extinf='false')
    assert client.post(url+'/export',params=params).text=='iTunes/Beyoncé.mp3\n'*2
    params['path_from']=''
    assert client.post(url+'/export',params=params).status_code==400
