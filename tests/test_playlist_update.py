import asyncio
import copy
import time

import pytest

import app
import services
import store
from conftest import project_with_options, recording
from identity import attach_library, playlist_ids
from playlist_update import merge_playlist


def incoming(*titles):
    recordings={}; tracks=[]
    for title in titles:
        rid=store.uid()
        recordings[rid]=recording(rid,title=title)
        recordings[rid].update(spotify_id=title,match_status='unmatched')
        tracks.append(dict(id=store.uid(),recording_id=rid,source_metadata=dict(recordings[rid])))
    return dict(recordings=recordings,tracks=tracks)


def titles(p):
    return [p['recordings'][t['recording_id']]['title'] for t in p['tracks']]


def test_add_is_multiset_union_and_preserves_catalog():
    p=project_with_options(); old=copy.deepcopy(p)
    result=merge_playlist(p,incoming('a','a','a','d'), 'add')
    assert titles(p)==['a','b','a','c','a','d']
    assert result['new_recordings']==1 and result['reused_recordings']==1
    assert p['releases']==old['releases']
    assert p['tracks'][:4]==old['tracks']
    merge_playlist(p,incoming('a','a','a','d'), 'add')
    assert len(p['tracks'])==6


def test_replace_retains_archived_matches_and_readding_reuses_them():
    p=project_with_options()
    p['recordings']['b'].update(included=False,required=True,rejected=['99'],ownership_override=True,
                                selected={'trackId':12},candidates=[{'song':{'trackId':12}}])
    before=copy.deepcopy(p['recordings']['b'])
    merge_playlist(p,incoming('c','a','c'),'replace')
    assert titles(p)==['c','a','c'] and 'b' not in playlist_ids(p)
    assert all(p['recordings']['b'][k]==v for k,v in before.items())
    result=merge_playlist(p,incoming('b'),'replace')
    assert titles(p)==['b'] and result['new_recordings']==0
    assert p['tracks'][0]['recording_id']=='b'
    assert p['recordings']['b']['selected']=={'trackId':12}
    assert p['recordings']['b']['ownership_override'] is True


@pytest.mark.parametrize('field,value',[('title','a (Live)'),('explicit',True),('duration',220),('isrc','OTHER')])
def test_conflicting_source_metadata_is_not_reused(field,value):
    p=project_with_options(); p['recordings']['a']['isrc']='ORIGINAL'
    new=incoming('a'); rec=next(iter(new['recordings'].values()))
    rec['isrc']='ORIGINAL';rec[field]=value
    result=merge_playlist(p,new,'replace')
    assert result['new_recordings']==1
    assert p['tracks'][0]['recording_id']!='a'


def test_reuse_aliases_after_canonical_consolidation():
    p=project_with_options()
    p['recordings']['a']['source_identities']=[dict(p['recordings']['a'],spotify_id='alternate')]
    new=incoming('a'); next(iter(new['recordings'].values()))['spotify_id']='alternate'
    assert merge_playlist(p,new,'replace')['new_recordings']==0


def test_catalog_update_does_not_search_known_records_or_reload_complete_albums(isolated_store,monkeypatch):
    p=project_with_options()
    song=dict(trackId=123,collectionId=10,trackName='a',artistName='Artist',trackTimeMillis=180000,trackExplicitness='notExplicit')
    p['recordings']['a'].update(selected=song,catalog_searched_at='previous')
    p['recordings']['b'].update(catalog_searched_at='previous',match_status='unmatched')
    p['recordings']['c'].update(catalog_searched_at='previous',match_status='unmatched')
    p['releases']['album:10']=dict(id='album:10',track_count=1,songs=[song],coverage=['a'])
    merge_playlist(p,incoming('a','b','d'),'replace')
    searched=[]
    async def search(term,country): searched.append(term);return []
    async def forbidden(*args,**kwargs): pytest.fail('Existing album should not be requested')
    monkeypatch.setattr(services,'search',search);monkeypatch.setattr(services,'apple',forbidden)
    asyncio.run(services.discover(p,lambda _:None,reuse_existing=True))
    assert searched==['Artist d']
    searched.clear()
    asyncio.run(services.discover(p,lambda _:None,reuse_existing=True))
    assert searched==[]


def wait_job(client,jid):
    for _ in range(100):
        job=app.JOBS[jid]
        if job['status'] not in ('queued','running'): return job
        time.sleep(.01)
    pytest.fail('Update did not finish')


