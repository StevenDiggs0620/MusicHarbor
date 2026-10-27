"""Feature regression cases, authored without execution during implementation."""
import asyncio
import copy
import json
from datetime import datetime, timezone, timedelta
import pytest
import app
import store
import services
import portable
import planning
import retention
import library_index
from export_policy import ExportOptions, select_files
from matching import owned_ids
from conftest import project_with_options, recording


def test_export_omissions_keep_positions_and_actionable_reasons(tmp_path):
    p=project_with_options()
    p['recordings']['a']['included']=False
    p['recordings']['c']['ownership_override']=True
    lines,skipped,omissions=app.export_lines(p,ExportOptions(),include_report=True)
    assert lines==[] and skipped==4
    assert [item['position'] for item in omissions]==[1,2,3,4]
    assert [item['action'] for item in omissions]==['songs','plan','songs','library']
    path=tmp_path/'song.mp3';path.touch()
    p['local_files']=[dict(path=str(path),recording_id='c',status='matched')]
    lines,skipped,omissions=app.export_lines(p,ExportOptions(slashes='macos'),include_report=True)
    assert lines==[str(path)] and skipped==3
    assert app.export_lines(p,ExportOptions(slashes='macos'))==(lines,skipped)


def test_export_prefers_format_folder_then_quality_and_path(tmp_path):
    p=project_with_options()
    files=[]
    for name,bitrate in [('b.mp3',320000),('a.mp3',128000),('song.flac',900000)]:
        path=tmp_path/name;path.touch()
        files.append(dict(id=name,path=str(path),recording_id='a',status='matched',bitrate=bitrate))
    p['local_files']=files
    assert select_files(p,ExportOptions())[0]['a']['id']=='song.flac'
    assert select_files(p,ExportOptions(preferred_format='mp3'))[0]['a']['id']=='b.mp3'
    p['export_file_overrides']={'a':str(tmp_path/'a.mp3')}
    assert select_files(p,ExportOptions())[0]['a']['id']=='a.mp3'
    (tmp_path/'a.mp3').unlink()
    with pytest.raises(ValueError,match='preferred export file'): select_files(p,ExportOptions())


def test_clear_release_ownership_preserves_other_sources(client):
    p=project_with_options();p['releases']['album'].update(owned=True,partial=['a'])
    p['recordings']['b']['ownership_override']=True;store.put(p)
    path=f"/api/projects/{p['id']}/releases/album"
    assert client.patch(path,json={'owned':False}).status_code==200
    assert owned_ids(store.get(p['id']))=={'a','b'}
    assert client.patch(path,json={'clear_ownership':True}).status_code==200
    assert owned_ids(store.get(p['id']))=={'b'}


def test_project_only_backup_omits_unrelated_library_and_paths():
    p=project_with_options()
    p['recordings']['unrelated']=recording('unrelated')
    p['local_files']=[{'path':'/private/music/file.mp3'}]
    p['library_folders']=['/private/music'];p['export_file_overrides']={'a':'/private/music/file.mp3'}
    p['exports']=[dict(created=store.now(),count=1,skipped=0,options={'path_from':'/private/music'})]
    result=portable.project_only(p)
    assert 'unrelated' not in result['recordings']
    assert '/private/music' not in json.dumps(result)
    assert p['library_folders']==['/private/music']


def test_full_library_restore_is_additive_and_requires_rescan(isolated_store):
    p=project_with_options()
    path=isolated_store/'song.mp3';path.touch()
    p['local_files']=[dict(id='file',path=str(path),title='a',artist='Artist',album='Album',
        duration=180,identity_id='a',recording_id='a',status='matched',fingerprint=[0,1])]
    store.save_project(p,library=True)
    blob=json.loads(portable.encode('library',p['id']))
    with store.connection() as c:
        c.execute('DELETE FROM library_files');c.execute('DELETE FROM library_recordings');c.execute('DELETE FROM library_keys')
    result=portable.restore_library(blob)
    assert result['restored_projects']==1 and result['restored_files']==1
    assert len(store.projects())==2
    file=store.library()['files'][0]
    assert file['status']=='missing' and 'fingerprint' not in file
    again=portable.restore_library(blob)
    assert again['restored_files']==0 and len(store.library()['files'])==1


def test_priority_queue_and_grouped_view_have_separate_order():
    from optimizer import calculate
    from purchase_order import purchase_groups
    p=project_with_options()
    p['releases']['album']['price']=30
    plan=calculate(p,strategy='songs-per-dollar')
    groups=purchase_groups(p,plan['release_ids'])
    assert plan['release_ids'][0]!='album'
    assert set(plan['release_ids'])=={rid for group in groups for rid in group['release_ids']}


