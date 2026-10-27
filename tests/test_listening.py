import asyncio
import copy

import musicharbor.listening as listening
from musicharbor.purchase_order import purchase_groups
from conftest import project_with_options


def test_counts_window_duplicates_and_ambiguous_versions():
    p=project_with_options(); now=10_000_000
    config=dict(provider='listenbrainz',username='test')
    history=dict(config,synced_at=now,listens=[
        dict(ts=now-1,title='a',artist='Artist'),
        dict(ts=now-listening.WINDOW-1,title='a',artist='Artist'),
        dict(ts=now-1,title='a (Live)',artist='Artist'),
        dict(ts=now-1,title='b',artist='Artist')])
    before=copy.deepcopy(p)
    counts=listening.play_counts(p,config,history,now)
    assert counts=={'a':1,'b':1,'c':0}  # two playlist appearances never double a listen
    assert p==before
    p['recordings']['clean']=dict(p['recordings']['a'],id='clean',explicit=True)
    p['tracks'].append(dict(recording_id='clean'))
    assert listening.play_counts(p,config,history,now)['a']==0
    assert listening.play_counts(p,{},history,now) is None
    assert listening.play_counts(p,dict(config,username='other'),history,now) is None


def test_album_ties_use_plays_before_price():
    p=project_with_options()
    p['releases']={}
    for rid,artist,price in [('a','Zebra',.99),('b','Alpha',9),('c','Beta',1)]:
        p['releases'][rid]=dict(id=rid,kind='album',coverage=[rid],name=rid,artist=artist,price=price)
    ids=list(p['releases'])
    assert [g['release_ids'][0] for g in purchase_groups(p,ids)]==['a','c','b']
    groups=purchase_groups(p,ids,{'a':100,'b':5,'c':5})
    assert [g['release_ids'][0] for g in groups]==['a','c','b']
    assert groups[0]['play_count']==100


def test_custom_window_and_incomplete_cache():
    p=project_with_options(); now=20_000_000
    config=dict(provider='listenbrainz',username='test',days=7)
    history=dict(provider='listenbrainz',username='test',synced_at=now,listens=[
        dict(ts=now-86400,title='a',artist='Artist'),
        dict(ts=now-8*86400,title='a',artist='Artist')])
    assert listening.play_counts(p,config,history,now)['a']==1
    assert listening.play_counts(p,dict(config,days=30),history,now)['a']==2
    assert listening.play_counts(p,dict(config,days=180),history,now) is None
    assert listening.play_counts(p,dict(config,days=180),dict(history,days=180),now)['a']==2


def test_window_validation_and_saved_setting(client,monkeypatch):
    import musicharbor.store as store
    monkeypatch.setattr(listening,'start_sync',listening.status)
    for days in (0,3651,1.5):
        assert client.post('/api/listening/connect',json=dict(username='test',days=days)).status_code==422
    response=client.post('/api/listening/connect',json=dict(username='test',days=14))
    assert response.status_code==200
    assert response.json()['days']==14
    assert store.setting('listening_config')['days']==14


def test_lastfm_pages_exact_window_and_ignore_now_playing(isolated_store,monkeypatch):
    monkeypatch.setattr(listening.time,'time',lambda:10_000_000)
    calls=[]
    async def fetch(client,url,params,headers=None):
        calls.append(params)
        return {'recenttracks':{'@attr':{'totalPages':'2'},'track':[
            {'name':'Playing','@attr':{'nowplaying':'true'}},
            {'name':'Song','artist':{'#text':'Artist'},'album':{'#text':'Album'},'date':{'uts':'9999999'}}]}}
    monkeypatch.setattr(listening,'fetch_json',fetch)
    result=asyncio.run(listening.download(dict(provider='lastfm',username='x',days=14),lambda _:None,None))
    assert len(result['listens'])==2
    assert [c['page'] for c in calls]==[1,2]
    assert calls[0]['from']==10_000_000-14*86400-1
    assert result['days']==14
    assert calls[0]['to']==10_000_001


def test_listenbrainz_paginates_until_cutoff(isolated_store,monkeypatch):
    now=10_000_000;monkeypatch.setattr(listening.time,'time',lambda:now)
    calls=[]
    async def fetch(client,url,params,headers=None):
        calls.append(params)
        ts=now-1 if len(calls)==1 else now-7*86400-1
        return {'payload':{'listens':[dict(listened_at=ts,track_metadata=dict(track_name='Song',artist_name='Artist'))]}}
    monkeypatch.setattr(listening,'fetch_json',fetch)
    result=asyncio.run(listening.download(dict(provider='listenbrainz',username='x',days=7),lambda _:None,None))
    assert len(result['listens'])==1
    assert result['days']==7
    assert calls[1]['max_ts']==now-1


def test_sync_failure_keeps_complete_snapshot_and_hides_credentials(client,monkeypatch):
    import musicharbor.store as store
    store.save_setting('listening_config',dict(provider='lastfm',username='x'))
    store.save_setting('lastfm_key','private-value')
    previous=dict(provider='lastfm',username='x',synced_at=123,listens=[])
    store.save_setting('listening_history',previous)
    async def fail(*args): raise ValueError('Service unavailable')
    monkeypatch.setattr(listening,'download',fail)
    async def check():
        listening.start_sync()
        await listening.TASK
    asyncio.run(check())
    assert store.setting('listening_history')==previous
    jobs=client.get('/api/jobs').json()
    job=next(j for j in jobs if j['id']==listening.JOB['id'])
    assert job['status']=='error'
    assert client.post('/api/jobs/'+job['id']+'/dismiss').status_code==200
    assert not any(j['id']==job['id'] for j in client.get('/api/jobs').json())
    assert 'private-value' not in client.get('/api/settings').text
    assert client.post('/api/listening/disconnect').status_code==200
    assert store.setting('listening_history')=={}
