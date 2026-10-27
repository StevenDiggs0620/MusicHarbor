import asyncio
from types import SimpleNamespace
import pytest
import musicharbor.csv_import as csv_import
import musicharbor.services as services
import musicharbor.store as store
from musicharbor.identity import decide, consolidate, summary
from musicharbor.matching import rec_owned, rebuild_coverage, score
from musicharbor.optimizer import calculate
from conftest import recording, project_with_options
from test_csv_import import make_csv


def listing(tid=1, album='Original Album', count=10, **kw):
    return dict(trackId=tid, collectionId=tid, trackName='Song', artistName='Artist',
                collectionName=album, trackCount=count, trackTimeMillis=180000,
                trackExplicitness='notExplicit', trackPrice=1.29,
                collectionPrice=7.99, currency='USD', **kw)


def source(**kw):
    return dict(title='Song', artist='Artist', duration=180, explicit=False, **kw)


def test_505_entries_500_recordings_and_visible_failures():
    rows = [[f'spotify:track:{i:022d}',f'Song {i}','Album','Artist',180000,'FALSE'] for i in range(500)]
    parsed = csv_import.parse(make_csv(rows + rows[:5]))
    preview = csv_import.preview(parsed)
    assert (preview['rows_read'],preview['count'],preview['recording_count'],preview['repeated_entries']) == (505,505,500,5)
    assert len({t['id'] for t in parsed['tracks']}) == 505
    bad = csv_import.preview(csv_import.parse(make_csv(rows + [['','Bad','','',180000,'FALSE']])))
    assert bad['rows_read'] == 501 and bad['count'] == 500 and bad['error_count'] == 1
    assert not bad['can_import'] and bad['errors'][0]['line'] == 502


def test_equivalent_release_listings_are_automatically_resolved():
    songs = [listing(1,'Song - Single',1), listing(2), listing(3,'Original Album (Deluxe)',15), listing(4,'Greatest Hits',20)]
    result = decide(source(), songs)
    assert result['resolution_state'] == 'HIGH_CONFIDENCE'
    assert result['selected'] and len(result['candidates']) == 4
    p = store.new_project()
    r = recording('canonical','Song'); r.update(result)
    p['recordings']['canonical'] = r
    p['tracks'] = [dict(id='entry',recording_id='canonical')]
    for song in songs: services.product(p,song,[song],True)
    rebuild_coverage(p,{})
    assert all(rel['coverage'] == ['canonical'] for rel in p['releases'].values())
    assert calculate(p)['release_ids'] == ['track:2']
    assert calculate(p,'best-value',budget=2)['release_ids'] == ['track:2']


@pytest.mark.parametrize('suffix',['Live','Acoustic','Club Remix','Radio Edit','2026 Remaster','Rerecorded Version'])
def test_alternate_recording_never_automatically_accepted(suffix):
    candidate = listing(); candidate['trackName'] += f' ({suffix})'
    assert decide(source(),[candidate])['selected'] is None


def test_clean_explicit_and_ambiguous_duration():
    explicit = listing(); explicit['trackExplicitness'] = 'explicit'
    assert decide(source(),[explicit])['selected'] is None
    a,b = listing(1),listing(2)
    a['trackTimeMillis']=178000; b['trackTimeMillis']=182000
    result = decide(source(),[a,b])
    assert result['resolution_state'] == 'NEEDS_REVIEW' and result['selected'] is None
    assert 'competing' in result['match_evidence']['reasons'][-1]


def test_same_identifier_with_conflicting_version_or_duration_requires_review():
    a = source(isrc='USABC1234567')
    assert score(a,dict(a,title='Song (Live)'))['confidence'] != 'high'
    assert score(a,dict(a,duration=200))['confidence'] != 'high'


def fake_audio(monkeypatch, *, explicit='2', isrc=''):
    def audio(path,easy=True):
        tags = {'title':['Song'], 'artist':['Artist'], 'album':['Original Album'],
                'albumartist':['Artist'], 'discnumber':['1'], 'tracknumber':['3']}
        if isrc: tags['isrc'] = [isrc]
        if not easy: tags={'rtng':[int(explicit)]} if explicit else {}
        return SimpleNamespace(tags=tags,info=SimpleNamespace(length=180.321))
    monkeypatch.setattr('mutagen.File', audio)
    async def search(term,country): return [listing()]
    monkeypatch.setattr(services,'search',search)


