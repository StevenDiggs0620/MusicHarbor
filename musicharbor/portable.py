"""Explicit project-only and complete-library portable snapshots."""
import copy
import json
from pathlib import Path
from pydantic import Field
from musicharbor import backup_schema as schema
import musicharbor.store as store

class LocalFile(schema.Source):
    id: str
    path: str = Field(min_length=1,max_length=32768)
    recording_id: str | None = None
    identity_id: str | None = None
    candidates: list[schema.Candidate] = Field(default_factory=list)
    manual: bool = False
    status: str = 'unmatched'
    resolution_state: str | None = None
    match_evidence: schema.Evidence = Field(default_factory=schema.Evidence)
    bitrate: float = Field(default=0,ge=0)
    sample_rate: float = Field(default=0,ge=0)
    bits_per_sample: float = Field(default=0,ge=0)

class Library(schema.Model):
    files: list[LocalFile]
    recordings: dict[str,schema.Recording]
    folders: list[str]

def project_only(p):
    p=copy.deepcopy({k:v for k,v in p.items() if not k.startswith('_')})
    ids={t['recording_id'] for t in p['tracks']}
    p['recordings']={rid:r for rid,r in p['recordings'].items() if rid in ids}
    p['releases']={key:r for key,r in p['releases'].items() if set(r.get('coverage',[]))&ids}
    for r in p['releases'].values():
        for key in ('coverage','partial'): r[key]=[rid for rid in r.get(key,[]) if rid in ids]
    p['price_history']=[x for x in p.get('price_history',[]) if x['release_id'] in p['releases']]
    p.update(local_files=[],library_folders=[],export_file_overrides={})
    # Export history options can contain absolute path replacements.
    for entry in p.get('exports',[]): entry.pop('options',None)
    return p

def encode(scope,pid):
    if scope=='project': return schema.encode(project_only(store.get(pid)))
    with store.connection() as c:
        c.execute('BEGIN')
        projects=[{k:v for k,v in store.get(row['id']).items() if not k.startswith('_')} for row in store.projects()]
        library=store.library()
        Library.model_validate(library)
        for p in projects: schema.validate(dict(format='musicharbor',version=2,project=p))
        blob=dict(format='musicharbor-library',version=1,projects=projects,library=library)
        data=json.dumps(blob,ensure_ascii=False,allow_nan=False).encode()
    if len(data)>schema.MAX_BYTES: raise ValueError('This backup exceeds the 128 MB limit. Use project-only backups or reduce retained history.')
    return data

def restore_library(blob):
    from musicharbor.identity import sync_files
    from musicharbor.matching import rebuild_coverage
    if blob.get('version')!=1 or not isinstance(blob.get('projects'),list): raise ValueError('Invalid full-library backup.')
    try:
        library=Library.model_validate(blob['library']).model_dump()
        projects=[schema.validate(dict(format='musicharbor',version=2,project=p)) for p in blob['projects']]
        ids=set(library['recordings'])
        for rid,r in library['recordings'].items():
            if r['id']!=rid: raise ValueError('Invalid recording reference.')
        for file in library['files']:
            if any(file.get(k) and file[k] not in ids for k in ('identity_id','recording_id')): raise ValueError('Invalid file reference.')
    except (ValueError,KeyError,TypeError) as exc: raise ValueError('Invalid full-library backup data.') from exc
    with store.connection() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=store.library();paths={f['path'] for f in existing['files']}
        # Restore additively; never overwrite existing shared file decisions.
        remap={rid:store.uid() for rid in ids}
        shared=store.new_project()
        shared['recordings']={remap[rid]:dict(r,id=remap[rid]) for rid,r in library['recordings'].items()}
        for file in library['files']:
            if file['path'] in paths: continue
            paths.add(file['path']);file['id']=store.uid()
            for key in ('identity_id','recording_id'):
                if file.get(key): file[key]=remap[file[key]]
            # Backups carry identity evidence; ownership requires a fresh scan.
            file.update(status='missing',error='Restored file: scan its folder to verify the local copy.')
            file.pop('fingerprint',None)
            shared['local_files'].append(file)
        shared['library_folders']=library['folders']
        store.save_library(shared)
        restored=[]
        for p in projects:
            p.update(id=store.uid(),name=p['name']+' (restored)',created=store.now())
            rebuild_coverage(p,store.setting('preferences',{}));store.put(p);restored.append(p)
    return dict(id=restored[0]['id'] if restored else None,restored_projects=len(restored),restored_files=len(shared['local_files']))
