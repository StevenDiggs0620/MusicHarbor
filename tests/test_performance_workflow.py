import asyncio
import copy
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import musicharbor.app as app
import musicharbor.services as services
import musicharbor.store as store
import musicharbor.matching as matching
from musicharbor.progress import JobProgress, report
from musicharbor.purchase_order import purchase_groups
from conftest import recording, project_with_options


def run(coro): return asyncio.run(coro)


def listing(cid,number=1,title='Song'):
    return dict(kind='song',trackId=int(cid)*100+number,collectionId=int(cid),trackName=title,
                artistName='Artist',collectionName=f'Album {cid}',trackNumber=number,discNumber=1,
                trackTimeMillis=180000,trackExplicitness='notExplicit',trackPrice=1.29,currency='USD')


def collection(cid,count=2):
    return dict(wrapperType='collection',collectionId=int(cid),collectionName=f'Album {cid}',
                artistName='Artist',trackCount=count,collectionPrice=7.99,currency='USD')


def wait_job(client,jid):
    for _ in range(200):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] not in ('running','queued'): return job
        time.sleep(.01)
    pytest.fail('Job did not finish')


def test_performance_settings_roundtrip_and_limits(client):
    assert client.get('/api/settings').json()['performance']==dict(api_concurrency=3,background_jobs=2)
    payload=dict(performance=dict(api_concurrency=4,background_jobs=1))
    assert client.post('/api/settings',json=payload).status_code==200
    assert client.get('/api/settings').json()['performance']==payload['performance']
    for perf in (dict(api_concurrency=0),dict(api_concurrency=7),dict(background_jobs=0),dict(background_jobs=5)):
        assert client.post('/api/settings',json={'performance':perf}).status_code==422


def test_parallel_is_bounded_and_reports_completed_work(isolated_store):
    store.save_setting('performance',{'api_concurrency':3})
    async def scenario():
        active=0; peak=0
        job=dict(status='running',stages=[]); progress=JobProgress(job)
        async def worker(item):
            nonlocal active,peak
            active+=1; peak=max(peak,active)
            await asyncio.sleep(.002)
            active-=1
        await services.parallel(range(10),worker,progress,'search','Searching')
        assert peak==3
        assert job['stages'][0]['completed']==10 and job['stages'][0]['percent']==100
    run(scenario())


def test_shared_network_cap_and_pacing(isolated_store,monkeypatch):
    async def scenario():
        clock=[100.0]; started=[]; gate=asyncio.Event()
        async def delay(seconds):
            clock[0]+=seconds
            await asyncio.sleep(0)
        monkeypatch.setattr(services,'time',SimpleNamespace(monotonic=lambda:clock[0],time=time.time))
        monkeypatch.setattr(services,'wait_delay',delay)
        state=services.network()
        async def operation():
            async with services.apple_slot(state):
                started.append(clock[0]); await gate.wait()
        tasks=[asyncio.create_task(operation()) for _ in range(6)]
        for _ in range(10): await asyncio.sleep(0)
        assert len(started)==3
        gate.set(); await asyncio.gather(*tasks)
        assert all(b-a>=3.09 for a,b in zip(started,started[1:]))
        await services.close_network()
    run(scenario())


def test_cooldown_extended_while_waiting_is_respected(isolated_store,monkeypatch):
    async def scenario():
        clock=[0.0]; waits=[]
        state=dict(gate=asyncio.Semaphore(1),pace=asyncio.Lock(),last=0,cooldown=0)
        async def delay(seconds):
            waits.append(seconds);clock[0]+=seconds
            if len(waits)==1: state['cooldown']=10
        monkeypatch.setattr(services,'time',SimpleNamespace(monotonic=lambda:clock[0]))
        monkeypatch.setattr(services,'wait_delay',delay)
        async with services.apple_slot(state): assert clock[0]==10
        assert len(waits)==2
    run(scenario())


