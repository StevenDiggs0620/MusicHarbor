"""MusicHarbor: loopback-only application. Run with python app.py."""
import asyncio
import copy
import json
import logging
import math
import secrets
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
import services
import store
import csv_import
import listening
import backup_schema
import portable
import planning
import library_index
import retention
from retention import Retention as RetentionPolicy
from export_policy import ExportOptions, select_files
from identity import consolidate, sync_files, summary
from matching import owned_ids, rec_owned, rebuild_coverage, score, song_data
from optimizer import calculate, CURRENCIES
from progress import JobProgress, STAGES, report
from purchase_order import purchase_groups
from owned_music import owned_collection

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
SESSION = secrets.token_urlsafe(32)
JOBS = {}
BUSY = set()
JOB_GATE = None
SETTINGS_BUSY = False
LOG = logging.getLogger('musicharbor')

@asynccontextmanager
async def lifespan(app):
    global JOB_GATE
    store.init(); store.interrupt_jobs()
    JOB_GATE=asyncio.Semaphore(services.performance()['background_jobs'])
    async def maintain():
        while True:
            await asyncio.sleep(3600)
            await services.run_blocking(retention.cleanup)
            kept=await services.run_blocking(retained_job_ids)
            for jid,job in list(JOBS.items()):
                if job['status'] not in ('running','queued') and jid not in kept: JOBS.pop(jid,None)
    cleanup_task=asyncio.create_task(maintain())
    yield
    tasks = [j['task'] for j in JOBS.values() if j.get('task') and not j['task'].done()]
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    await services.close_network()
    await listening.stop()
    cleanup_task.cancel()
    await asyncio.gather(cleanup_task,return_exceptions=True)

def retained_job_ids():
    with store.connection() as c: return {row[0] for row in c.execute('SELECT id FROM jobs')}

app = FastAPI(title='MusicHarbor', lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=str(ROOT/'static')), name='static')

@app.middleware('http')
async def local_only(request: Request, call_next):
    if request.headers.get('host','') not in ('127.0.0.1:8765','localhost:8765','testserver'):
        return JSONResponse({'error':'Open the app at http://127.0.0.1:8765.'},403)
    origin = request.headers.get('origin')
    if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765','http://testserver'):
        return JSONResponse({'error':'Requests from other websites are blocked.'},403)
    if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('x-app-token',''),SESSION):
        return JSONResponse({'error':'The app session changed. Reload this page and try again.'},403)
    if SETTINGS_BUSY and request.method not in ('GET','HEAD','OPTIONS'):
        return JSONResponse({'error':'Settings are being updated. Please retry when saving finishes.'},409)
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://*.mzstatic.com data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'error':str(exc)},400)

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    LOG.exception('Request failed')
    return JSONResponse({'error':'The operation could not finish. Try again or restart the app.'},500)

@app.get('/',response_class=HTMLResponse)
def home():
    return (ROOT/'static/ui.html').read_text(encoding='utf-8').replace('__APP_TOKEN__', SESSION)

@app.get('/api/health')
def health(): return {'app':'musicharbor','version':2}

@app.get('/api/desktop')
def desktop_capabilities():
    return {'folder_picker':callable(getattr(app.state,'folder_picker',None))}

@app.post('/api/desktop/folder')
async def desktop_folder():
    # Same-origin and session-token checks in local_only also protect this route.
    picker=getattr(app.state,'folder_picker',None)
    if not callable(picker):
        return JSONResponse({'error':'Folder selection requires the desktop app. You can enter a folder path instead.'},409)
    return {'path':await asyncio.to_thread(picker)}

async def read_csv_upload(request):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > csv_import.MAX_BYTES:
            raise ValueError('Choose a CSV smaller than 10 MB.')
        chunks.extend(chunk)
    return await asyncio.to_thread(csv_import.parse, bytes(chunks))

@app.post('/api/import/csv/preview')
async def preview_csv(request:Request):
    return csv_import.preview(await read_csv_upload(request))

@app.post('/api/import/csv')
async def import_csv(request:Request, name:str=Query(default='',max_length=200),
                     storefront:str='us', filename:str=Query(default='playlist.csv',max_length=255)):
    if storefront not in CURRENCIES:
        raise ValueError('Choose United States, Canada, or United Kingdom.')
    parsed = await read_csv_upload(request)
    p = csv_import.build_project(parsed,name,storefront,filename)
    await services.run_blocking(store.put,p)
    return {'project':p['id'], 'name':p['name'], 'count':len(p['tracks']),
            'recording_count':len(p['recordings']), 'warnings':parsed['warnings'][:50],
            'job':(await start_job(p['id'],services.discover))['job']}

