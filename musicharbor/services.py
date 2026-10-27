"""Spotify authorization, catalog requests, and local metadata scanning."""
import asyncio
import base64
import hashlib
import json
import secrets
import time
import re
import weakref
import threading
import copy
from contextlib import asynccontextmanager
from musicharbor.progress import report
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
import musicharbor.store as store
from musicharbor.matching import score, song_data, rebuild_coverage
from musicharbor.identity import decide, consolidate, sync_files, playlist_ids, summary

REDIRECT = 'http://127.0.0.1:8765/api/oauth/callback'
AUTH_PENDING = {}
AUTH_GENERATION = 0
APP_TOKEN = {}
TOKEN_LOCK = asyncio.Lock()
NETWORK = weakref.WeakKeyDictionary()
wait_delay = asyncio.sleep


def performance():
    saved=store.setting('performance', {})
    return dict(api_concurrency=max(1,min(6,int(saved.get('api_concurrency',3)))),
                background_jobs=max(1,min(4,int(saved.get('background_jobs',2)))))


def network():
    loop=asyncio.get_running_loop()
    if loop not in NETWORK:
        NETWORK[loop]=dict(client=httpx.AsyncClient(timeout=30), gate=asyncio.Semaphore(performance()['api_concurrency']),
                           pace=asyncio.Lock(), last=-float('inf'), cooldown=0, inflight={})
    return NETWORK[loop]