def test_scoped_load_and_shared_storage(isolated_store):
    shared=store.new_project();shared['recordings']={}
    for rid,title in [('wanted','Wanted song'),('unrelated','Other song')]:
        path=isolated_store/(rid+'.mp3');path.touch()
        rec=recording(rid,title);rec.update(library_identity=True,included=False)
        shared['recordings'][rid]=rec
        shared['local_files'].append(dict(id=rid,path=str(path),identity_id=rid,recording_id=rid,status='matched'))
    store.save_library(shared)
    p=store.new_project();p['recordings']['wanted']=recording('wanted','Wanted song')
    p['tracks']=[dict(id='entry',recording_id='wanted')];store.put(p)
    loaded=store.get(p['id']);assert 'unrelated' not in loaded['recordings']
    store.put(loaded)
    with store.connection() as c: saved=json.loads(c.execute('SELECT payload FROM projects WHERE id=?',(p['id'],)).fetchone()[0])
    assert saved['local_files']==[]
    assert 'candidates' not in saved['recordings']['wanted']
    assert library_index.page(0,1)['next_offset']==1
    assert library_index.page(1,1)['next_offset'] is None


def test_plan_cache_key_tracks_ownership_and_options():
    p=project_with_options()
    _,snapshot,first=planning.prepare(p,{'strategy':'cheapest'},None)
    p['recordings']['a']['ownership_override']=True
    assert planning.prepare(p,{'strategy':'cheapest'},None)[2]!=first
    assert 'candidates' not in snapshot['recordings']['a']


def test_retention_preserves_active_jobs_and_user_decisions(isolated_store):
    p=project_with_options();p['exports']=[dict(created=store.now(),count=i,skipped=0) for i in range(4)]
    p['recordings']['a']['ownership_override']=True
    old=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
    p['price_history']=[dict(release_id='album',price=1,currency='USD',storefront='us',checked=old)]
    store.put(p);store.save_setting('retention',dict(job_days=1,price_days=1,export_count=2))
    store.put_job('done',dict(project=p['id'],status='done',created=old))
    store.put_job('active',dict(project=p['id'],status='running',created=old))
    retention.cleanup()
    result=store.get(p['id'])
    assert len(result['exports'])==2 and result['price_history']==[]
    assert result['recordings']['a']['ownership_override'] is True
    assert [j['id'] for j in store.jobs(p['id'])]==['active']


def test_spotify_changed_snapshot_retries_without_mixing_pages(monkeypatch):
    snapshots=iter(['old','new','stable','stable'])
    calls=[]
    async def request(method,url,**kw):
        calls.append(url)
        if url.endswith('/items'): return dict(items=[{'id':'one'}],total=1,next=None)
        return dict(snapshot_id=next(snapshots),tracks={'total':1})
    monkeypatch.setattr(services,'request',request)
    meta,items=asyncio.run(services.stable_playlist('id',{},'us',lambda *args:None))
    assert meta['snapshot_id']=='stable' and len(items)==1
    assert sum(url.endswith('/items') for url in calls)==2


def test_application_token_reused_until_configuration_changes(isolated_store,monkeypatch):
    store.save_setting('spotify_id','client');store.save_setting('spotify_secret','secret')
    services.invalidate_authorization();calls=[]
    async def request(*args,**kw):
        calls.append(kw);return {'access_token':str(len(calls)),'expires_in':3600}
    monkeypatch.setattr(services,'request',request)
    async def scenario():
        assert await services._spotify_token()=='1'
        assert await services._spotify_token()=='1'
        store.save_setting('spotify_secret','new-secret')
        assert await services._spotify_token()=='2'
    asyncio.run(scenario())


def test_repeated_price_observation_does_not_grow_history(isolated_store):
    p=store.new_project()
    song=dict(trackId=1,collectionId=2,trackName='Song',artistName='Artist',trackPrice=1,currency='USD')
    services.product(p,song,[song],True);services.product(p,song,[song],True)
    assert len(p['price_history'])==1
    song['trackPrice']=2;services.product(p,song,[song],True)
    assert len(p['price_history'])==2


def test_cancelling_queued_plan_releases_reservation(client,monkeypatch):
    p=project_with_options();store.put(p)
    async def wait(*args): await asyncio.Event().wait()
    monkeypatch.setattr(planning,'run',wait)
    result=client.post(f"/api/projects/{p['id']}/plan/start",json={'strategy':'cheapest'})
    jid=result.json()['job']
    assert client.post(f'/api/jobs/{jid}/cancel',json={}).status_code==200
    import time
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        job=client.get(f'/api/jobs/{jid}').json()
        if job['status']=='cancelled': break
        time.sleep(.01)
    assert job['status']=='cancelled' and p['id'] not in app.BUSY