def available(pid, load=True):
    if SETTINGS_BUSY: raise ValueError('Settings are being updated. Please wait for saving to finish.')
    if pid in BUSY: raise ValueError('This project has an operation running. Wait for it to finish or cancel it first.')
    return store.get(pid) if load else None

async def mutate(pid, function, *args):
    available(pid,False); BUSY.add(pid)
    try: return await services.run_blocking(function,pid,*args)
    finally: BUSY.discard(pid)

def project_view(p):
    result=copy.deepcopy({k:v for k,v in p.items() if not k.startswith('_')})
    result['identity_summary']=summary(p)
    owned=owned_ids(p)
    for rid,r in result['recordings'].items(): r['effective_owned']=rid in owned
    for f in result['local_files']:
        if not Path(f['path']).is_file(): f['status']='missing'
    result['busy']=p['id'] in BUSY
    result['job']=next((key for key,j in JOBS.items() if j['project']==p['id'] and j['status'] in ('running','queued')),None)
    return result

@app.get('/api/projects')
def list_projects(): return store.projects()

@app.get('/api/projects/{pid}')
def get_project(pid:str): return project_view(store.get(pid))

class CreateProject(BaseModel):
    name:str=Field(default='Untitled playlist',min_length=1,max_length=200)
    storefront:str='us'
    url:str=Field(default='',max_length=2000)

@app.post('/api/projects')
async def create_project(body:CreateProject):
    if body.storefront not in CURRENCIES: raise ValueError('Choose United States, Canada, or United Kingdom.')
    if body.url: services.playlist_id(body.url)
    return await services.run_blocking(store.put,store.new_project(body.name,body.storefront,body.url))

class Rename(BaseModel):
    name:str=Field(min_length=1,max_length=200)

@app.patch('/api/projects/{pid}')
async def rename_project(pid:str,body:Rename):
    return await mutate(pid,save_rename,body)

def save_rename(pid,body):
    p=store.get(pid); p['name']=body.name.strip() or 'Untitled playlist'
    return store.put(p)

@app.delete('/api/projects/{pid}')
async def delete_project(pid:str):
    await mutate(pid,store.delete)
    return {'ok':True}

@app.post('/api/projects/{pid}/duplicate')
async def duplicate_project(pid:str):
    return await mutate(pid,store.duplicate)

async def start_job(pid, operation, args=None):
    available(pid,False); BUSY.add(pid); jid=store.uid()
    name=operation if isinstance(operation,str) else operation.__name__
    stages=[dict(id=key,label=label,status='pending',completed=0,total=None,percent=None)
            for key,label in STAGES.get(name, [('work','Working'),('save','Saving results')])]
    job=dict(project=pid,kind=name,status='queued',message='Waiting for a background slot…',error=None,
             created=store.now(),stages=stages)
    try: await services.run_blocking(store.put_job,jid,job)
    except BaseException:
        BUSY.discard(pid)
        raise
    JOBS[jid]=job
    progress=JobProgress(job)
    async def run():
        p=None
        try:
            async with JOB_GATE:
                job.update(status='running',message='Starting…')
                p=await services.run_blocking(store.get,pid,operation=='scan')
                if operation=='plan':
                    report(progress,'work','Calculating purchase plan',0,None)
                    counts=await services.run_blocking(listening.play_counts,p)
                    job['result']=await planning.run(p,args,counts)
                    result='Purchase plan ready.'
                    report(progress,'work','Purchase plan ready',1,1)
                elif operation=='update_playlist': result=await services.update_and_discover(p,args,progress)
                elif operation=='scan': result=await services.scan_and_resolve(p,args,progress)
                elif operation=='load_release':
                    report(progress,'releases','Reading selected release',0,1)
                    await services.lookup_release(p,args)
                    report(progress,'releases','Reading selected release',1,1)
                    await services.finish_coverage(p,progress)
                    result='Selected release loaded. Your confirmed match is saved.'
                else: result=await operation(p,progress)
                report(progress,'save','Saving results',0,1)
                if operation!='plan': await services.run_blocking(store.save_project,p,True)
                report(progress,'save','Saving results',1,1)
                for stage in stages:
                    if stage['status']=='pending': stage['status']='skipped'
                job.update(status='error' if any(stage['status']=='error' for stage in stages) else 'done',message=result)
        except asyncio.CancelledError:
            job.update(status='cancelled',message='Cancelled. Saving completed work…')
            if p is not None and operation!='plan':
                try: await services.checkpoint(p,library=True)
                except Exception:
                    LOG.exception('Could not save cancelled work')
                    job['error']='Cancelled, but the latest work could not be saved. Previously committed results remain available.'
            job['message']=job.get('error') or ('Cancelled. Completed work was saved.' if p is not None else 'Cancelled before work started.')
        except Exception as e:
            LOG.exception('Background operation failed')
            job.update(status='error',error=str(e) if isinstance(e,ValueError) else 'The operation failed. Check your connection or restart and retry.',message='Operation stopped. Previously completed stages are retained.')
            if p is not None and operation!='plan':
                try: await services.checkpoint(p,library=True)
                except Exception:
                    LOG.exception('Could not save interrupted work')
                    job['message']='The latest work could not be saved. Previously committed results remain available.'
        finally:
            for stage in stages:
                if stage['status']=='running': stage['status']=job['status']
            job['finished']=store.now()
            try: await services.run_blocking(store.put_job,jid,job)
            finally: BUSY.discard(pid)
    job['task']=asyncio.create_task(run())
    def cancelled_before_start(task):
        if task.cancelled() and job['status']=='queued':
            job.update(status='cancelled',message='Cancelled before starting.',finished=store.now())
            BUSY.discard(pid); store.put_job(jid,job)
    job['task'].add_done_callback(cancelled_before_start)
    return {'job':jid}