async def close_network():
    state=NETWORK.pop(asyncio.get_running_loop(),None)
    if state:
        tasks=list(state['inflight'].values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        await state['client'].aclose()


@asynccontextmanager
async def apple_slot(state):
    async with state['gate']:
        async with state['pace']:
            while True:
                delay=max(0,state['last']+3.1-time.monotonic(),state['cooldown']-time.monotonic())
                if delay<=0: break
                await wait_delay(delay)
            state['last']=time.monotonic()
        yield


async def request(method, url, **kwargs):
    for attempt in range(4):
        try:
            state=network()
            if url.startswith('https://itunes.apple.com/'):
                async with apple_slot(state):
                    response=await state['client'].request(method,url,**kwargs)
            else:
                response=await state['client'].request(method,url,**kwargs)
        except httpx.RequestError:
            if attempt == 3:
                raise ValueError('Could not reach the music service. Check your connection and try again.')
            await asyncio.sleep(2 ** attempt)
            continue
        if response.status_code == 429:
            try:
                delay = max(1, float(response.headers.get('Retry-After', 3)))
            except ValueError:
                delay = 3
            if url.startswith('https://itunes.apple.com/'):
                state['cooldown']=max(state['cooldown'],time.monotonic()+delay)
            if delay > 30 or attempt == 3:
                raise ValueError(f'The service is limiting requests. Try again in {int(delay)} seconds.')
            await asyncio.sleep(delay)
            continue
        if response.status_code >= 500 and attempt < 3:
            await asyncio.sleep(2 ** attempt)
            continue
        if response.status_code == 401:
            raise ValueError('Authorization expired or credentials were rejected. Reconnect Spotify in Settings.')
        if response.status_code in (403, 404):
            raise ValueError('This resource is unavailable. For Spotify, connect your account and use a playlist you own or collaborate on. Check the app’s allowed users and Premium requirements.')
        if response.is_error:
            raise ValueError(f'The music service rejected the request ({response.status_code}). Check your settings and retry.')
        try:
            return response.json()
        except ValueError:
            raise ValueError('The music service returned an unreadable response. Try again later.')


def oauth_start():
    client_id = store.setting('spotify_id', '')
    if not client_id:
        raise ValueError('Save your Spotify Client ID first.')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    AUTH_PENDING.clear()
    AUTH_PENDING[state] = (verifier, time.time(), client_id, AUTH_GENERATION)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return 'https://accounts.spotify.com/authorize?' + urlencode(dict(
        client_id=client_id, response_type='code', redirect_uri=REDIRECT,
        scope='playlist-read-private playlist-read-collaborative', state=state,
        code_challenge_method='S256', code_challenge=challenge))


async def oauth_complete(code, state):
    pending = AUTH_PENDING.pop(state, None)
    if not pending or time.time() - pending[1] > 600 or pending[3] != AUTH_GENERATION or pending[2] != store.setting('spotify_id'):
        raise ValueError('Sign-in expired. Start Connect Spotify again in Settings.')
    token = await request('POST', 'https://accounts.spotify.com/api/token', data=dict(
        grant_type='authorization_code', code=code, redirect_uri=REDIRECT,
        client_id=pending[2], code_verifier=pending[0]))
    if pending[3] != AUTH_GENERATION or pending[2] != store.setting('spotify_id'):
        raise ValueError('Spotify connection settings changed. Start sign-in again.')
    token['expires_at'] = time.time() + token.get('expires_in', 3600)
    store.save_setting('spotify_token', token)

def invalidate_authorization():
    global AUTH_GENERATION
    AUTH_GENERATION += 1
    AUTH_PENDING.clear()
    APP_TOKEN.clear()


async def spotify_token():
    async with TOKEN_LOCK:
        return await _spotify_token()


async def _spotify_token():
    token = store.setting('spotify_token', {})
    if token.get('access_token') and token.get('expires_at', 0) > time.time() + 60:
        return token['access_token']
    client_id = store.setting('spotify_id', '')
    if not client_id:
        raise ValueError('Open Settings and save your Spotify Client ID.')
    if token.get('refresh_token'):
        generation=AUTH_GENERATION
        fresh = await request('POST', 'https://accounts.spotify.com/api/token', data=dict(
            grant_type='refresh_token', refresh_token=token['refresh_token'], client_id=client_id))
        fresh.setdefault('refresh_token', token['refresh_token'])
        if generation!=AUTH_GENERATION: raise ValueError('Spotify settings changed; reconnect before retrying.')
        fresh['expires_at'] = time.time() + fresh.get('expires_in', 3600)
        store.save_setting('spotify_token', fresh)
        return fresh['access_token']
    secret = store.setting('spotify_secret', '')
    if not secret:
        raise ValueError('Connect Spotify in Settings, or provide a Client Secret for public-playlist access where permitted.')
    cache_key=hashlib.sha256((client_id+'\0'+secret).encode()).hexdigest()
    if APP_TOKEN.get('key')==cache_key and APP_TOKEN.get('expires_at',0)>time.time()+60:
        return APP_TOKEN['access_token']
    generation=AUTH_GENERATION
    auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
    data = await request('POST', 'https://accounts.spotify.com/api/token',
                         headers={'Authorization': 'Basic ' + auth}, data={'grant_type': 'client_credentials'})
    if generation!=AUTH_GENERATION: raise ValueError('Spotify settings changed; retry the request.')
    APP_TOKEN.update(key=cache_key,access_token=data['access_token'],expires_at=time.time()+data.get('expires_in',3600))
    return data['access_token']


def playlist_id(url):
    if re.fullmatch(r'spotify:playlist:[A-Za-z0-9]{22}', url):
        return url.split(':')[-1]
    parsed = urlparse(url)
    match = re.fullmatch(r'/(?:intl-[a-z]+/)?playlist/([A-Za-z0-9]{22})/?', parsed.path)
    if parsed.scheme == 'https' and parsed.hostname == 'open.spotify.com' and match:
        return match.group(1)
    raise ValueError('Paste a full Spotify playlist link or spotify:playlist: URI.')


async def stable_playlist(pid,headers,storefront,progress):
    url=f'https://api.spotify.com/v1/playlists/{pid}'
    for attempt in range(3):
        meta=await request('GET',url,headers=headers)
        before=meta.get('snapshot_id')
        items=[];offset=0;expected=None;consistent=True
        while True:
            data=await request('GET',url+'/items',headers=headers,
                               params={'limit':50,'offset':offset,'market':storefront.upper()})
            total=data.get('total')
            if expected is None: expected=total
            elif total!=expected: consistent=False
            batch=data.get('items',[])
            items.extend(batch)
            report(progress,'import','Importing playlist',len(items),total)
            if not data.get('next'): break
            if not batch or (isinstance(total,int) and len(items)>=total):
                consistent=False;break
            offset+=len(batch)
        after=await request('GET',url,headers=headers)
        final_total=(after.get('tracks') or after.get('items') or {}).get('total')
        if (consistent and before and before==after.get('snapshot_id')
                and isinstance(expected,int) and len(items)==expected
                and (final_total is None or final_total==len(items))):
            return meta,items
        report(progress,'import','Playlist changed during import; retrying',0,None)
    raise ValueError('Spotify could not provide a consistent playlist snapshot. Wait until editing has finished, then retry. Existing membership was preserved.')


async def import_playlist(p, progress, mode="replace", source_url=None):
    pid = playlist_id(source_url or p['source_url'])
    token = await spotify_token()
    headers = {'Authorization': 'Bearer ' + token}
    meta,items=await stable_playlist(pid,headers,p['storefront'],progress)
    report(progress,'import','Importing playlist',len(items),len(items))
    recordings = {}; occurrences = []; skipped = 0
    for item in items:
        t = item.get('item') or item.get('track') or {}
        if t.get('type') != 'track' or not t.get('id') or t.get('is_local'):
            skipped += 1
            continue
        metadata = dict(title=t.get('name', ''), artist=', '.join(a['name'] for a in t.get('artists', [])),
                        album=(t.get('album') or {}).get('name', ''), duration=(t.get('duration_ms') or 0)/1000,
                        spotify_id=t['id'], spotify_url=t.get('external_urls', {}).get('spotify', ''),
                        explicit=t.get('explicit'), isrc=t.get('external_ids', {}).get('isrc'))
        rid = store.uid()
        recordings[rid] = dict(metadata, id=rid, included=True, required=False, owned=False,
                              ownership_override=None, match_status='unmatched', selected=None,
                              candidates=[], rejected=[], source_type='spotify')
        occurrences.append(dict(id=store.uid(), recording_id=rid, source_metadata=metadata.copy()))
    from musicharbor.playlist_update import merge_playlist
    result = merge_playlist(p, dict(recordings=recordings, tracks=occurrences), mode)
    if not result['before']: p['name'] = meta.get('name') or p['name']
    p.update(source_url=source_url or p['source_url'], source_type='spotify')
    p['last_playlist_update']['skipped'] = skipped
    return f"Playlist now has {result['count']} entries; {result['reused_recordings']} recording identities reused. Skipped {skipped} unavailable, local, or non-song entries."


def cache_key(endpoint,params):
    return endpoint + ':' + json.dumps(params,sort_keys=True)


def cached(endpoint,params):
    with store.connection() as c:
        row=c.execute('SELECT payload FROM api_cache WHERE key=? AND expires>?',
                      (cache_key(endpoint,params),time.time())).fetchone()
    return json.loads(row['payload']) if row else None


def cache_result(endpoint,params,data):
    with store.connection() as c:
        c.execute('INSERT OR REPLACE INTO api_cache VALUES (?,?,?)',
                  (cache_key(endpoint,params),json.dumps(data),time.time()+86400))


async def apple(endpoint, params, refresh=False):
    if not refresh:
        data=cached(endpoint,params)
        if data is not None: return data
    state=network(); key=cache_key(endpoint,params)
    task=state['inflight'].get(key)
    if task is None:
        async def fetch():
            data=await request('GET','https://itunes.apple.com/'+endpoint,params=params)
            cache_result(endpoint,params,data)
            return data
        task=asyncio.create_task(fetch())
        state['inflight'][key]=task
        def finished(done):
            state['inflight'].pop(key,None)
            if not done.cancelled(): done.exception()  # retrieve failures after all waiters cancel
        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def parallel(items, worker, progress, stage, label):
    """Bound task creation as well as network traffic; cancel children with parent."""
    items=list(items); total=len(items); completed=0; cursor=iter(items)
    report(progress,stage,label,0,total)
    async def consume():
        nonlocal completed
        for item in cursor:
            await worker(item)
            completed+=1
            report(progress,stage,label,completed,total)
    tasks=[asyncio.create_task(consume()) for _ in range(min(performance()['api_concurrency'],total))]
    try:
        if tasks: await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)


