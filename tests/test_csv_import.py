import csv
import io
from pathlib import Path
import pytest

import musicharbor.csv_import as csv_import
import musicharbor.store as store
from musicharbor.matching import score

EXAMPLE = Path(__file__).parent/'fixtures/exportify-example.csv'
URI = 'spotify:track:73UQ8oAuZNrLWyPb8TiAuO'


def make_csv(rows, headers=None, delimiter=','):
    stream=io.StringIO(newline='')
    writer=csv.writer(stream,delimiter=delimiter)
    writer.writerow(headers or ['Track URI','Track Name','Album Name','Artist Name(s)','Duration (ms)','Explicit'])
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def test_users_exact_exportify_example():
    parsed=csv_import.parse(EXAMPLE.read_bytes())
    assert not parsed['errors']
    assert len(parsed['tracks'])==len(parsed['recordings'])==1
    rec=next(iter(parsed['recordings'].values()))
    assert rec['title']=='God Driven'
    assert rec['artist']=='116, 1K Phew, Sam Rivera'
    assert rec['duration']==176.937
    assert rec['explicit'] is False
    assert rec['release_date']=='2026-07-31'
    assert rec['spotify_id']=='73UQ8oAuZNrLWyPb8TiAuO'
    assert rec['isrc'] is None
    assert rec['match_status']=='unmatched'
    assert 'added_by' not in rec and 'danceability' not in rec


@pytest.mark.parametrize('bom',[b'',b'\xef\xbb\xbf'])
@pytest.mark.parametrize('delimiter',[',',';','\t'])
def test_quoted_fields_unicode_and_separated_artists(bom,delimiter):
    payload=make_csv([[URI,'A song, "quoted"','An album\nwith a subtitle','Beyoncé;Guest',180500,'TRUE']],delimiter=delimiter)
    result=csv_import.parse(bom+payload)
    rec=next(iter(result['recordings'].values()))
    assert rec['title']=='A song, "quoted"'
    assert rec['album']=='An album\nwith a subtitle'
    assert rec['artist']=='Beyoncé, Guest'
    assert rec['explicit'] is True and rec['duration']==180.5


def test_old_exportify_headers_are_supported():
    parsed=csv_import.parse(make_csv([[URI,'Song','Artist',123000,'FALSE']],
        ['Track URI','Track Name','Artist Name(s)','Track Duration (ms)','Explicit?']))
    assert not parsed['errors']
    assert next(iter(parsed['recordings'].values()))['duration']==123


def test_missing_metadata_stays_unknown_and_needs_review():
    parsed=csv_import.parse(make_csv([['Song','Artist']],['Track Name','Artist Name(s)']))
    rec=next(iter(parsed['recordings'].values()))
    assert rec['duration'] is None and rec['explicit'] is None and rec['spotify_id'] is None
    match=score(rec,dict(title='Song',artist='Artist',duration=180,explicit=False))
    assert match['confidence']!='high'
    assert csv_import.preview(parsed)['missing_explicit']==1


def test_unknown_explicit_does_not_automatically_accept_a_version():
    reference=dict(title='Song',artist='Artist',duration=180,explicit=None)
    candidate=dict(reference,explicit=True)
    assert score(reference,candidate)['confidence']!='high'
    assert score(reference,candidate,{'clean_explicit_equivalent':True})['confidence']=='high'


def test_repeated_occurrences_preserve_order_without_double_counting_recording():
    other='spotify:track:'+'b'*22
    rows=[[URI,'First','Album','Artist',180000,'FALSE'],[other,'Second','Album','Artist',190000,'FALSE'],[URI,'First','Other album','Artist',180000,'FALSE']]
    parsed=csv_import.parse(make_csv(rows))
    ids=[t['recording_id'] for t in parsed['tracks']]
    assert len(ids)==3 and len(parsed['recordings'])==2
    assert ids[0]==ids[2] and ids[0]!=ids[1]
    assert parsed['tracks'][2]['source_album']=='Other album'


def test_same_title_without_identifier_is_not_silently_merged():
    parsed=csv_import.parse(make_csv([['Song','Artist'],['Song','Artist']],['Track Name','Artist Name(s)']))
    assert len(parsed['recordings'])==2


def test_conflicting_metadata_for_same_spotify_id_is_kept_separate():
    rows=[[URI,'Song','Album','Artist',180000,'FALSE'],[URI,'Song (Live)','Album','Artist',180000,'FALSE']]
    parsed=csv_import.parse(make_csv(rows))
    assert len(parsed['recordings'])==2 and parsed['warnings']


@pytest.mark.parametrize('value',['NaN','Infinity','-100','bad'])
def test_invalid_durations_block_import(value):
    parsed=csv_import.parse(make_csv([[URI,'Song','Album','Artist',value,'FALSE']]))
    assert not csv_import.preview(parsed)['can_import']
    with pytest.raises(ValueError): csv_import.build_project(parsed,'Name','us','playlist.csv')