@app.get('/api/projects/{pid}/jobs')
def project_jobs(pid:str):
    saved={j['id']:j for j in store.jobs(pid)+store.jobs('__listening__')}
    if listening.JOB and listening.STATE['running']: saved[listening.JOB['id']]=listening.JOB
    for jid,job in list(JOBS.items()):
        if job['project']==pid: saved[jid]=dict(id=jid,**{k:v for k,v in job.items() if k!='task'})
    return sorted(saved.values(),key=lambda j:j['created'],reverse=True)


@app.get('/api/jobs')
def global_jobs():
    return project_jobs('__listening__')


@app.post('/api/jobs/{jid}/dismiss')
async def dismiss_job(jid:str):
    if listening.JOB and listening.JOB['id']==jid and listening.STATE['running']:
        raise ValueError('Cancel the running operation before dismissing it.')
    if jid in JOBS and JOBS[jid]['status'] in ('queued','running'):
        raise ValueError('Cancel the running operation before dismissing it.')
    JOBS.pop(jid,None); store.dismiss_job(jid)
    return {'ok':True}

@app.post('/api/projects/{pid}/import')
async def import_playlist(pid:str): return await start_job(pid,services.import_and_discover)

class PlaylistUpdateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    mode: Literal['add', 'replace'] = 'add'


@app.post('/api/projects/{pid}/playlist/spotify')
async def update_spotify_playlist(pid:str, body:PlaylistUpdateRequest):
    services.playlist_id(body.url)
    return await start_job(pid,'update_playlist',dict(source='spotify',url=body.url,mode=body.mode))


@app.post('/api/projects/{pid}/playlist/csv')
async def update_csv_playlist(pid:str, request:Request, mode:Literal['add','replace']='add',
                              filename:str=Query(default='playlist.csv',max_length=255)):
    available(pid,False)
    p=await services.run_blocking(store.get,pid)
    parsed=await read_csv_upload(request)
    incoming=csv_import.build_project(parsed,p['name'],p['storefront'],filename)
    # Recheck availability in start_job after awaiting upload and parsing.
    return await start_job(pid,'update_playlist',dict(source='csv',mode=mode,filename=incoming['source_filename'],
                                               incoming=incoming,summary=incoming['import_summary']))


@app.post('/api/projects/{pid}/discover')
async def discover(pid:str): return await start_job(pid,services.discover)

@app.post('/api/projects/{pid}/refresh')
async def refresh(pid:str): return await start_job(pid,services.refresh_prices)

@app.get('/api/jobs/{jid}')
async def job_status(jid:str):
    if jid not in JOBS: raise ValueError('This operation is no longer available. Reload the project.')
    job=JOBS[jid]
    result={k:v for k,v in job.items() if k!='task'}
    if job.get('task') and not job['task'].done() and result['status'] in ('done','cancelled','error'):
        result['status']='running'
    return result

@app.post('/api/jobs/{jid}/cancel')
async def cancel_job(jid:str):
    if listening.JOB and listening.JOB['id']==jid: await listening.stop()
    if jid in JOBS and JOBS[jid]['status'] in ('queued','running'): JOBS[jid]['task'].cancel()
    return {'ok':True}

class Preferences(BaseModel):
    clean_explicit_equivalent:bool=False
    remasters_equivalent:bool=False

