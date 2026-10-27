"""Regression cases for the static review fixes. Not run as part of the repair."""
import asyncio
import copy
import json
import threading
from urllib.parse import parse_qs, urlparse

import pytest
import app
import musicharbor.backup_schema as backup_schema
import musicharbor.csv_import as csv_import
import musicharbor.identity as identity
import musicharbor.listening as listening
import musicharbor.services as services
import musicharbor.store as store
from musicharbor.matching import comparison_title, rebuild_coverage, score
from musicharbor.playlist_update import merge_playlist


def song(tid=1, title='Song', **changes):
    return dict(dict(trackId=tid,collectionId=10,kind='song',trackName=title,
                     artistName='Artist',collectionName='Album',trackTimeMillis=180000,
                     trackExplicitness='notExplicit',trackPrice=1,currency='USD'),**changes)


def project():
    p=store.new_project()
    p['recordings']['r']=dict(id='r',title='Song',artist='Artist',album='Album',duration=180,
        explicit=False,included=True,required=False,owned=False,ownership_override=None,
        match_status='confirmed',selected=song(),candidates=[],rejected=[])
    p['tracks']=[dict(id='entry',recording_id='r')]
    services.product(p,song(),[song()],True)
    rebuild_coverage(p,{})
    return p


def test_merge_preserves_only_explicit_override():
    p=project()
    p['recordings']['second']=dict(copy.deepcopy(p['recordings']['r']),id='second',ownership_override=False)
    p['tracks'].append(dict(id='second-entry',recording_id='second'))
    mapping=identity.consolidate(p)
    assert mapping['second']=='r'
    assert p['recordings']['r']['ownership_override'] is False


def test_resolution_and_live_remaster_preferences_agree():
    source=dict(title='Song (Live)',artist='Artist',duration=180,explicit=False)
    listing=song(title='Song (Live 2026 Remastered)',trackExplicitness='explicit')
    prefs=dict(remasters_equivalent=True,clean_explicit_equivalent=True)
    assert identity.decide(source,[listing],prefs=prefs)['selected']==listing
    assert identity.decide(source,[listing])['selected'] is None
    assert score(dict(source,title='Song (Clean)'),dict(source,title='Song (Explicit)',explicit=True),prefs)['confidence']=='high'


def test_partial_artist_name_requires_review():
    a=dict(title='Song',artist='Simon & Garfunkel',duration=180,explicit=False)
    assert score(a,dict(a,artist='Simon'))['confidence']!='high'


def test_remaster_normalization_preserves_years_in_song_titles():
    prefs={'remasters_equivalent':True}
    assert comparison_title('1999',prefs)=='1999'
    assert comparison_title('1999 (2019 Remastered)',prefs)=='1999'
    assert comparison_title('Song (Remastered 2019)',prefs)=='song'


def test_repeated_identifier_free_update_is_idempotent():
    parsed=csv_import.parse(b'\nTrack Name,Artist Name(s)\nSong,Artist\nSong,Artist\n')
    p=csv_import.build_project(parsed,'Name','us','playlist.csv')
    for _ in range(2):
        incoming=csv_import.parse(b'Track Name,Artist Name(s)\nSong,Artist\nSong,Artist\n')
        merge_playlist(p,incoming,'add')
    assert len(p['tracks'])==2
    assert len(p['recordings'])==2


def test_recording_only_change_is_shared_and_existing_project_updates(isolated_store):
    p=project(); path=isolated_store/'song.mp3';path.touch()
    p['local_files']=[dict(id='f',path=str(path),identity_id='r',recording_id='r',status='matched')]
    store.save_project(p,library=True)
    other=copy.deepcopy(p);other['id']=store.uid();store.put(other)
    loaded=store.get(p['id'])
    files=copy.deepcopy(loaded['local_files'])
    loaded['recordings']['r']['rejected']=['99']
    store.save_project(loaded,library=True)
    assert loaded['local_files']==files
    assert store.get(other['id'])['recordings']['r']['rejected']==['99']


def test_identifier_free_update_after_canonical_consolidation():
    data=b'Track Name,Artist Name(s),Duration (ms),Explicit\nSong,Artist,180000,FALSE\nSong,Artist,180000,FALSE\n'
    p=csv_import.build_project(csv_import.parse(data),'Name','us','playlist.csv')
    for rec in p['recordings'].values(): rec.update(selected=song(),match_status='high')
    identity.consolidate(p)
    assert len(p['recordings'])==1
    merge_playlist(p,csv_import.parse(data),'add')
    assert len(p['tracks'])==2