def test_duplicate_requests_share_one_fetch_then_cache(isolated_store,monkeypatch):
    calls=[]
    async def fake(*args,**kwargs):
        calls.append(kwargs); await asyncio.sleep(.005);return {'results':[]}
    monkeypatch.setattr(services,'request',fake)
    async def scenario():
        await asyncio.gather(*(services.apple('search',{'term':'Song'}) for _ in range(5)))
        await services.apple('search',{'term':'Song'})
        assert len(calls)==1
        await services.close_network()
    run(scenario())


def test_release_batches_partition_cache_and_progress(isolated_store,monkeypatch):
    calls=[]
    async def fake(endpoint,params,refresh=False):
        calls.append(params['id']);results=[]
        for cid in params['id'].split(','):
            results.extend([collection(cid),listing(cid,1),listing(cid,2)])
        return {'results':results}
    monkeypatch.setattr(services,'apple',fake)
    async def scenario():
        p=store.new_project(); job=dict(status='running',stages=[])
        loaded=await services.read_releases(p,map(str,range(1,11)),JobProgress(job))
        assert len(calls)==2 and len(loaded)==20
        assert job['stages'][0]['completed']==10
        assert all(len(p['releases'][f'album:{cid}']['songs'])==2 for cid in range(1,11))
        calls.clear()
        await services.read_releases(p,map(str,range(1,11)),JobProgress(job))
        assert not calls
    run(scenario())


def test_incomplete_batch_falls_back_to_individual(isolated_store,monkeypatch):
    calls=[]
    async def fake(endpoint,params,refresh=False):
        ids=params['id'];calls.append(ids)
        if ',' in ids: return {'results':[collection('1'),listing('1')]}
        return {'results':[collection(ids),listing(ids,1),listing(ids,2)]}
    monkeypatch.setattr(services,'apple',fake)
    p=store.new_project()
    run(services.read_releases(p,['1','2'],lambda _:None))
    assert calls==['1,2','1','2']
    assert all(len(r['songs'])==2 for r in p['releases'].values() if r['id'].startswith('album:'))


def test_refresh_missing_parent_still_refreshes_individual_track(isolated_store,monkeypatch):
    p=store.new_project();s=listing('1')
    services.product(p,collection('1'),[s]);services.product(p,s,[s],True)
    calls=[]
    async def fake(endpoint,params,refresh=False):
        calls.append(params['id'])
        return {'results':[]} if params['id']=='1' else {'results':[dict(s,trackPrice=.99)]}
    monkeypatch.setattr(services,'apple',fake)
    run(services.refresh_prices(p,lambda _:None))
    assert calls==['1','101']
    assert p['releases']['album:1']['price'] is None
    assert p['releases']['track:101']['price']==.99


def test_refresh_complete_parent_does_not_refetch_tracks(isolated_store,monkeypatch):
    p=store.new_project();s=listing('1')
    services.product(p,collection('1',1),[s]);services.product(p,s,[s],True)
    calls=[]
    async def fake(endpoint,params,refresh=False):
        calls.append(params['id']);return {'results':[collection('1',1),s]}
    monkeypatch.setattr(services,'apple',fake)
    run(services.refresh_prices(p,lambda _:None))
    assert calls==['1']


def test_coverage_index_matches_previous_algorithm_and_avoids_cartesian_work(monkeypatch):
    p=store.new_project()
    for i in range(100):
        rid=str(i);song=listing(i+1,title='Song '+rid)
        r=recording(rid,'Song '+rid);r['selected']=song
        p['recordings'][rid]=r
        services.product(p,song,[song,dict(song,trackId=song['trackId']+100000)],True)
    p['releases']['versions']=dict(id='versions',songs=[dict(listing(1),trackName='Song 0 (Live)'),dict(listing(1),trackName='Song 0',trackExplicitness='explicit')])
    expected={}
    for rel in p['releases'].values():
        expected[rel['id']]=[rid for rid,r in p['recordings'].items() if any(
            str(song['trackId'])==str(r['selected']['trackId']) or matching.score(matching.song_data(r['selected']),matching.song_data(song))['confidence']=='high'
            for song in rel['songs'])]
    calls=[0]; original=matching.score
    def counted(*args,**kwargs): calls[0]+=1;return original(*args,**kwargs)
    monkeypatch.setattr(matching,'score',counted)
    matching.rebuild_coverage(p,{})
    assert {rid:r['coverage'] for rid,r in p['releases'].items()}==expected
    assert calls[0]<300