class Performance(BaseModel):
    api_concurrency:int=Field(default=3,ge=1,le=6)
    background_jobs:int=Field(default=2,ge=1,le=4)

class Settings(BaseModel):
    spotify_id:str=Field(default='',max_length=200)
    spotify_secret:str=Field(default='',max_length=500)
    clear_secret:bool=False
    storefront:str='us'
    preferences:Preferences=Field(default_factory=Preferences)
    performance:Performance|None=None
    retention:RetentionPolicy|None=None

@app.get('/api/settings')
def settings():
    return dict(spotify_id=store.setting('spotify_id',''),spotify_secret_set=bool(store.setting('spotify_secret','')),
                connected=bool(store.setting('spotify_token',{}).get('refresh_token')),storefront=store.setting('storefront','us'),
                preferences=store.setting('preferences',{}),performance=services.performance(),redirect_uri=services.REDIRECT,listening=listening.status(),retention=store.setting('retention',retention.Retention().model_dump()))

@app.post('/api/settings')
async def save_settings(body:Settings):
    global JOB_GATE, SETTINGS_BUSY
    if SETTINGS_BUSY: raise ValueError('Settings are already being updated. Please wait for saving to finish.')
    if BUSY: raise ValueError('Wait for running operations to finish before changing settings.')
    SETTINGS_BUSY=True
    try:
        if body.spotify_id.strip() != await services.run_blocking(store.setting,'spotify_id',''):
            services.invalidate_authorization()
        if body.performance is not None: await services.close_network()
        result=await services.run_blocking(apply_settings,body)
        if body.performance is not None: JOB_GATE=asyncio.Semaphore(body.performance.background_jobs)
        return result
    finally:
        SETTINGS_BUSY=False

def apply_settings(body):
    with store.connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        return apply_settings_transaction(body)

def apply_settings_transaction(body):
    if body.storefront not in CURRENCIES: raise ValueError('Invalid storefront.')
    if body.spotify_id.strip() != store.setting('spotify_id',''):
        store.save_setting('spotify_token',{})
    store.save_setting('spotify_id',body.spotify_id.strip())
    if body.clear_secret: store.save_setting('spotify_secret','')
    elif body.spotify_secret: store.save_setting('spotify_secret',body.spotify_secret.strip())
    store.save_setting('storefront',body.storefront)
    if body.performance is not None:
        store.save_setting('performance',body.performance.model_dump())
    if body.retention is not None: store.save_setting('retention',body.retention.model_dump())
    prefs=body.preferences.model_dump(); old=store.setting('preferences',{})
    store.save_setting('preferences',prefs)
    if old != prefs:
        for row in store.projects():
            p=store.get(row['id'])
            for rec in p['recordings'].values():
                if rec.get('match_status')=='high' and rec.get('selected'):
                    evidence=score(rec,song_data(rec['selected']),prefs)
                    if evidence['confidence']!='high': rec.update(match_status=evidence['confidence'],selected=None,resolution_state='NEEDS_REVIEW')
            rebuild_coverage(p,prefs); sync_files(p); store.save_project(p,library=True)
    return {'ok':True}

class ListeningConnection(BaseModel):
    days: int = Field(default=90,ge=1,le=3650,strict=True)
    provider: Literal['listenbrainz','lastfm'] = 'listenbrainz'
    username: str = Field(min_length=1,max_length=100)
    api_key: str = Field(default='',max_length=256)
    token: str = Field(default='',max_length=256)


@app.get('/api/listening')
def listening_status(): return listening.status()


@app.post('/api/listening/connect')
async def connect_listening(body:ListeningConnection):
    if listening.STATE['running']: raise ValueError('Wait for listening sync to finish before changing accounts.')
    username=body.username.strip()
    if not username or any(c in username for c in '/\\?#'):
        raise ValueError('Enter your username, not a profile URL.')
    if body.api_key.strip(): store.save_setting('lastfm_key',body.api_key.strip())
    if body.token.strip(): store.save_setting('listenbrainz_token',body.token.strip())
    if body.provider=='lastfm' and not listening.status()['key_set']:
        raise ValueError('Last.fm requires an application API key. Follow the setup link below, or choose ListenBrainz.')
    config=dict(provider=body.provider,username=username,days=body.days)
    previous=store.setting('listening_config',{})
    if any(config[k]!=previous.get(k) for k in ('provider','username')): store.save_setting('listening_history',{})
    store.save_setting('listening_config',config)
    return listening.start_sync()


@app.post('/api/listening/sync')
async def sync_listening(): return listening.start_sync()