def test_shared_conflict_does_not_commit_project_half(isolated_store):
    p=project();path=isolated_store/'song.mp3';path.touch()
    p['local_files']=[dict(id='f',path=str(path),identity_id='r',recording_id='r',status='matched')]
    store.save_project(p,library=True)
    stale=store.get(p['id']);fresh=store.get(p['id'])
    fresh['local_files'][0]['manual']=True
    store.save_project(fresh,library=True)
    stale['name']='Must not commit';stale['local_files'][0]['manual']=False
    with pytest.raises(ValueError,match='another project'):
        store.save_project(stale,library=True)
    assert store.get(p['id'])['name']!=stale['name']


def test_recovery_checkpoint_rebuilds_coverage(isolated_store):
    p=project()
    services.product(p,song(),[song()],True)
    p['releases']['track:1']['coverage']=[]
    services.save_checkpoint(p)
    assert store.get(p['id'])['releases']['track:1']['coverage']==['r']


def test_partial_refresh_keeps_complete_evidence():
    p=project();songs=[song(),song(2,'Other')]
    album=dict(wrapperType='collection',collectionId=10,collectionName='Album',artistName='Artist',trackCount=2,collectionPrice=5,currency='USD')
    services.apply_release(p,10,dict(results=[album,*songs]))
    services.apply_release(p,10,dict(results=[dict(album,collectionPrice=6),songs[0]]),True)
    rel=p['releases']['album:10']
    assert len(rel['songs'])==2 and rel['price']==6
    assert rel['tracklist_refresh_incomplete']


def test_restore_normalizes_duration_and_distrusts_forged_coverage(isolated_store):
    p=project();p['recordings']['r'].update(duration='180',selected=None,match_status='unmatched')
    restored=app.restore_project(backup_schema.encode(p))
    assert restored['recordings']['r']['duration']==180
    assert restored['releases']['track:1']['coverage']==[]


@pytest.mark.parametrize('change',[
    dict(selected=[]),dict(candidates=[dict(song=song(),score='<button>')]),
    dict(duration='NaN'),dict(resolution_state='invented'),dict(owned={}),
])
def test_restore_rejects_invalid_nested_recording(change):
    p=project();p['recordings']['r'].update(change)
    with pytest.raises(ValueError):
        backup_schema.validate(dict(format='playlist-purchaser',version=2,project=p))


def test_backup_over_old_recording_limit_round_trips():
    p=store.new_project()
    rec=project()['recordings']['r']
    p['recordings']={str(i):dict(rec,id=str(i),selected=None) for i in range(10001)}
    blob=json.loads(backup_schema.encode(p))
    assert len(backup_schema.validate(blob)['recordings'])==10001


def test_job_creation_failure_releases_reservation(isolated_store,monkeypatch):
    p=store.put(project())
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr(store,'put_job',fail)
    with pytest.raises(OSError): asyncio.run(app.start_job(p['id'],services.discover))
    assert p['id'] not in app.BUSY


def test_listening_start_failure_clears_running(isolated_store,monkeypatch):
    store.save_setting('listening_config',dict(provider='listenbrainz',username='name'))
    monkeypatch.setattr(listening,'STATE',dict(running=False,error=None,message='',fetched=0))
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr(store,'put_job',fail)
    with pytest.raises(OSError): listening.start_sync()
    assert not listening.STATE['running']


def test_known_mbid_conflict_does_not_get_listening_credit():
    p=project();p['recordings']['r']['musicbrainz_id']='known'
    config=dict(provider='listenbrainz',username='name',days=1)
    history=dict(config,synced_at=1000,listens=[dict(ts=999,title='Song',artist='Artist',mbid='different')])
    assert listening.play_counts(p,config,history,1000)=={'r':0}


def test_oauth_completion_after_disconnect_is_rejected(isolated_store,monkeypatch):
    store.save_setting('spotify_id','client')
    state=parse_qs(urlparse(services.oauth_start()).query)['state'][0]
    async def request(*args,**kwargs):
        services.invalidate_authorization()
        return dict(access_token='must-not-save',expires_in=3600)
    monkeypatch.setattr(services,'request',request)
    with pytest.raises(ValueError,match='changed'):
        asyncio.run(services.oauth_complete('code',state))
    assert not store.setting('spotify_token',{})


def test_scan_checks_cooperative_cancellation_before_reading(isolated_store):
    (isolated_store/'song.mp3').touch()
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(services.ScanCancelled):
        services.scan_library(store.new_project(),str(isolated_store),lambda _:None,cancelled)