def test_local_file_independent_owned_and_reused_across_projects(isolated_store,monkeypatch):
    fake_audio(monkeypatch)
    path=isolated_store/'song.m4a'; path.touch()
    p=store.new_project('Empty playlist')
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    f=p['local_files'][0]; rid=f['recording_id']
    assert f['status']=='matched' and rid
    assert not p['tracks'] and rec_owned(p,rid)
    assert calculate(p)['remaining']==0
    assert f['album_artist']=='Artist' and f['duration']==180.321
    q=store.new_project('Different playlist')
    r=recording('playlist','Song'); r.update(decide(source(),[listing()]))
    q['recordings']['playlist']=r
    q['tracks']=[dict(id='first',recording_id='playlist'),dict(id='second',recording_id='playlist')]
    store.put(q)
    loaded=store.get(q['id'])
    assert len({t['recording_id'] for t in loaded['tracks']})==1
    playlist_rid=loaded['tracks'][0]['recording_id']
    assert rec_owned(loaded,playlist_rid)
    assert calculate(loaded)['remaining']==0
    path.unlink()
    assert not rec_owned(store.get(q['id']),playlist_rid)


def test_unknown_local_explicitness_stays_unresolved_without_blocking_plan(isolated_store,monkeypatch):
    fake_audio(monkeypatch,explicit='')
    (isolated_store/'song.m4a').touch()
    p=project_with_options()
    for rid,r in p['recordings'].items():
        r['selected']=dict(listing(),trackId=rid,trackName=r['title'])
    for rel in p['releases'].values():
        rel['songs']=[p['recordings'][rid]['selected'] for rid in rel['coverage']]
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    assert p['local_files'][0]['recording_id'] is None
    assert p['local_files'][0]['status']=='review'
    plan=calculate(p)
    assert plan['complete'] and plan['cost']==3 and plan['remaining']==3


def test_embedded_identifier_owns_recording_without_store_listing(isolated_store,monkeypatch):
    fake_audio(monkeypatch,explicit='',isrc='USABC1234567')
    (isolated_store/'song.flac').touch()
    async def empty(*args): return []
    monkeypatch.setattr(services,'search',empty)
    p=store.new_project()
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    rid=p['local_files'][0]['recording_id']
    assert rid and rec_owned(p,rid)
    assert p['recordings'][rid]['resolution_state']=='EXACT'


def test_catalog_failure_preserves_scanned_files(isolated_store,monkeypatch):
    fake_audio(monkeypatch)
    (isolated_store/'song.m4a').touch()
    async def unavailable(*args): raise ValueError('Service unavailable')
    monkeypatch.setattr(services,'search',unavailable)
    p=store.new_project()
    message=asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    assert 'interrupted' in message
    assert len(store.library()['files'])==1


def test_duplicate_sources_consolidate_without_losing_occurrences():
    p=store.new_project()
    for rid in ('a','b'):
        r=recording(rid,'Song'); r.update(decide(source(),[listing()]))
        p['recordings'][rid]=r
        p['tracks'].append(dict(id=rid,recording_id=rid))
    consolidate(p)
    assert summary(p)['duplicate_appearances']==1
    assert len(p['tracks'])==2 and len(p['recordings'])==1


@pytest.mark.parametrize('needed,expected_cost,album',[ (1,1.29,False),(4,5.16,False),(7,7.99,True)])
def test_global_album_vs_individual_tracks(needed,expected_cost,album):
    p=store.new_project()
    songs=[]
    for i in range(needed):
        rid=str(i); s=listing(i+10); s.update(collectionId=100,trackName='Song '+rid)
        songs.append(s)
        r=recording(rid,'Song '+rid); r.update(selected=s)
        p['recordings'][rid]=r; p['tracks'].append(dict(id=rid,recording_id=rid))
    release=dict(songs[0],collectionId=100)
    services.product(p,release,songs)
    for s in songs: services.product(p,s,[s],True)
    rebuild_coverage(p,{})
    plan=calculate(p)
    assert plan['complete'] and plan['optimal'] and plan['cost']==expected_cost
    assert ('album:100' in plan['release_ids']) == album


def test_single_lower_price_beats_album_preference():
    p=store.new_project(); r=recording('song','Song'); r.update(selected=listing())
    p['recordings']['song']=r; p['tracks']=[dict(id='entry',recording_id='song')]
    a,b=listing(1),listing(2,'Song - Single',1); b['trackPrice']=1.28
    for s in (a,b): services.product(p,s,[s],True)
    rebuild_coverage(p,{})
    assert calculate(p)['release_ids']==['track:2']


def test_manual_local_correction_does_not_change_playlist(client,isolated_store):
    p=store.new_project(); path=isolated_store/'song.m4a'; path.touch()
    studio=listing(); live=listing(99); live['trackName']='Song (Live)'
    r=recording('studio','Song'); r.update(selected=studio,candidates=[dict(song=studio,**score(source(),source()))])
    p['recordings']['studio']=r; p['tracks']=[dict(id='entry',recording_id='studio')]
    p['local_files']=[dict(id='file',path=str(path),title='Song',artist='Artist',duration=180,explicit=False,
                            recording_id='studio',identity_id='studio',status='matched',
                            candidates=[dict(song=live,score=0,reasons=['Live version'])])]
    store.put(p)
    response=client.post(f'/api/projects/{p["id"]}/files/file/match',json={'track_id':'99','action':'confirm'})
    assert response.status_code==200
    result=store.get(p['id'])
    assert result['tracks'][0]['recording_id']=='studio'
    assert not rec_owned(result,'studio')
    assert result['local_files'][0]['recording_id']!='studio'
    assert result['recordings'][result['local_files'][0]['recording_id']]['selected']['trackId']==99