@app.post('/api/listening/disconnect')
async def disconnect_listening():
    await listening.stop()
    for key in ('listening_config','listening_history'): store.save_setting(key,{})
    for key in ('lastfm_key','listenbrainz_token'): store.save_setting(key,'')
    listening.STATE.update(running=False,message='',error=None,fetched=0)
    return listening.status()


@app.post('/api/oauth/start')
async def oauth_start(): return {'url':services.oauth_start()}

@app.get('/api/oauth/callback')
async def oauth_callback(code:str='',state:str='',error:str=''):
    if error: return RedirectResponse('/?oauth=cancelled',303)
    await services.oauth_complete(code,state)
    return RedirectResponse('/?oauth=connected',303)

@app.post('/api/oauth/disconnect')
async def disconnect():
    if BUSY: raise ValueError('Wait for running operations to finish before disconnecting.')
    services.invalidate_authorization()
    store.save_setting('spotify_token',{})
    return {'ok':True}

class RecordingUpdate(BaseModel):
    included:bool|None=None
    required:bool|None=None
    owned:bool|None=None
    ownership_override:bool|None=None
    reset_override:bool=False

@app.patch('/api/projects/{pid}/recordings/{rid}')
async def update_recording(pid:str,rid:str,body:RecordingUpdate):
    return await mutate(pid,save_recording,rid,body)

def save_recording(pid,rid,body):
    p=store.get(pid)
    if rid not in p['recordings']: raise ValueError('Recording not found.')
    r=p['recordings'][rid]
    for key in ('included','required','owned','ownership_override'):
        value=getattr(body,key)
        if value is not None: r[key]=value
    if body.required: r['included']=True
    if body.included is False: r['required']=False
    if body.reset_override: r['ownership_override']=None
    store.put(p)
    return {'ok':True}

class ReleaseUpdate(BaseModel):
    owned:bool|None=None
    excluded:bool|None=None
    partial:list[str]|None=None
    clear_ownership:bool=False

@app.patch('/api/projects/{pid}/releases/{release_id}')
async def update_release(pid:str,release_id:str,body:ReleaseUpdate):
    return await mutate(pid,save_release,release_id,body)

def save_release(pid,release_id,body):
    p=store.get(pid)
    if release_id not in p['releases']: raise ValueError('Release not found.')
    r=p['releases'][release_id]
    for key in ('owned','excluded','partial'):
        value=getattr(body,key)
        if value is not None:
            if key=='partial' and not set(value)<=set(r['coverage']): raise ValueError('Choose recordings contained in this release.')
            r[key]=value
    if body.clear_ownership: r.update(owned=False,partial=[])
    store.put(p)
    return {'ok':True}

class MatchDecision(BaseModel):
    track_id:str=Field(max_length=40)
    action:str='confirm'

@app.post('/api/projects/{pid}/recordings/{rid}/match')
async def match_decision(pid:str,rid:str,body:MatchDecision):
    available(pid,False)
    BUSY.add(pid)
    try: return await services.run_blocking(save_match_decision,pid,rid,body)
    finally: BUSY.discard(pid)

def save_match_decision(pid,rid,body):
    p=store.get(pid)
    if rid not in p['recordings']: raise ValueError('Recording not found.')
    rec=p['recordings'][rid]
    candidate=next((c['song'] for c in rec.get('candidates',[]) if str(c['song'].get('trackId'))==body.track_id),None)
    if not candidate: raise ValueError('Search for a candidate before selecting it.')
    original_entries=[t for t in p['tracks'] if t['recording_id']==rid]
    if original_entries and any(f.get('recording_id')==rid for f in p['local_files']):
        # Playlist overrides must not rewrite the identity of an owned file.
        new_id=store.uid()
        rec=copy.deepcopy(rec); rec.update(id=new_id,library_identity=False)
        p['recordings'][new_id]=rec
        p['recordings'][rid].update(included=False,required=False)
        for entry in original_entries: entry['recording_id']=new_id
        rid=new_id
    if body.action=='reject':
        rec['rejected']=sorted(set(rec.get('rejected',[])+[body.track_id]))
        if rec.get('selected') and str(rec['selected'].get('trackId'))==body.track_id: rec.update(selected=None,match_status='unmatched',resolution_state='NEEDS_REVIEW',match_evidence={'score':0,'reasons':['Previous match rejected']})
    elif body.action=='confirm':
        rec['selected']=candidate; rec['match_status']='confirmed'
        rec['resolution_state']='HIGH_CONFIDENCE'
        rec['match_evidence']={'score':100,'reasons':['Manually confirmed by user']}
        rec['rejected']=[x for x in rec.get('rejected',[]) if x!=body.track_id]
        services.product(p,candidate,[candidate],True)
    else: raise ValueError('Choose confirm or reject.')
    remap=consolidate(p,store.setting('preferences',{})); sync_files(p)
    services.save_checkpoint(p,library=True)
    return {'ok':True, 'recording_id':original_entries[0]['recording_id'] if original_entries else remap.get(rid,rid)}