async def run_blocking(function, *args):
    """Drain an in-progress mutation before releasing its project reservation."""
    task=asyncio.create_task(asyncio.to_thread(function,*args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A Python worker cannot safely be killed midway through a mutation.
        try: await task
        except Exception: pass
        raise


async def finish_coverage(p,progress):
    total=len(p['recordings'])
    report(progress,'coverage','Matching release coverage',0,total)
    loop=asyncio.get_running_loop()
    def update(done,count):
        if done==count or done%25==0:
            loop.call_soon_threadsafe(report,progress,'coverage','Matching release coverage',done,count)
    await run_blocking(rebuild_coverage,p,store.setting('preferences',{}),update)
    report(progress,'coverage','Matching release coverage',total,total)


async def search(term, country):
    data = await apple('search', dict(term=term, entity='song', media='music', country=country, limit=200))
    return [s for s in data.get('results', []) if s.get('kind') == 'song' and s.get('trackId')]


def release_kind(source, songs=()):
    name = source.get('collectionName', '').casefold()
    count = source.get('trackCount') or len(songs)
    if source.get('artistName', '').casefold() == 'various artists' or any(x in name for x in ('greatest hits', 'best of', 'compilation')): return 'compilation'
    if 'soundtrack' in name: return 'soundtrack'
    if any(x in name for x in ('deluxe', 'expanded', 'anniversary')): return 'deluxe album'
    if re.search(r'\bep\b', name): return 'ep'
    if re.search(r'\bsingle\b', name): return 'single'
    if count > 6: return 'album'
    if count >= 3: return 'ep'
    return 'single' if count else 'unknown'


def product(p, source, songs, individual=False):
    cat_id = str(source.get('trackId') if individual else source.get('collectionId'))
    key = ('track:' if individual else 'album:') + cat_id
    previous = p['releases'].get(key, {})
    name = source.get('trackName' if individual else 'collectionName', 'Untitled release')
    parent = p['releases'].get('album:' + str(source.get('collectionId')), {})
    category = parent.get('kind') or release_kind(source, songs if not individual else ())
    kind = 'individual song' if individual else category
    rel = dict(id=key, catalog_id=cat_id, name=name, artist=source.get('artistName',''), kind=kind,
               purchase_type='track' if individual else 'release', release_kind=category,
               release_id=str(source.get('collectionId') or ''), release_name=source.get('collectionName', ''),
               track_number=source.get('trackNumber'),disc_number=source.get('discNumber'),
               track_count=source.get('trackCount') or parent.get('track_count') or (len(songs) if not individual else None),
               date=source.get('releaseDate','')[:10], price=source.get('trackPrice' if individual else 'collectionPrice'),
               currency=source.get('currency'), url=source.get('trackViewUrl' if individual else 'collectionViewUrl',''),
               artwork=source.get('artworkUrl100',''), songs=songs, coverage=previous.get('coverage',[]),
               owned=previous.get('owned',False), partial=previous.get('partial',[]), excluded=previous.get('excluded',False),
               checked=store.now())
    p['releases'][key] = rel
    if not previous or (previous.get('price'),previous.get('currency'))!=(rel['price'],rel['currency']):
        p['price_history'].append(dict(release_id=key, price=rel['price'], currency=rel['currency'],
                                      storefront=p['storefront'], checked=rel['checked']))
    return rel


def apply_release(p, collection_id, data, refresh=False):
    album=next((r for r in data.get('results',[]) if r.get('wrapperType')=='collection'
                and str(r.get('collectionId'))==str(collection_id)),None)
    songs=[r for r in data.get('results',[]) if r.get('kind')=='song' and r.get('trackId')
           and str(r.get('collectionId'))==str(collection_id)]
    if album:
        previous=p['releases'].get('album:'+str(collection_id),{})
        if len({s['trackId'] for s in songs}) < (album.get('trackCount') or 0) and previous.get('songs') and not previous.get('incomplete_tracklist'):
            # Refresh price without destroying previously complete identity evidence.
            rel=product(p,album,copy.deepcopy(previous['songs']))
            rel['tracklist_refresh_incomplete']=True
            for song in songs: product(p,song,[song],True)
            return {str(song['trackId']) for song in songs}
        rel=product(p,album,songs)
        if len(songs)<(album.get('trackCount') or 0): rel['incomplete_tracklist']=True
        for song in songs: product(p,song,[song],True)
        return {str(song['trackId']) for song in songs}
    elif refresh:
        key='album:'+str(collection_id)
        if key in p['releases']: p['releases'][key].update(price=None,checked=store.now())
    return set()


def lookup_params(p,cid):
    return dict(id=str(cid),entity='song',country=p['storefront'],limit=200)


async def lookup_release(p, collection_id, refresh=False):
    data=await apple('lookup',lookup_params(p,collection_id),refresh)
    return apply_release(p,collection_id,data,refresh)


async def read_releases(p, collections, progress, refresh=False, reuse_existing=False):
    ids=sorted(set(map(str,collections))); done=0; total=len(ids); loaded_tracks=set()
    label='Refreshing releases' if refresh else 'Reading releases'
    report(progress,'releases',label,0,total)
    pending=[]
    for cid in ids:
        saved=p['releases'].get('album:'+cid, {})
        if reuse_existing and not refresh and saved.get('track_count') and len({s.get('trackId') for s in saved.get('songs', []) if s.get('trackId')}) >= saved['track_count']:
            loaded_tracks.update(str(s['trackId']) for s in saved['songs'] if s.get('trackId'))
            done+=1
            continue
        data=None if refresh else cached('lookup',lookup_params(p,cid))
        if data is not None:
            loaded_tracks.update(apply_release(p,cid,data)); done+=1
        else: pending.append(cid)
    report(progress,'releases',label,done,total)
    async def batch(group):
        nonlocal done
        if len(group)==1:
            loaded_tracks.update(await lookup_release(p,group[0],refresh) or set())
            done+=1; report(progress,'releases',label,done,total); return
        try:
            data=await apple('lookup',lookup_params(p,','.join(group)),refresh)
        except ValueError as exc:
            if 'rejected the request (400)' not in str(exc): raise
            data={'results':[]}
        for cid in group:
            results=[r for r in data.get('results',[]) if str(r.get('collectionId'))==cid]
            album=next((r for r in results if r.get('wrapperType')=='collection'),None)
            songs=[r for r in results if r.get('kind')=='song' and r.get('trackId')]
            # A capped/partial batch must never quietly remove album coverage.
            if not album or not album.get('trackCount') or len({s['trackId'] for s in songs})<album['trackCount']:
                loaded_tracks.update(await lookup_release(p,cid,refresh) or set())
            else:
                single=dict(resultCount=len(results),results=results)
                cache_result('lookup',lookup_params(p,cid),single)
                loaded_tracks.update(apply_release(p,cid,single,refresh))
            done+=1; report(progress,'releases',label,done,total)
    groups=[pending[i:i+5] for i in range(0,len(pending),5)]
    # Worker progress is reported in releases, not in batches.
    await parallel(groups,batch,lambda _:None,'batches','Reading batches')
    return loaded_tracks


async def discover(p, progress, reuse_existing=False):
    prefs = store.setting('preferences', {})
    active_ids = playlist_ids(p)
    recordings = [r for rid,r in p['recordings'].items() if rid in active_ids and r.get('included',True)]
    collections = set()
    if reuse_existing:
        pending=[]
        for r in recordings:
            if not r.get('resolution_error') and (r.get('catalog_searched_at') or r.get('selected') or r.get('candidates') or r.get('match_evidence')):
                sources=[c['song'] for c in r.get('candidates', []) if c.get('confidence') in ('high','medium')]
                if r.get('selected'): sources.append(r['selected'])
                collections.update(str(s['collectionId']) for s in sources if s.get('collectionId'))
            else: pending.append(r)
        recordings=pending
    async def resolve(r):
        try:
            results = await search(r['artist'] + ' ' + r['title'], p['storefront'])
        except ValueError as exc:
            r['resolution_error'] = str(exc)
            raise
        r.pop('resolution_error', None)
        candidates = []
        for s in results:
            evidence = score(r, song_data(s), prefs)
            candidates.append(dict(song=s, **evidence))
            if evidence['confidence'] in ('high','medium') or (r.get('selected') and s.get('trackId') == r['selected'].get('trackId')):
                if s.get('collectionId'): collections.add(str(s['collectionId']))
                product(p,s,[s],True)
        r['candidates'] = sorted(candidates,key=lambda c:c['score'],reverse=True)
        r['catalog_searched_at'] = store.now()
        if r.get('selected') and r['selected'].get('collectionId'):
            collections.add(str(r['selected']['collectionId']))
        if r.get('match_status') != 'confirmed':
            r.update(decide(r, results, r.get('rejected', []), prefs))
    try:
        await parallel(recordings,resolve,progress,'search','Searching recordings')
    except ValueError as exc:
        raise ValueError(f'Catalog search interrupted: {exc} Retry to reuse cached results.') from exc
    await run_blocking(consolidate,p,prefs)
    await checkpoint(p,library=True)
    await read_releases(p,collections,progress,reuse_existing=reuse_existing)
    await finish_coverage(p,progress)
    p['refreshed'] = store.now()
    await checkpoint(p,library=True)
    counts = summary(p)['states']
    return f"Matching finished: {counts['EXACT']} exact, {counts['HIGH_CONFIDENCE']} high confidence, {counts['NEEDS_REVIEW']} need review, {counts['UNMATCHED']} unmatched. {len(collections)} candidate releases."


async def refresh_prices(p, progress):
    """Find fresh purchase listings for accepted identities without resolving them again."""
    prefs = store.setting('preferences', {})
    active_ids = playlist_ids(p)
    resolved = [r for rid,r in p['recordings'].items()
                if rid in active_ids and r.get('included', True)
                and r.get('match_status') in ('confirmed', 'high') and r.get('selected')]
    collections = {str(r['catalog_id']) for r in p['releases'].values() if r['id'].startswith('album:')}
    previous_collections = collections.copy()
    async def find_alternatives(rec):
        selected = rec['selected']
        reference = song_data(selected)
        # Force a fresh search: the ordinary discovery cache can hide a new album.
        data = await apple('search', dict(term=reference['artist']+' '+reference['title'],
                           entity='song', media='music', country=p['storefront'], limit=200), True)
        rejected = set(map(str, rec.get('rejected', [])))
        if selected.get('collectionId'):
            collections.add(str(selected['collectionId']))
        for song in data.get('results', []):
            if song.get('kind') != 'song' or not song.get('trackId'):
                continue
            if str(song['trackId']) in rejected:
                continue
            same_listing = str(song['trackId']) == str(selected.get('trackId'))
            if not same_listing and score(reference, song_data(song), prefs)['confidence'] != 'high':
                continue
            product(p, song, [song], True)
            if song.get('collectionId'):
                collections.add(str(song['collectionId']))
        # Deliberately leave selected, candidates, rejection history and identity untouched.
    await parallel(resolved, find_alternatives, progress, 'alternatives', 'Finding alternative releases')
    loaded_tracks=await read_releases(p,collections,progress,True)
    tracks=[r for r in list(p['releases'].values()) if r['id'].startswith('track:')
            and str(r['catalog_id']) not in loaded_tracks]
    async def refresh_track(r):
        data=await apple('lookup',dict(id=r['catalog_id'],country=p['storefront']),True)
        song=next((x for x in data.get('results',[]) if x.get('kind')=='song'),None)
        if song: product(p,song,[song],True)
        else: r.update(price=None,checked=store.now())
    await parallel(tracks,refresh_track,progress,'tracks','Refreshing individual tracks')
    await finish_coverage(p,progress)
    p['refreshed'] = store.now()
    new_releases = sum('album:'+cid in p['releases'] for cid in collections-previous_collections)
    return f'Releases and prices refreshed. {new_releases} new releases found for {len(resolved)} identified recordings. Existing recording matches were preserved.'


class ScanCancelled(Exception):
    pass

def scan_library(p, folder, progress, cancel=None):
    import mutagen
    base = Path(folder).expanduser().resolve()
    if not base.is_dir():
        raise ValueError('Folder not found. Enter an existing local music folder path.')
    previous = {f['path']:f for f in p['local_files']}
    files = dict(previous)
    extensions = {'.mp3','.m4a','.flac','.wav','.aac','.ogg'}
    report(progress,'scan','Scanning local files',0,None,'Counting audio files')
    count = 0
    for path in base.rglob('*'):
        if cancel and cancel.is_set():
            p['local_files']=list(files.values())
            raise ScanCancelled()
        if path.suffix.lower() not in extensions or not path.is_file() or path.is_symlink(): continue
        count += 1
        report(progress,'scan','Scanning local files',count-1,None,path.name)
        item = dict(id=store.uid(), path=str(path), title='',artist='',album='',duration=0,
                    recording_id=None, candidates=[],status='incomplete metadata',manual=False)
        try:
            audio = mutagen.File(path,easy=True)
            if audio is None: raise ValueError('Unsupported or unreadable audio metadata')
            def tag(*keys):
                for k in keys:
                    value = (audio.tags or {}).get(k)
                    if value: return str(value[0] if isinstance(value,list) else value)
                return ''
            item.update(title=tag('title','TIT2'),artist=tag('artist','TPE1'),album=tag('album','TALB'),
                        duration=round(getattr(audio.info,'length',0),3),track_number=tag('tracknumber','TRCK'))
            item.update(bitrate=getattr(audio.info,'bitrate',0) or 0,sample_rate=getattr(audio.info,'sample_rate',0) or 0,bits_per_sample=getattr(audio.info,'bits_per_sample',0) or 0,codec=getattr(audio.info,'codec','') or '')
            raw = mutagen.File(path, easy=False)
            raw_tags = getattr(raw, 'tags', {}) or {}
            def raw_tag(*keys):
                for key in keys:
                    value = raw_tags.get(key)
                    if value is not None:
                        if hasattr(value, 'text'): value = value.text
                        elif hasattr(value, 'data'): value = value.data
                        if isinstance(value, (list, tuple)): value = value[0] if value else ''
                        if isinstance(value, bytes): value = value.decode('utf-8', errors='replace')
                        return str(value)
                return ''
            explicit_tag = tag('explicit', 'itunesadvisory') or raw_tag('rtng', 'TXXX:ITUNESADVISORY', 'TXXX:EXPLICIT')
            explicit = True if explicit_tag.lower() in ('1','4','true','explicit') else False if explicit_tag.lower() in ('2','false','clean','cleaned') else None
            item.update(album_artist=tag('albumartist','TPE2'), disc_number=tag('discnumber','TPOS'),
                        filename=path.name, explicit=explicit,
                        itunes_track_id=tag('itunes_trackid') or raw_tag('cnID') or None,
                        isrc=(tag('isrc','TSRC') or raw_tag('TSRC','----:com.apple.iTunes:ISRC')).upper() or None,
                        musicbrainz_id=tag('musicbrainz_trackid') or raw_tag('UFID:http://musicbrainz.org','----:com.apple.iTunes:MusicBrainz Track Id') or None)
            if item['itunes_track_id'] and not item['itunes_track_id'].isdigit(): item['itunes_track_id']=None
            if item['isrc'] and not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}[0-9]{7}', item['isrc']): item['isrc'] = None
            if item['musicbrainz_id'] and not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', item['musicbrainz_id']): item['musicbrainz_id'] = None
            old = previous.get(str(path))
            fingerprint = [path.stat().st_size, path.stat().st_mtime_ns]
            if old and old.get('fingerprint') == fingerprint:
                old.update({key:item[key] for key in ('bitrate','sample_rate','bits_per_sample','codec')})
                item = old
            else:
                rid = store.uid()
                rec = dict({k:item.get(k) for k in ('title','artist','album','duration','explicit','isrc','musicbrainz_id','itunes_track_id')}, id=rid, included=False, required=False, owned=False,
                           ownership_override=None, match_status='unmatched', selected=None,
                           candidates=[], rejected=[], resolution_state='UNMATCHED', source_type='local_file', library_identity=True)
                # Strong embedded identifiers are independently useful without a
                # playlist or a Store listing. Metadata conflicts still need review.
                if item['musicbrainz_id'] or item['isrc']:
                    rec.update(resolution_state='EXACT', identity_evidence=dict(score=100, reasons=['Embedded recording identifier']), match_evidence=dict(score=100, reasons=['Embedded recording identifier']))
                p['recordings'][rid] = rec
                item.update(identity_id=rid, fingerprint=fingerprint)
            item.setdefault('id', store.uid())
        except Exception as e:
            item.update(status='unreadable',error=str(e))
        files[str(path)]=item
        report(progress,'scan','Scanning local files',count,None,path.name)
    p['local_files']=list(files.values())
    for f in p['local_files']:
        if not Path(f['path']).is_file(): f['status']='missing'
    p['library_folders']=sorted(set(p.get('library_folders',[])+[str(base)]))
    consolidate(p,store.setting('preferences',{}))
    report(progress,'scan','Scanning local files',count,count)
    return f'Scanned {count} files.'


async def scan_and_resolve(p, folder, progress):
    cancel=threading.Event()
    worker=asyncio.create_task(asyncio.to_thread(scan_library,p,folder,progress,cancel))
    try:
        scanned=await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        await asyncio.gather(worker,return_exceptions=True)
        raise
    await checkpoint(p,library=True)
    errors = []
    ids = list(dict.fromkeys(f.get('identity_id') for f in p['local_files'] if f.get('status') != 'missing'))
    eligible=[rid for rid in ids if rid in p['recordings'] and p['recordings'][rid].get('match_status') not in ('confirmed','high')
              and p['recordings'][rid].get('title') and p['recordings'][rid].get('artist')]
    async def identify(rid):
        r=p['recordings'][rid]
        try:
            if r.get('itunes_track_id'):
                data=await apple('lookup',dict(id=r['itunes_track_id'],country=p['storefront']))
                results=[s for s in data.get('results',[]) if s.get('kind')=='song']
                if not results: results=await search(r['artist']+' '+r['title'],p['storefront'])
            else: results=await search(r['artist']+' '+r['title'],p['storefront'])
            exact=r.get('resolution_state')=='EXACT'
            r.update(decide(r,results,r.get('rejected',[]),store.setting('preferences',{})))
            if exact and not r.get('selected'): r.update(resolution_state='EXACT',match_evidence=r.get('identity_evidence',{}))
        except ValueError as exc:
            r['resolution_error']=str(exc); errors.append(str(exc)); raise
    try:
        await parallel(eligible,identify,progress,'identify','Identifying local recordings')
    except ValueError:
        # Keep scanned metadata, but label this stage interrupted rather than 100%.
        report(progress,'identify','Identifying local recordings',sum(p['recordings'][rid].get('match_status') in ('high','confirmed') for rid in eligible),len(eligible),errors[0],status='error')
    await run_blocking(consolidate,p,store.setting('preferences',{}))
    await finish_coverage(p,progress)
    sync_files(p)
    identified = sum(f.get('status') == 'matched' for f in p['local_files'])
    await checkpoint(p,library=True)
    return f'{scanned} {identified} files identified; {len(p["local_files"])-identified} unresolved or unavailable.' + (f' Catalog interrupted: {errors[0]}' if errors else '')


async def import_and_discover(p, progress):
    message = await import_playlist(p, progress)
    await run_blocking(store.save_project,p)
    return message + ' ' + await discover(p, progress, reuse_existing=True)


async def update_and_discover(p, args, progress):
    if args['source']=='spotify':
        message=await import_playlist(p,progress,args['mode'],args['url'])
    else:
        from musicharbor.playlist_update import merge_playlist
        result=merge_playlist(p,args['incoming'],args['mode'])
        p.update(source_type='exportify_csv',source_url='',source_filename=args['filename'],
                 import_summary=args['summary'],imported_at=store.now())
        message=f"Playlist now has {result['count']} entries; {result['reused_recordings']} recording identities reused."
        report(progress,'import','Updating playlist',result['incoming'],result['incoming'])
    # Commit membership before discovery so cancellation never loses the update.
    await run_blocking(store.save_project,p)
    try:
        return message+' '+await discover(p,progress,reuse_existing=True)
    except (Exception, asyncio.CancelledError):
        # Preserve completed searches even if later lookups fail or are cancelled.
        await checkpoint(p,library=True)
        raise

def save_checkpoint(p, library=False):
    rebuild_coverage(p,store.setting('preferences',{}))
    sync_files(p)
    return store.save_project(p,library=library)

async def checkpoint(p, library=False):
    return await run_blocking(save_checkpoint,p,library)