def test_confirmation_saves_before_background_release_lookup(client,monkeypatch):
    p=store.new_project();r=recording('song','Song');s=listing('1')
    r.update(match_status='medium',candidates=[{'song':s}],selected=None)
    p['recordings']['song']=r;p['tracks']=[dict(id='entry',recording_id='song')];store.put(p)
    release_started=threading.Event(); release_gate=threading.Event()
    async def slow(*args):
        release_started.set()
        while not release_gate.is_set(): await asyncio.sleep(.005)
    monkeypatch.setattr(services,'lookup_release',slow)
    base=f'/api/projects/{p["id"]}/recordings/song'
    result=client.post(base+'/match',json={'track_id':'101','action':'confirm'})
    assert result.status_code==200 and not release_started.is_set()
    assert store.get(p['id'])['recordings']['song']['match_status']=='confirmed'
    job=client.post(base+'/release',json={}).json()['job']
    assert release_started.wait(1)
    assert client.get('/api/health').status_code==200
    assert client.get('/api/jobs/'+job).json()['status']=='running'
    release_gate.set()
    assert wait_job(client,job)['status']=='done'


def test_background_limit_queue_cancel_and_history(client,monkeypatch):
    assert client.post('/api/settings',json={'performance':{'background_jobs':1}}).status_code==200
    gate=threading.Event();started=[]
    async def work(p,progress):
        started.append(p['id']);report(progress,'search','Searching',1,4)
        while not gate.is_set(): await asyncio.sleep(.005)
        report(progress,'search','Searching',4,4);return 'Finished sample work'
    monkeypatch.setattr(services,'discover',work)
    projects=[store.put(store.new_project()) for _ in range(2)]
    first=client.post(f'/api/projects/{projects[0]["id"]}/discover').json()['job']
    second=client.post(f'/api/projects/{projects[1]["id"]}/discover').json()['job']
    for _ in range(100):
        if started:break
        time.sleep(.005)
    assert len(started)==1
    assert client.get('/api/jobs/'+second).json()['status']=='queued'
    assert client.post('/api/jobs/'+first+'/dismiss').status_code==400
    assert client.post('/api/jobs/'+second+'/cancel').status_code==200
    assert wait_job(client,second)['status']=='cancelled'
    gate.set();assert wait_job(client,first)['status']=='done'
    app.JOBS.clear()  # Simulate completed jobs recovered from persisted storage.
    history=client.get(f'/api/projects/{projects[0]["id"]}/jobs').json()
    assert history[0]['id']==first and history[0]['status']=='done'
    assert client.post('/api/jobs/'+first+'/dismiss').status_code==200
    assert client.get(f'/api/projects/{projects[0]["id"]}/jobs').json()==[]


def test_stage_percent_and_pending_stage():
    job=dict(status='running',stages=[dict(id='search',status='pending'),dict(id='releases',status='pending')])
    report(JobProgress(job),'search','Searching',23,100)
    assert job['stages'][0]['percent']==23
    assert job['stages'][0]['status']=='running'
    assert job['stages'][1]['status']=='pending' and 'percent' not in job['stages'][1]


def test_cancelled_blocking_work_drains_before_return(isolated_store):
    async def scenario():
        entered=threading.Event();release=threading.Event();finished=[]
        def work(): entered.set();release.wait(1);finished.append(True)
        task=asyncio.create_task(services.run_blocking(work))
        while not entered.is_set():await asyncio.sleep(.001)
        task.cancel();await asyncio.sleep(.005)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert finished
    run(scenario())


def test_shared_library_stale_job_cannot_undo_newer_file_decision(isolated_store):
    path=isolated_store/'song.m4a';path.touch()
    p=store.new_project();p['recordings']['song']=recording('song')
    p['local_files']=[dict(id='file',path=str(path),recording_id='song',identity_id='song',status='matched')]
    store.save_library(p);store.put(p)
    old=store.get(p['id']);new=store.get(p['id'])
    new['local_files'][0]['manual']=True;store.save_library(new)
    old['local_files'][0]['status']='review'
    with pytest.raises(ValueError,match='changed in another project'):
        store.save_library(old)
    assert store.library()['files'][0]['manual'] is True
    assert store.library()['files'][0]['status']=='matched'