class Search(BaseModel):
    term:str=Field(min_length=1,max_length=300)

@app.post('/api/projects/{pid}/recordings/{rid}/search')
async def manual_search(pid:str,rid:str,body:Search):
    available(pid,False)
    BUSY.add(pid)
    try:
        p=await services.run_blocking(store.get,pid)
        if rid not in p['recordings']: raise ValueError('Recording not found.')
        songs=await services.search(body.term,p['storefront'])
        await services.run_blocking(save_search_results,p,rid,songs)
        return {'count':len(songs)}
    finally: BUSY.discard(pid)

def save_search_results(p,rid,songs):
    rec=p['recordings'][rid];prefs=store.setting('preferences',{})
    candidates={str(c['song'].get('trackId')):c for c in rec.get('candidates',[])}
    for song in songs: candidates[str(song['trackId'])]=dict(song=song,**score(rec,song_data(song),prefs))
    rec['candidates']=sorted(candidates.values(),key=lambda c:c['score'],reverse=True)
    store.save_project(p,library=True)

@app.post('/api/projects/{pid}/recordings/{rid}/release')
async def selected_release(pid:str,rid:str):
    available(pid,False)
    p=await services.run_blocking(store.get,pid); rec=p['recordings'].get(rid)
    if not rec or not rec.get('selected'): raise ValueError('Confirm a recording first.')
    cid=rec['selected'].get('collectionId')
    if not cid: raise ValueError('This result has no release identifier.')
    return await start_job(pid,'load_release',cid)

class PlanRequest(BaseModel):
    strategy:str='cheapest'
    purchase_penalty:float=Field(default=1,ge=0,le=10000,allow_inf_nan=False)
    budget:float|None=Field(default=None,ge=0,le=1000000,allow_inf_nan=False)
    artist:str=Field(default='',max_length=200)

@app.post('/api/projects/{pid}/plan/start')
async def start_plan(pid:str,body:PlanRequest):
    if body.strategy not in ('cheapest','fewest','best-value','most-songs','songs-per-dollar','artist'): raise ValueError('Choose a purchase strategy.')
    return await start_job(pid,'plan',body.model_dump())

@app.post('/api/projects/{pid}/plan')
async def plan(pid:str,body:PlanRequest):
    # Compatibility endpoint shares the same reservations and solver gate.
    started=await start_plan(pid,body)
    job=JOBS[started['job']]
    await asyncio.shield(job['task'])
    if job['status']!='done': raise ValueError(job.get('error') or job['message'])
    return job['result']

@app.get('/api/projects/{pid}/library')
def library_page(pid:str,offset:int=Query(default=0,ge=0),limit:int=Query(default=100,ge=1,le=200)):
    store.get(pid)
    return library_index.page(offset,limit)

@app.get('/api/projects/{pid}/owned-collection')
def get_owned_collection(pid:str):
    p=store.get(pid)
    return owned_collection(p,listening.play_counts(p))


class Scan(BaseModel):
    folder:str=Field(min_length=1,max_length=4000)

@app.post('/api/projects/{pid}/scan')
async def scan(pid:str,body:Scan): return await start_job(pid,'scan',body.folder)

class LocalMatch(BaseModel):
    recording_id:str|None=None

@app.patch('/api/projects/{pid}/files/{fid}')
async def local_match(pid:str,fid:str,body:LocalMatch):
    return await mutate(pid,save_local_match,fid,body)

def save_local_match(pid,fid,body):
    p=store.get(pid,True); file=next((f for f in p['local_files'] if f['id']==fid),None)
    if not file: raise ValueError('Local file not found.')
    if body.recording_id is not None and body.recording_id not in p['recordings']: raise ValueError('Recording not found.')
    if body.recording_id and not Path(file['path']).is_file(): raise ValueError('This file is missing. Scan its current folder.')
    file.update(recording_id=body.recording_id,identity_id=body.recording_id,status='matched' if body.recording_id else 'unmatched',manual=True)
    store.save_project(p,library=True)
    return {'ok':True}


