import asyncio
import copy

import musicharbor.services as services
import musicharbor.store as store
from conftest import recording


def test_refresh_finds_new_album_without_changing_identity(isolated_store, monkeypatch):
    p = store.new_project()
    selected = dict(kind='song', trackId=11, collectionId=1, trackName='Song',
                    artistName='Artist', trackTimeMillis=180000, trackExplicitness='notExplicit',
                    trackPrice=1.29, currency='USD', collectionName='Song - Single')
    album_song = dict(selected, trackId=22, collectionId=2, collectionName='New Album')
    live = dict(album_song, trackId=33, collectionId=3, trackName='Song (Live)')
    rejected = dict(album_song, trackId=44, collectionId=4)
    rec = recording('r', 'Song')
    rec.update(selected=selected, candidates=[{'song': selected}], rejected=['44'])
    p['recordings']['r'] = rec
    p['tracks'] = [dict(id='entry', recording_id='r')]
    before = copy.deepcopy(rec)
    calls = []

    async def apple(endpoint, params, refresh=False):
        calls.append((endpoint, params.copy(), refresh))
        assert refresh is True
        if endpoint == 'search':
            return {'results': [album_song, live, rejected]}
        results = []
        for cid in params['id'].split(','):
            song = selected if cid == '1' else album_song
            results.extend([dict(wrapperType='collection', collectionId=int(cid),
                                 collectionName=song['collectionName'], artistName='Artist',
                                 trackCount=1, collectionPrice=5, currency='USD'), song])
        return {'results': results}

    monkeypatch.setattr(services, 'apple', apple)
    asyncio.run(services.refresh_prices(p, lambda _: None))
    assert rec == before
    assert 'album:2' in p['releases']
    assert p['releases']['album:2']['coverage'] == ['r']
    assert 'album:3' not in p['releases'] and 'album:4' not in p['releases']
    assert sum(endpoint == 'search' for endpoint, _, _ in calls) == 1
