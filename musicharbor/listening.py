"""Read-only, locally cached listening history. Never changes recording identity."""
import asyncio
import os
import time
from collections import defaultdict
from urllib.parse import quote

import httpx
import musicharbor.store as store
from musicharbor.matching import normalize, song_data, title_base

WINDOW = 90 * 86400
TASK = None
JOB = None
STATE = {'running': False, 'message': '', 'error': None, 'fetched': 0}


def status():
    config = store.setting('listening_config', {})
    cache = store.setting('listening_history', {})
    return dict(provider=config.get('provider','listenbrainz'), username=config.get('username',''),
                days=config.get('days',90), needs_sync=bool(config.get('username')) and (not cache.get('synced_at') or cache.get('days',90)<config.get('days',90)),
                connected=bool(config.get('username')), key_set=bool(store.setting('lastfm_key','') or os.getenv('LASTFM_API_KEY')),
                token_set=bool(store.setting('listenbrainz_token','')), synced_at=cache.get('synced_at'),
                **STATE)


async def fetch_json(client, url, params, headers=None):
    for attempt in range(4):
        await asyncio.sleep(1.05)  # Both providers share this serial, read-only sync.
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.RequestError:
            if attempt < 3: continue
            raise ValueError('Could not reach the listening service. Check your connection and retry.') from None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 3: raise ValueError('The listening service is busy or rate-limited. Please sync again later.')
            try: delay=float(response.headers.get('Retry-After', response.headers.get('X-RateLimit-Reset-In','5')))
            except ValueError: delay=5
            await asyncio.sleep(min(60,max(1,delay)))
            continue
        if response.status_code in (401,403): raise ValueError('History access was denied. Check your credentials and history privacy settings.')
        if response.status_code == 404: raise ValueError('User not found. Check the username in Settings.')
        if response.status_code != 200: raise ValueError('The listening service rejected the request. Check your connection settings.')
        try: data=response.json()
        except ValueError: raise ValueError('The listening service returned an unreadable response. Try again later.') from None
        if data.get('error') in (11,16,29) and attempt<3:
            await asyncio.sleep(5)
            continue
        if data.get('error'):
            raise ValueError('The listening service could not load this history. Check the username, API key and privacy settings.')
        return data


async def download(config, progress, client):
    days=config.get('days',90)
    end=int(time.time()); start=end-days*86400; listens=[]; page=1; cursor=end+1
    while page <= 2000:
        if config['provider']=='lastfm':
            data=await fetch_json(client,'https://ws.audioscrobbler.com/2.0/',dict(
                method='user.getRecentTracks', user=config['username'],
                api_key=os.getenv('LASTFM_API_KEY') or store.setting('lastfm_key',''),
                format='json', limit=200, page=page, **{'from':start-1,'to':end+1}))
            payload=data.get('recenttracks')
            if not isinstance(payload,dict): raise ValueError('Incomplete Last.fm response; previous history kept.')
            tracks=payload.get('track',[])
            if isinstance(tracks,dict): tracks=[tracks]
            for t in tracks:
                if t.get('@attr',{}).get('nowplaying')=='true': continue
                ts=int(t.get('date',{}).get('uts',0))
                if start<=ts<=end:
                    listens.append(dict(ts=ts,title=t.get('name',''),artist=t.get('artist',{}).get('#text',''),
                                        album=t.get('album',{}).get('#text','')))
            pages=int(payload.get('@attr',{}).get('totalPages',1))
            done=page>=pages
            if not tracks and not done: raise ValueError('Last.fm returned an incomplete history. Please retry.')
        else:
            token=store.setting('listenbrainz_token','')
            data=await fetch_json(client,'https://api.listenbrainz.org/1/user/'+quote(config['username'],safe='')+'/listens',
                                  dict(max_ts=cursor,count=1000),{'Authorization':'Token '+token} if token else None)
            payload=data.get('payload')
            if not isinstance(payload,dict) or 'listens' not in payload: raise ValueError('Incomplete ListenBrainz response; previous history kept.')
            tracks=payload['listens']
            for t in tracks:
                ts=int(t.get('listened_at',0)); m=t.get('track_metadata',{})
                if start<=ts<=end:
                    listens.append(dict(ts=ts,title=m.get('track_name',''),artist=m.get('artist_name',''),
                                        album=m.get('release_name',''),mbid=m.get('additional_info',{}).get('recording_mbid')))
            oldest=min((int(t.get('listened_at',0)) for t in tracks),default=0)
            done=not tracks or oldest<start
            if not done and oldest>=cursor: raise ValueError('ListenBrainz pagination did not advance; please retry.')
            if len(tracks)>=1000 and len({t.get('listened_at') for t in tracks})==1:
                raise ValueError('Too many listens share one timestamp to safely paginate. Previous history kept.')
            if len(tracks)>=1000 and not done:
                # Re-fetch the boundary second so a split timestamp is not lost.
                listens=[listen for listen in listens if listen['ts']!=oldest]
                cursor=oldest+1
            else:
                cursor=oldest
        progress(len(listens))
        if done: return dict(provider=config['provider'],username=config['username'],days=days,synced_at=end,listens=listens)
        page+=1
    raise ValueError('History exceeded the sync limit; previous history kept instead of saving partial counts.')


