"""Local transactional persistence; project snapshots keep occurrence order and decisions together."""
import copy
import hashlib
import json
import os
import sqlite3
import sys
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from musicharbor.branding import data_dir

DATA = data_dir()
DB = DATA / ('playlist_purchaser.sqlite3' if (DATA / 'playlist_purchaser.sqlite3').exists() else 'musicharbor.sqlite3')
_TRANSACTION = threading.local()

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return uuid.uuid4().hex

@contextmanager
def connection():
    existing = getattr(_TRANSACTION, 'connection', None)
    if existing is not None:
        yield existing
        return
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    _TRANSACTION.connection = c
    _TRANSACTION.after_commit = []
    try:
        yield c
        c.commit()
        for callback in _TRANSACTION.after_commit: callback()
    except Exception:
        c.rollback()
        raise
    finally:
        _TRANSACTION.connection = None
        _TRANSACTION.after_commit = []
        c.close()

def save_project(p, library=False):
    """Commit a project and related library changes as one transaction."""
    with connection() as c:
        if not c.in_transaction: c.execute('BEGIN IMMEDIATE')
        if library: save_library(p)
        put(p)
    return p

def init():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS library_files(path TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS library_recordings(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS api_cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL);
        ''')
    try:
        DB.chmod(0o600)
    except OSError:
        pass
    migrate_legacy()
    from musicharbor.library_index import initialize
    with connection() as c: initialize(c)
    from musicharbor.retention import cleanup
    cleanup()

def setting(key, default=None):
    env = {'spotify_id': 'SPOTIFY_CLIENT_ID', 'spotify_secret': 'SPOTIFY_CLIENT_SECRET'}.get(key)
    if env and os.getenv(env):
        return os.environ[env]
    with connection() as c:
        row = c.execute('SELECT v FROM settings WHERE k=?', (key,)).fetchone()
    return json.loads(row['v']) if row else default

def save_setting(key, value):
    with connection() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

def new_project(name='Untitled playlist', storefront='us', url=''):
    return dict(id=uid(), name=name, storefront=storefront, source_url=url,
                created=now(), refreshed=None, tracks=[], recordings={}, releases={},
                local_files=[], exports=[], price_history=[], library_folders=[])

def put(p):
    from musicharbor.retention import Retention, trim_project
    trim_project(p,Retention.model_validate(setting('retention',{})))
    payload=copy.deepcopy({k:v for k,v in p.items() if not k.startswith('_')})
    playlist={t['recording_id'] for t in p['tracks']}
    keep={rid for rid,r in p['recordings'].items() if rid in playlist or r.get('playlist_seen') or not r.get('library_identity')}
    for rel in p['releases'].values(): keep.update(rel.get('coverage',[]));keep.update(rel.get('partial',[]))
    payload['recordings']={rid:r for rid,r in payload['recordings'].items() if rid in keep}
    for rid,r in payload['recordings'].items():
        if rid in p.get('_library_recording_versions',{}):
            r['shared_version']=p['_library_recording_versions'][rid]
            # Shared evidence is loaded by identity ID; retain project decisions.
            for field in ('selected','candidates','rejected','match_evidence','identity_evidence'):
                r.pop(field,None)
    # Old snapshots retain unsaved file rows until a shared-library save succeeds.
    payload['local_files']=[f for f in payload['local_files'] if f['path'] not in p.get('_library_versions',{})]
    with connection() as c:
        c.execute('INSERT OR REPLACE INTO projects VALUES (?,?,?,?)',
                  (p['id'], p['name'], json.dumps(payload, ensure_ascii=False), now()))
    return p

def get(pid, full_library=False):
    with connection() as c:
        row = c.execute('SELECT payload FROM projects WHERE id=?', (pid,)).fetchone()
    if not row:
        raise ValueError('Project not found. Select an existing project.')
    p = json.loads(row['payload'])
    from musicharbor.identity import attach_library
    # Discard redundant legacy library-only copies before selecting related rows.
    playlist={t['recording_id'] for t in p['tracks']}
    retained=set(playlist)
    for rel in p['releases'].values(): retained.update(rel.get('coverage',[]));retained.update(rel.get('partial',[]))
    p['recordings']={rid:r for rid,r in p['recordings'].items() if rid in retained or r.get('playlist_seen') or not r.get('library_identity')}
    p['local_files']=[f for f in p.get('local_files',[]) if not (f.get('identity_id') or f.get('recording_id')) or (f.get('identity_id') or f.get('recording_id')) in p['recordings']]
    attach_library(p, library(None if full_library else p['recordings']), setting('preferences',{}))
    return p

def projects():
    with connection() as c:
        rows = c.execute('SELECT id,name,updated FROM projects ORDER BY updated DESC').fetchall()
    return [dict(r) for r in rows]

def delete(pid):
    with connection() as c:
        c.execute('DELETE FROM projects WHERE id=?', (pid,))
        c.execute('DELETE FROM jobs WHERE project=?',(pid,))

def duplicate(pid):
    p = copy.deepcopy(get(pid))
    p.update(id=uid(), name=p['name']+' (copy)', created=now())
    return put(p)

def migrate_legacy():
    legacy = Path(os.getenv('MUSICHARBOR_LEGACY') or os.getenv('PLAYLIST_PURCHASER_LEGACY', ROOT / 'playlist_purchaser.sqlite3'))
    if not legacy.exists() or legacy.resolve() == DB.resolve() or setting('legacy_migrated', False):
        return
    c = sqlite3.connect(legacy)
    c.row_factory = sqlite3.Row
    try:
        if 'payload' in [r[1] for r in c.execute('PRAGMA table_info(projects)')]:
            return
        with connection() as destination:
            destination.execute('BEGIN IMMEDIATE')
            _migrate_rows(c)
    finally:
        c.close()

def _migrate_rows(c):
        for row in c.execute('SELECT * FROM projects'):
            p = new_project(row['name'], row['storefront'])
            p['id'] = 'legacy-' + str(row['id'])
            with connection() as destination:
                if destination.execute('SELECT 1 FROM projects WHERE id=?',(p['id'],)).fetchone():
                    continue
            for t in c.execute('SELECT * FROM tracks WHERE project=?', (row['id'],)):
                rid = t['id']
                rec = dict(id=rid, title=t['title'], artist=t['artist'], album=t['album'],
                           duration=t['duration'], spotify_id=t['id'], spotify_url=t['spotify_url'],
                           explicit=None, isrc=None, included=bool(t['include']), required=False,
                           owned=bool(t['owned']), ownership_override=None, match_status='unmatched',
                           candidates=[], rejected=[], selected=None)
                p['recordings'][rid] = rec
                p['tracks'].append(dict(id=uid(), recording_id=rid))
            # Legacy matches lack version checks. Preserve products for review, without claiming coverage.
            for r in c.execute('SELECT * FROM releases WHERE project=?', (row['id'],)):
                key = 'album:' + r['id']
                p['releases'][key] = dict(id=key, catalog_id=r['id'], name=r['name'], artist=r['artist'],
                    kind=r['kind'], date=r['date'], price=r['price'], currency=r['currency'],
                    url=r['url'], artwork=r['artwork'], songs=[], coverage=[], owned=bool(r['owned']),
                    excluded=False, partial=[], checked=r['checked'], legacy_review=True)
            put(p)
        for r in c.execute('SELECT * FROM settings'):
            if setting(r['k']) is None:
                save_setting(r['k'], r['v'])
        save_setting('legacy_migrated', True)


def library(recordings_filter=None):
    with connection() as c:
        if recordings_filter is None:
            files = [json.loads(r[0]) for r in c.execute('SELECT payload FROM library_files')]
            recordings = {r[0]:json.loads(r[1]) for r in c.execute('SELECT id,payload FROM library_recordings')}
        else:
            from musicharbor.library_index import related
            files,recordings=related(c,recordings_filter)
    # Historical shared identities can still be referenced by projects even if
    # their last file was reassigned. Keep their evidence available by ID.
    return dict(files=files, recordings=recordings, folders=setting('library_folders', []))


def file_version(file):
    return hashlib.sha256(json.dumps(file,sort_keys=True).encode()).hexdigest()


def save_library(p):
    """Save changed files without overwriting another project's newer decisions."""
    baseline=p.setdefault('_library_versions',{})
    recording_baseline=p.setdefault('_library_recording_versions',{})
    updated_files={}; updated_recordings={}
    with connection() as c:
        if not c.in_transaction: c.execute('BEGIN IMMEDIATE')
        referenced={f.get('identity_id') or f.get('recording_id') for f in p['local_files']}
        for rid in referenced:
            if rid not in p['recordings']: continue
            rec=copy.deepcopy(p['recordings'][rid])
            rec.pop('shared_version',None)
            rec.update(included=False,required=False,owned=False,ownership_override=None,library_identity=True,playlist_seen=False)
            version=file_version(rec)
            if recording_baseline.get(rid)==version: continue
            current=c.execute('SELECT payload FROM library_recordings WHERE id=?',(rid,)).fetchone()
            current_version=file_version(json.loads(current[0])) if current else None
            if current_version not in (recording_baseline.get(rid),version):
                raise ValueError('This library recording changed in another project. Reload and review the latest decision before saving again.')
            c.execute('INSERT OR REPLACE INTO library_recordings VALUES (?,?)',(rid,json.dumps(rec)))
            from musicharbor.library_index import index_record
            index_record(c,rid,rec)
            updated_recordings[rid]=version
        for file in p['local_files']:
            version=file_version(file); path=file['path']
            if baseline.get(path)==version: continue
            current=c.execute('SELECT payload FROM library_files WHERE path=?',(path,)).fetchone()
            current_version=file_version(json.loads(current[0])) if current else None
            if current_version not in (baseline.get(path),version):
                raise ValueError('This file changed in another project. Reload and review its latest identity before saving again.')
            c.execute('INSERT OR REPLACE INTO library_files VALUES (?,?)',(path,json.dumps(file)))
            updated_files[path]=version
        row=c.execute("SELECT v FROM settings WHERE k='library_folders'").fetchone()
        folders=sorted(set((json.loads(row[0]) if row else [])+p.get('library_folders',[])))
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('library_folders',json.dumps(folders)))
        _TRANSACTION.after_commit.append(lambda: baseline.update(updated_files))
        _TRANSACTION.after_commit.append(lambda: recording_baseline.update(updated_recordings))


def put_job(jid,job):
    payload={k:v for k,v in job.items() if k!='task'}
    with connection() as c:
        c.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?)',(jid,job['project'],json.dumps(payload)))


def jobs(pid):
    with connection() as c:
        rows=c.execute('SELECT id,payload FROM jobs WHERE project=? ORDER BY rowid DESC',(pid,)).fetchall()
    return [dict(json.loads(row['payload']),id=row['id']) for row in rows]


def dismiss_job(jid):
    with connection() as c: c.execute('DELETE FROM jobs WHERE id=?',(jid,))


def interrupt_jobs():
    with connection() as c:
        for row in c.execute('SELECT id,payload FROM jobs').fetchall():
            job=json.loads(row['payload'])
            if job['status'] in ('queued','running'):
                job.update(status='cancelled',message='App stopped before this operation finished. Retry to reuse cached results.')
                for stage in job.get('stages',[]):
                    if stage['status']=='running': stage['status']='cancelled'
                c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(job),row['id']))