def test_playlist_override_does_not_reidentify_owned_file(client,isolated_store):
    p=store.new_project(); path=isolated_store/'song.m4a'; path.touch()
    studio=listing(); live=listing(99); live['trackName']='Song (Live)'
    r=recording('studio','Song'); r.update(selected=studio,candidates=[dict(song=live,score=0,reasons=['Live version'])])
    p['recordings']['studio']=r; p['tracks']=[dict(id='entry',recording_id='studio')]
    p['local_files']=[dict(id='file',path=str(path),recording_id='studio',identity_id='studio',status='matched')]
    store.put(p)
    response=client.post(f'/api/projects/{p["id"]}/recordings/studio/match',json={'track_id':'99','action':'confirm'})
    assert response.status_code==200
    result=store.get(p['id'])
    new_id=result['tracks'][0]['recording_id']
    assert new_id!='studio' and not rec_owned(result,new_id)
    assert result['local_files'][0]['recording_id']=='studio'
    assert result['recordings']['studio']['selected']['trackId']==1


def test_library_canonical_id_survives_project_reuse(isolated_store,monkeypatch):
    fake_audio(monkeypatch); (isolated_store/'song.m4a').touch()
    p=store.new_project()
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    canonical=p['local_files'][0]['recording_id']
    for i in range(2):
        q=store.new_project()
        r=recording('new','Song'); r.update(decide(source(),[listing()]))
        q['recordings']['new']=r; q['tracks']=[dict(id='entry',recording_id='new')]
        store.put(q)
        q=store.get(q['id'])
        assert q['tracks'][0]['recording_id']==canonical
        store.save_library(q)


def test_import_automatically_starts_resolution(client,monkeypatch):
    import time
    async def search(*args): return [listing()]
    async def lookup(*args): return None
    monkeypatch.setattr(services,'search',search)
    monkeypatch.setattr(services,'lookup_release',lookup)
    response=client.post('/api/import/csv',content=make_csv([['spotify:track:'+'a'*22,'Song','Album','Artist',180000,'FALSE']])).json()
    assert response['job']
    for _ in range(100):
        job=client.get('/api/jobs/'+response['job']).json()
        if job['status'] not in ('running','queued'): break
        time.sleep(.01)
    assert job['status']=='done'
    p=store.get(response['project'])
    assert next(iter(p['recordings'].values()))['resolution_state']=='HIGH_CONFIDENCE'
    assert calculate(p)['cost']==1.29


def test_unreadable_local_file_is_preserved(isolated_store,monkeypatch):
    (isolated_store/'broken.mp3').touch()
    monkeypatch.setattr('mutagen.File',lambda *args,**kw:None)
    p=store.new_project()
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    assert p['local_files'][0]['status']=='unreadable'
    assert p['local_files'][0]['error']
    assert calculate(p)['complete']


def test_invalid_embedded_identifier_is_not_accepted(isolated_store,monkeypatch):
    fake_audio(monkeypatch,explicit='',isrc='not-an-isrc')
    (isolated_store/'song.m4a').touch()
    p=store.new_project()
    asyncio.run(services.scan_and_resolve(p,str(isolated_store),lambda _:None))
    assert p['local_files'][0]['recording_id'] is None


def test_main_album_beats_deluxe_and_other_artist_album():
    p=store.new_project(); r=recording('song','Song'); r.update(selected=listing(),album='Original Album')
    p['recordings']['song']=r; p['tracks']=[dict(id='entry',recording_id='song')]
    songs=[listing(10,'Other Artist Album'),listing(11,'Original Album (Deluxe)',15),listing(12,'Original Album')]
    for s in songs: services.product(p,s,[s],True)
    rebuild_coverage(p,{})
    assert calculate(p)['release_ids']==['track:12']
    p['releases']['track:12']['excluded']=True
    assert calculate(p)['release_ids']==['track:11']


def test_embedded_itunes_id_resolves_unknown_explicitness():
    local=source(itunes_track_id='1'); local['explicit']=None
    result=decide(local,[listing()])
    assert result['resolution_state']=='EXACT'
    assert 'Embedded iTunes track ID agrees' in result['match_evidence']['reasons']
    live=listing(); live['trackName']='Song (Live)'
    assert decide(local,[live])['selected'] is None