def test_bad_boolean_and_missing_artist_are_visible_errors():
    parsed=csv_import.parse(make_csv([[URI,'Song','Album','Artist',180000,'maybe'],[URI,'Song','Album','',180000,'FALSE']]))
    assert len(parsed['errors'])==2
    assert parsed['errors'][0]['line']==2


def test_missing_required_columns_and_ambiguous_duration():
    with pytest.raises(ValueError): csv_import.parse(b'Name,Album\nSong,Album\n')
    parsed=csv_import.parse(b'Track Name,Artist Name(s),Duration\nSong,Artist,180000\n')
    assert parsed['errors']
    clock=csv_import.parse(b'Track Name,Artist Name(s),Duration\nSong,Artist,3:01\n')
    assert next(iter(clock['recordings'].values()))['duration']==181


def test_bad_quoting_and_empty_file():
    for payload in (b'',b'Track Name,Artist Name(s)\n"Unclosed,Artist\n'):
        with pytest.raises(ValueError): csv_import.parse(payload)


def test_blank_rows_and_utf16():
    text='Track Name,Artist Name(s)\r\nSong,Artist\r\n\r\n'
    parsed=csv_import.parse(text.encode('utf-16'))
    assert len(parsed['tracks'])==1 and parsed['blank_rows']==1


def test_preview_and_import_do_not_need_spotify(client,monkeypatch):
    import musicharbor.services as services
    async def forbidden(*args,**kwargs): raise AssertionError('CSV import must not call Spotify')
    monkeypatch.setattr(services,'spotify_token',forbidden)
    monkeypatch.setattr(services,'request',forbidden)
    payload=EXAMPLE.read_bytes()
    response=client.post('/api/import/csv/preview',content=payload,headers={'Content-Type':'text/csv'})
    assert response.status_code==200 and response.json()['can_import']
    assert store.projects()==[]
    response=client.post('/api/import/csv?name=My%20Playlist&storefront=ca&filename=export.csv',content=payload,headers={'Content-Type':'text/csv'})
    assert response.status_code==200
    p=store.get(response.json()['project'])
    assert p['name']=='My Playlist' and p['storefront']=='ca'
    assert p['source_type']=='exportify_csv' and p['source_url']==''
    assert p['source_filename']=='export.csv'
    assert store.setting('spotify_id') is None


def test_invalid_file_does_not_create_partial_project(client):
    response=client.post('/api/import/csv',content=b'Track Name,Artist Name(s)\nSong,\n')
    assert response.status_code==400 and store.projects()==[]


def test_uploaded_filename_is_metadata_not_a_path(client):
    response=client.post('/api/import/csv',params={'filename':'../../file.csv'},content=EXAMPLE.read_bytes())
    p=store.get(response.json()['project'])
    assert p['source_filename']=='file.csv'


def test_csv_import_rejects_bad_storefront_and_missing_csrf(client):
    assert client.post('/api/import/csv?storefront=bad',content=EXAMPLE.read_bytes()).status_code==400
    assert client.post('/api/import/csv/preview',content=EXAMPLE.read_bytes(),headers={'X-App-Token':''}).status_code==403


def test_backup_of_recordings_with_unknown_duration_restores(client):
    uploaded=client.post('/api/import/csv',content=b'Track Name,Artist Name(s)\nSong,Artist\n').json()
    backup=client.get(f'/api/projects/{uploaded["project"]}/backup').json()
    restored=client.post('/api/restore',json=backup)
    assert restored.status_code==200
    assert next(iter(restored.json()['recordings'].values()))['duration'] is None


def test_upload_limit_is_enforced_before_project_creation(client,monkeypatch):
    monkeypatch.setattr(csv_import,'MAX_BYTES',20)
    response=client.post('/api/import/csv',content=EXAMPLE.read_bytes())
    assert response.status_code==400 and store.projects()==[]


def test_row_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(csv_import,'MAX_ROWS',1)
    with pytest.raises(ValueError):
        csv_import.parse(make_csv([['Song','Artist'],['Next','Artist']],['Track Name','Artist Name(s)']))


def test_formatted_text_is_metadata_not_executable_markup():
    name='<img src=x onerror=alert(1)>'
    parsed=csv_import.parse(make_csv([[name,'Artist']],['Track Name','Artist Name(s)']))
    assert parsed['rows'][0]['title']==name
    # The API returns metadata as JSON; the interface escapes all displayed values.


def test_unknown_duration_csv_reaches_optimizer_without_spotify(client):
    uploaded=client.post('/api/import/csv',content=b'Track Name,Artist Name(s)\nSong,Artist\n').json()
    p=store.get(uploaded['project']);rid=next(iter(p['recordings']))
    p['releases']['track:fixture']=dict(id='track:fixture',price=1.29,currency='USD',coverage=[rid],owned=False,excluded=False)
    store.put(p)
    result=client.post(f'/api/projects/{p["id"]}/plan',json={'strategy':'cheapest'})
    assert result.status_code==200
    assert result.json()['complete'] and result.json()['cost']==1.29