def test_purchase_display_all_requested_tie_breakers():
    p=store.new_project()
    p['tracks']=[dict(id=str(i),recording_id=str(i)) for i in range(12)]
    def full(key,kind,coverage,count,price):
        p['releases'][key]=dict(id=key,kind=kind,purchase_type='release',coverage=coverage,
                                track_count=count,price=price,artist='Artist',name=key)
    full('album-low-coverage','album',['0'],30,1)
    full('album-short','album',['0','1'],8,1)
    full('album-expensive','deluxe album',['0','1'],12,9)
    full('album-cheap','album',['0','1'],12,7)
    full('ep-short','ep',['0','1'],3,1)
    full('ep-long','ep',['0','1'],6,3)
    def track(key,cid,number,price=1.29,artist='Artist',date='2020-01-01',disc=1):
        p['releases'][key]=dict(id=key,kind='individual song',purchase_type='track',release_id=cid,
            release_name=cid,coverage=[str(number-1)],track_number=number,disc_number=disc,price=price,artist=artist,date=date)
    track('a3','A',3);track('a1','A',1);track('a2','A',2)
    track('b2','B',2);track('b1','B',1)
    track('single-expensive','C',1,1.99,'Aaron')
    track('single-cheap','D',1,.99,'Zebra')
    track('single-artist-z','E',1,1.29,'Zebra')
    track('single-new','F',1,1.29,'Aaron','2022-01-01')
    track('single-old-track2','G',2,1.29,'Aaron','2019-01-01')
    track('single-old-track1','H',1,1.29,'Aaron','2019-01-01')
    ids=list(reversed(p['releases'])); original=list(ids)
    groups=purchase_groups(p,ids)
    assert groups[0]['release_ids']==['a1','a2','a3']
    assert [g['release_ids'][0] for g in groups[1:7]]==['album-short','ep-short','b1','ep-long','album-cheap','album-expensive']
    assert groups[3]['release_ids']==['b1','b2']
    assert [g['release_ids'][0] for g in groups[7:]]==['single-cheap','album-low-coverage','single-new','single-old-track2','single-old-track1','single-artist-z','single-expensive']
    assert ids==original
    assert sorted(rid for g in groups for rid in g['release_ids'])==sorted(ids)


def test_purchase_order_uses_legacy_song_metadata_and_disc_numbers():
    p=store.new_project()
    for disc,number in ((2,1),(1,5),(1,2)):
        key=f'track:{disc}-{number}'
        p['releases'][key]=dict(id=key,kind='individual song',price=1.29,artist='Artist',songs=[dict(collectionId=7,collectionName='Album',discNumber=disc,trackNumber=number)])
    group=purchase_groups(p,list(p['releases']))[0]
    assert group['release_ids']==['track:1-2','track:1-5','track:2-1']


def test_release_type_does_not_override_price():
    p=store.new_project()
    p['tracks']=[dict(recording_id='r')]
    p['releases']={
        'album:1':dict(id='album:1',name='Standalone',release_kind='single',release_id='1',price=.99,coverage=['r']),
        'album:2':dict(id='album:2',name='Full EP',release_kind='ep',release_id='2',price=4,coverage=['r']),
        'album:3':dict(id='album:3',name='Studio Album',release_kind='album',release_id='3'),
        'track:3':dict(id='track:3',release_id='3',price=1.29,coverage=['r']),
        'track:4':dict(id='track:4',release_id='4',release_kind='single',release_name='Another Single',price=.79,coverage=['r']),
    }
    groups=purchase_groups(p,['album:1','track:4','track:3','album:2'])
    assert [g['release_ids'] for g in groups]==[['track:4'],['album:1'],['track:3'],['album:2']]
    assert groups[2]['label']=='Studio Album — 1 individual track'