def start_sync():
    global TASK, JOB
    if STATE['running']: raise ValueError('Listening history is already syncing.')
    config=store.setting('listening_config',{})
    if not config.get('username'): raise ValueError('Connect a listening account in Settings first.')
    if config['provider']=='lastfm' and not (os.getenv('LASTFM_API_KEY') or store.setting('lastfm_key','')):
        raise ValueError('Last.fm requires an application API key. Add it in Settings, or choose ListenBrainz.')
    STATE.update(running=True,error=None,message=f"Loading the last {config.get('days',90)} days…",fetched=0)
    JOB=dict(id=store.uid(),project='__listening__',created=store.now(),status='running',
             message=STATE['message'],error=None,stages=[dict(id='listening',
             label=f"Syncing listening history ({config.get('days',90)} days)",status='running',total=None,percent=None,completed=0)])
    job=JOB
    try: store.put_job(job['id'],job)
    except Exception:
        STATE.update(running=False,error='Could not save the listening operation.',message='Sync did not start.')
        JOB=None
        raise
    async def run():
        try:
            async with httpx.AsyncClient(timeout=30,headers={'User-Agent':'MusicHarbor/2.0 (local desktop music library application)'}) as client:
                def progress(count):
                    STATE.update(fetched=count,message=f'Loaded {count:,} listens…')
                    job.update(message=STATE['message'])
                    job['stages'][0]['completed']=count
                data=await download(config,progress,client)
            store.save_setting('listening_history',data)
            STATE.update(message=f"Synced {len(data['listens']):,} listens. Rankings updated.")
            job['status']='done'
        except asyncio.CancelledError:
            STATE.update(message='Sync cancelled. Previous complete history kept.')
            job['status']='cancelled'
            raise
        except Exception as exc:
            STATE.update(error=str(exc) if isinstance(exc,ValueError) else 'Listening sync failed. Try again later.',message='Previous complete history kept.')
            job['status']='error'
        finally:
            STATE['running']=False
            job.update(message=STATE['message'],error=STATE['error'],finished=store.now())
            job['stages'][0]['status']=job['status']
            store.put_job(job['id'],job)
    TASK=asyncio.create_task(run())
    return status()


async def stop():
    if TASK and not TASK.done():
        TASK.cancel()
        await asyncio.gather(TASK,return_exceptions=True)
    # Cancellation can occur before the coroutine executes its finally block.
    if JOB and JOB['status']=='running':
        STATE.update(running=False,message='Sync cancelled.',error=None)
        JOB.update(status='cancelled',message='Sync cancelled.',finished=store.now())
        JOB['stages'][0]['status']='cancelled'
        store.put_job(JOB['id'],JOB)


def play_counts(p, config=None, history=None, now=None):
    config=store.setting('listening_config',{}) if config is None else config
    history=store.setting('listening_history',{}) if history is None else history
    if not config.get('username') or any(config.get(k)!=history.get(k) for k in ('provider','username')) or not history.get('synced_at'):
        return None
    now=time.time() if now is None else now
    # Never present a shorter cached history as a complete longer period.
    if history.get('days',90)<config.get('days',90): return None
    cutoff=now-config.get('days',90)*86400
    ids={t['recording_id'] for t in p['tracks']}
    by_name=defaultdict(set); by_mbid=defaultdict(set); albums=defaultdict(set); known_mbids=defaultdict(set)
    for rid in ids:
        r=p['recordings'][rid]
        sources=[r,*r.get('source_identities',[])]
        if r.get('selected'): sources.append(song_data(r['selected']))
        for source in sources:
            by_name[(title_base(source.get('title')),normalize(source.get('artist')))].add(rid)
            if source.get('musicbrainz_id'):
                by_mbid[source['musicbrainz_id'].lower()].add(rid)
                known_mbids[rid].add(source['musicbrainz_id'].lower())
            if source.get('album'): albums[rid].add(normalize(source['album']))
    counts={rid:0 for rid in ids}
    for listen in history.get('listens',[]):
        if not cutoff<=listen['ts']<= now: continue
        matches=by_name.get((title_base(listen.get('title')),normalize(listen.get('artist'))),set())
        if listen.get('mbid'):
            matches={rid for rid in matches if not known_mbids[rid] or listen['mbid'].lower() in known_mbids[rid]}
            identified=by_mbid.get(listen['mbid'].lower(),set())
            if identified: matches=matches & identified
        if len(matches)>1 and listen.get('album'):
            matches={rid for rid in matches if normalize(listen['album']) in albums[rid]}
        # Ambiguous clean/explicit versions or competing masters do not share plays.
        if len(matches)==1: counts[next(iter(matches))]+=1
    return counts