@app.post('/api/projects/{pid}/files/{fid}/search')
async def local_search(pid:str, fid:str, body:Search):
    available(pid,False)
    BUSY.add(pid)
    try:
        p=await services.run_blocking(store.get,pid,True)
        file=next((f for f in p['local_files'] if f['id']==fid), None)
        if not file: raise ValueError('Local file not found.')
        songs=await services.search(body.term,p['storefront'])
        decision=await services.run_blocking(services.decide,file,songs,(),store.setting('preferences',{}))
        file['candidates']=decision['candidates']
        await services.run_blocking(store.save_project,p,True)
        return file
    finally: BUSY.discard(pid)


@app.post('/api/projects/{pid}/files/{fid}/match')
async def confirm_local(pid:str, fid:str, body:MatchDecision):
    available(pid,False); BUSY.add(pid)
    try: return await services.run_blocking(save_local_confirmation,pid,fid,body)
    finally: BUSY.discard(pid)

def save_local_confirmation(pid, fid, body):
    p=store.get(pid,True)
    file=next((f for f in p['local_files'] if f['id']==fid), None)
    if not file or not Path(file['path']).is_file(): raise ValueError('Local file is missing.')
    original=p['recordings'].get(file.get('identity_id') or file.get('recording_id'), {})
    candidates=file.get('candidates') or original.get('candidates', [])
    candidate=next((c['song'] for c in candidates if 'song' in c and str(c['song'].get('trackId'))==body.track_id), None)
    if candidate is None: raise ValueError('Search for a recording candidate first.')
    if body.action != 'confirm': raise ValueError('Choose confirm for this file.')
    # A file override creates a new identity before consolidation. Never change
    # a playlist recording just because a previously linked file was corrected.
    rid=store.uid()
    r=dict(id=rid, **song_data(candidate), included=False, required=False, owned=False,
           ownership_override=None, source_type='local_file', library_identity=True, selected=candidate,
           candidates=candidates, rejected=[], match_status='confirmed', resolution_state='HIGH_CONFIDENCE',
           match_evidence={'score':100,'reasons':['Manually confirmed for this local file']})
    p['recordings'][rid]=r
    r['source_identifiers']={key:file.get(key) or original.get(key) for key in ('isrc','musicbrainz_id','itunes_track_id') if file.get(key) or original.get(key)}
    for key in ('isrc','musicbrainz_id'):
        supplied=r['source_identifiers'].get(key)
        if supplied and not r.get(key): r[key]=supplied
        elif supplied and r.get(key)!=supplied:
            r.setdefault('identifier_conflicts',{})[key]=supplied
    file.update(recording_id=rid,identity_id=rid,status='matched',manual=True)
    consolidate(p,store.setting('preferences',{}))
    services.save_checkpoint(p,library=True)
    return {'ok':True}

class ExportChoice(BaseModel):
    path:str|None=Field(default=None,max_length=32768)

@app.patch('/api/projects/{pid}/export-files/{rid}')
async def export_choice(pid:str,rid:str,body:ExportChoice):
    return await mutate(pid,save_export_choice,rid,body)

def save_export_choice(pid,rid,body):
    p=store.get(pid)
    if rid not in {t['recording_id'] for t in p['tracks']}: raise ValueError('Recording is not in this playlist.')
    overrides=p.setdefault('export_file_overrides',{})
    if body.path is None: overrides.pop(rid,None)
    elif any(f['path']==body.path and f.get('recording_id')==rid and f.get('status')=='matched' for f in p['local_files']):
        overrides[rid]=body.path
    else: raise ValueError('Choose a matched local file for this recording.')
    store.put(p)
    return {'ok':True}