def test_csv_update_endpoints_preserve_project_and_reject_invalid_rows(client,monkeypatch):
    p=project_with_options();store.put(p)
    calls=[]
    async def discover(p,progress,reuse_existing=False): calls.append(reuse_existing);return 'Done'
    monkeypatch.setattr(services,'discover',discover)
    path=f'/api/projects/{p["id"]}/playlist/csv'
    csv=b'Track Name,Artist Name(s),Track URI,Duration (ms),Explicit\na,Artist,,180000,FALSE\nnew,Artist,,180000,FALSE\n'
    response=client.post(path+'?mode=replace&filename=update.csv',content=csv)
    assert response.status_code==200
    assert wait_job(client,response.json()['job'])['status']=='done'
    saved=store.get(p['id'])
    assert titles(saved)==['a','new']
    assert saved['name']==p['name'] and saved['releases']==p['releases']
    assert len(saved['recordings'])>=3 and calls==[True]
    before=copy.deepcopy(saved['tracks'])
    bad=client.post(path+'?mode=replace',content=b'Track Name,Artist Name(s)\n,Artist\n')
    assert bad.status_code==400
    assert store.get(p['id'])['tracks']==before
    assert client.post(path+'?mode=wrong',content=csv).status_code==422
    app.BUSY.add(p['id'])
    try: assert client.post(path,content=csv).status_code==400
    finally: app.BUSY.discard(p['id'])


def test_spotify_update_add_and_replace(client,monkeypatch):
    p=project_with_options();store.put(p)
    async def token(): return 'test'
    async def request(method,url,**kwargs):
        if url.endswith('/items'):
            def song(title): return dict(type='track',id=title,name=title,artists=[dict(name='Artist')],album=dict(name='Album'),duration_ms=180000,explicit=False)
            return dict(items=[dict(item=song('a')),dict(item=song('d'))],next=None,total=2)
        return dict(name='Incoming playlist',snapshot_id='stable',tracks={'total':2})
    async def discover(p,progress,reuse_existing=False): assert reuse_existing;return 'Done'
    monkeypatch.setattr(services,'spotify_token',token);monkeypatch.setattr(services,'request',request)
    monkeypatch.setattr(services,'discover',discover)
    path=f'/api/projects/{p["id"]}/playlist/spotify'
    for mode,expected in [('add',['a','b','a','c','d']),('replace',['a','d'])]:
        result=client.post(path,json=dict(mode=mode,url='spotify:playlist:'+'a'*22))
        assert wait_job(client,result.json()['job'])['status']=='done'
        saved=store.get(p['id'])
        assert titles(saved)==expected and saved['name']==p['name']
        assert saved['releases']==p['releases']
        assert 'b' in saved['recordings']


def test_failed_spotify_fetch_does_not_replace_playlist(client,monkeypatch):
    p=project_with_options();store.put(p)
    async def fail(): raise ValueError('Spotify unavailable')
    monkeypatch.setattr(services,'spotify_token',fail)
    result=client.post(f'/api/projects/{p["id"]}/playlist/spotify',json=dict(mode='replace',url='spotify:playlist:'+'a'*22))
    assert wait_job(client,result.json()['job'])['status']=='error'
    assert store.get(p['id'])['tracks']==p['tracks']


def test_new_playlist_member_can_reuse_local_identity():
    p=project_with_options()
    local=recording('local',title='local song')
    local.update(spotify_id='local song',included=False,library_identity=True,source_type='local_file')
    p['recordings']['local']=local
    merge_playlist(p,incoming('local song'),'replace')
    assert p['tracks'][0]['recording_id']=='local'
    assert p['recordings']['local']['included'] is True


def test_update_saves_completed_searches_on_later_failure(isolated_store,monkeypatch):
    p=project_with_options();store.put(p)
    async def fail_later(p,progress,reuse_existing=False):
        p['recordings']['a']['catalog_searched_at']='finished search'
        raise ValueError('Later release lookup failed')
    monkeypatch.setattr(services,'discover',fail_later)
    args=dict(source='csv',mode='replace',incoming=incoming('a'),filename='update.csv',summary={})
    with pytest.raises(ValueError,match='Later release'):
        asyncio.run(services.update_and_discover(p,args,lambda _:None))
    saved=store.get(p['id'])
    assert titles(saved)==['a']
    assert saved['recordings']['a']['catalog_searched_at']=='finished search'


def test_shared_library_membership_does_not_exclude_song_in_another_project():
    p=store.new_project()
    rec=recording('local',title='local song')
    rec.update(spotify_id='local song',included=False,library_identity=True,playlist_seen=True)
    attach_library(p,dict(files=[],recordings={'local':rec},folders=[]))
    merge_playlist(p,incoming('local song'),'replace')
    assert p['tracks'][0]['recording_id']=='local'
    assert p['recordings']['local']['included'] is True