def export_lines(p, options=None, include_report=False, summary=None):
    options = options or ExportOptions()
    source = options.path_from.replace('\\', '/')
    replacement = options.path_to.replace('\\', '/')
    if options.custom_path:
        if not source: raise ValueError('Enter the path text to replace.')
        if any(c in source + replacement for c in ('\n', '\r', '\0')):
            raise ValueError('Paths cannot contain line breaks or null characters.')
    mapping,_=select_files(p,options)
    owned=owned_ids(p)
    lines=['#EXTM3U'] if options.extinf else []
    skipped=0
    omissions=[]
    def omit(position,rid,r,reason,action):
        if summary is not None:
            group=summary.setdefault(reason,dict(reason=reason,action=action,count=0,entries=[]))
            group['count']+=1
            if len(group['entries'])<50:
                group['entries'].append(dict(position=position,recording_id=rid,title=r['title'],artist=r['artist']))
        if len(omissions)<200:
            omissions.append(dict(position=position,recording_id=rid,title=r['title'],artist=r['artist'],reason=reason,action=action))
    for position,entry in enumerate(p['tracks'],1):
        rid=entry['recording_id']; r=p['recordings'][rid]; file=mapping.get(rid)
        reason='Not included' if not r.get('included',True) else 'Not marked owned' if rid not in owned else 'Needs a matched local file' if not file else None
        if reason:
            skipped+=1
            omit(position,rid,r,reason,'songs' if not r.get('included',True) else 'plan' if rid not in owned else 'library')
            continue
        path=file['path']
        if any(c in path for c in ('\n','\r','\0')):
            skipped+=1
            omit(position,rid,r,'File path contains an unsupported line break or character','library')
            continue
        path=path.replace('\\','/')
        if options.custom_path:
            if options.path_mode=='prefix':
                prefix=source.rstrip('/')+'/'
                if not path.startswith(prefix):
                    skipped+=1
                    omit(position,rid,r,'Outside the selected source music folder','export')
                    continue
                relative=path[len(prefix):]
                destination=replacement.rstrip('/') or ('/' if replacement.startswith('/') else '')
                path=(destination+('' if destination.endswith('/') else '/') if destination else '')+relative
            else:
                path=path.replace(source,replacement)
        if options.slashes=='windows': path=path.replace('/','\\')
        if not path or path.startswith('#'):
            raise ValueError('The exported path must not be empty or start with #.')
        label=(r['artist']+' - '+r['title']).replace('\n',' ').replace('\r',' ').replace('\0','')
        if options.extinf:
            lines.append(f'#EXTINF:{round(file.get("duration") or r.get("duration") or -1)},{label}')
        lines.append(path)
    return (lines,skipped,omissions) if include_report else (lines,skipped)

@app.get('/api/projects/{pid}/export-preview')
def export_preview(pid:str, options:ExportOptions=Depends()):
    summary={}
    p=store.get(pid); lines,skipped,omissions=export_lines(p,options,True,summary)
    return {'count':len(p['tracks'])-skipped,'skipped':skipped,'omissions':omissions,'omission_groups':list(summary.values()),'text':'\n'.join(lines)+'\n'}

@app.post('/api/projects/{pid}/export')
async def export_m3u(pid:str, options:ExportOptions=Depends()):
    available(pid,False); BUSY.add(pid)
    try: return await services.run_blocking(build_export,pid,options)
    finally: BUSY.discard(pid)

def build_export(pid,options):
    p=store.get(pid); lines,skipped=export_lines(p,options); count=len(p['tracks'])-skipped
    if not count: raise ValueError('No exportable files. Include songs, mark them owned, and confirm local file matches first.')
    p['exports'].append(dict(created=store.now(),count=count,skipped=skipped,options=options.model_dump())); store.put(p)
    return Response(('\n'.join(lines)+'\n').encode('utf-8'),media_type='audio/x-mpegurl',headers={'Content-Disposition':f'attachment; filename="playlist-owned.{options.format}"'})

@app.get('/api/projects/{pid}/backup')
def backup(pid:str,scope:Literal['project','library']='project'):
    return Response(portable.encode(scope,pid),
                    media_type='application/json',headers={'Content-Disposition':f'attachment; filename="playlist-{scope}.json"'})

@app.post('/api/restore')
async def restore(request:Request):
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>backup_schema.MAX_BYTES:
            raise ValueError('Project file is too large (128 MB maximum).')
        data.extend(chunk)
    if SETTINGS_BUSY: raise ValueError('Settings are being updated. Please retry after saving finishes.')
    return await services.run_blocking(restore_project,bytes(data))

def restore_project(data):
    try:
        blob=json.loads(data)
    except (ValueError,UnicodeError,RecursionError): raise ValueError('That is not a valid MusicHarbor project backup.')
    if isinstance(blob,dict) and blob.get('format') in ('musicharbor-library','playlist-purchaser-library'): return portable.restore_library(blob)
    p=backup_schema.validate(blob)
    p.update(id=store.uid(),name=p['name']+' (restored)',created=store.now(),local_files=[],library_folders=[])
    p.setdefault('exports',[]); p.setdefault('price_history',[]); p.setdefault('source_url',''); p.setdefault('refreshed',None)
    services.save_checkpoint(p)
    return p

def main():
    import uvicorn
    if sys.stdout is None or sys.stderr is None:
        store.DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
        stream=(store.DATA/'application.log').open('a',encoding='utf-8')
        if sys.stdout is None: sys.stdout=stream
        if sys.stderr is None: sys.stderr=stream
    if '--no-browser' not in sys.argv:
        timer=threading.Timer(1.5,lambda:webbrowser.open('http://127.0.0.1:8765'))
        timer.daemon=True; timer.start()
    uvicorn.run(app,host='127.0.0.1',port=8765,access_log=False)

if __name__=='__main__': main()
