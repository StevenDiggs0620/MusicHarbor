"""Shared recording decisions for playlist entries, local files and catalog listings.

Catalog IDs identify listings, never canonical recordings. Canonical IDs are
opaque IDs; occurrences and files retain their own metadata and identities.
"""
import copy
from pathlib import Path
from matching import score, song_data, title_base, comparison_title

ACCEPTED = {'high', 'confirmed'}


def playlist_ids(p):
    return {t['recording_id'] for t in p['tracks']}


def reference(rec):
    return song_data(rec['selected']) if rec.get('selected') and rec.get('match_status') in ACCEPTED else rec


def equivalent(a, b, prefs=None):
    # Explicit user choices are authoritative references, but conflicting source
    # identifiers still prevent silent consolidation of two sources.
    for key in ('isrc', 'musicbrainz_id'):
        if a.get(key) and b.get(key) and a[key].casefold() != b[key].casefold():
            return False
    if any(str(other.get('selected', {}).get('trackId')) in rec.get('rejected', [])
           for rec,other in ((a,b),(b,a)) if other.get('selected')):
        return False
    evidence = score(a, b, prefs)
    if not evidence['compatible']:
        return False
    if evidence['confidence'] == 'high' and evidence.get('identifier_match'):
        return True
    if a.get('selected') and b.get('selected') and a.get('match_status') in ACCEPTED and b.get('match_status') in ACCEPTED:
        x, y = a['selected'], b['selected']
        return (str(x.get('trackId')) == str(y.get('trackId')) or
                score(song_data(x), song_data(y), prefs)['confidence'] == 'high')
    return False


def decide(source, songs, rejected=(), prefs=None):
    candidates = sorted((dict(song=s, **score(source, song_data(s), prefs)) for s in songs),
                        key=lambda c: (-c['score'], str(c['song'].get('trackId'))))
    eligible = [c for c in candidates if str(c['song'].get('trackId')) not in rejected and c['compatible']]
    top = eligible[0] if eligible else None
    state = 'UNMATCHED' if not top or top['confidence'] == 'low' else 'NEEDS_REVIEW'
    selected = None
    evidence = dict(score=top['score'], reasons=list(top['reasons'])) if top else dict(score=0, reasons=['No compatible catalog candidates'])
    if top and top['confidence'] == 'high':
        # Equivalent album/single listings are one possibility. Close competing
        # versions are real ambiguity, even if the first result scored highly.
        rivals = [c for c in eligible[1:] if c['score'] >= top['score'] - 5
                  and score(song_data(top['song']), song_data(c['song']), prefs)['confidence'] != 'high']
        if rivals:
            evidence['reasons'].append('Several competing recordings have similar scores')
        else:
            state = top.get('state', 'HIGH_CONFIDENCE')
            selected = top['song']
    return dict(candidates=candidates, selected=selected, resolution_state=state,
                match_status='high' if selected else 'unmatched' if state == 'UNMATCHED' else 'medium',
                match_evidence=evidence)


def merge(p, old, target):
    if old == target: return
    overrides=p.get('export_file_overrides',{})
    if old in overrides:
        overrides.setdefault(target,overrides.pop(old))
    a, b = p['recordings'][old], p['recordings'][target]
    was_playlist = old in playlist_ids(p)
    target_playlist = target in playlist_ids(p)
    if was_playlist and not target_playlist:
        for key in ('included', 'required', 'ownership_override'):
            b[key] = a.get(key)
    else:
        b['included'] = a.get('included', False) or b.get('included', False)
        b['required'] = a.get('required', False) or b.get('required', False)
        if b.get('ownership_override') is None:
            b['ownership_override'] = a.get('ownership_override')
    b['owned'] = a.get('owned', False) or b.get('owned', False)
    b['playlist_seen'] = a.get('playlist_seen', False) or b.get('playlist_seen', False) or was_playlist or target_playlist
    if a.get('match_status') == 'confirmed' or not b.get('selected'):
        for key in ('selected', 'match_status', 'resolution_state', 'match_evidence', 'candidates'):
            if key in a: b[key] = a[key]
    b['rejected'] = sorted(set(a.get('rejected', []) + b.get('rejected', [])))
    for source in a.get('source_identities', []):
        if source not in b.setdefault('source_identities', []): b['source_identities'].append(source)
    if a.get('catalog_searched_at') and not b.get('catalog_searched_at'):
        b['catalog_searched_at'] = a['catalog_searched_at']
    for key in ('isrc', 'musicbrainz_id', 'spotify_id', 'spotify_url'):
        if not b.get(key) and a.get(key): b[key] = a[key]
    for entry in p['tracks']:
        if entry['recording_id'] == old:
            entry.setdefault('source_metadata', {k:a.get(k) for k in ('title','artist','album','duration','explicit','isrc','spotify_id')})
            entry['recording_id'] = target
    for f in p['local_files']:
        for key in ('recording_id', 'identity_id'):
            if f.get(key) == old: f[key] = target
    for rel in p['releases'].values():
        for key in ('coverage', 'partial'):
            rel[key] = list(dict.fromkeys(target if rid == old else rid for rid in rel.get(key, [])))
    del p['recordings'][old]


def consolidate(p, prefs=None):
    remap = {rid: rid for rid in p['recordings']}
    ids = sorted(p['recordings'], key=lambda rid: not p['recordings'][rid].get('library_identity', False))
    buckets = {}
    for i, rid in enumerate(ids):
        if rid not in p['recordings']: continue
        a = p['recordings'][rid]
        key = comparison_title(reference(a).get('title'), prefs)
        previous = buckets.setdefault(key, [])
        for other in previous:
            if other not in p['recordings']: continue
            b = p['recordings'][other]
            choices=p.get('export_file_overrides',{})
            if choices.get(rid) and choices.get(other) and choices[rid]!=choices[other]:
                continue
            # Conflicting user decisions deserve review, not silent deletion.
            if any(a.get(k) is not None and b.get(k) is not None and a.get(k) != b.get(k)
                   for k in ('ownership_override',)):
                continue
            if equivalent(a, b, prefs):
                merge(p, rid, other)
                for source, target in remap.items():
                    if target == rid: remap[source] = other
                break
        else:
            previous.append(rid)
    sync_files(p)
    return remap


def sync_files(p):
    for f in p['local_files']:
        rid = f.get('identity_id') or f.get('recording_id')
        rec = p['recordings'].get(rid)
        if not Path(f['path']).is_file():
            f['status'] = 'missing'
            continue
        if f.get('error'): continue
        if rec and (rec.get('match_status') in ACCEPTED or rec.get('resolution_state') == 'EXACT'):
            f.update(recording_id=rid, identity_id=rid, status='matched',
                     resolution_state=rec.get('resolution_state', 'HIGH_CONFIDENCE'),
                     match_evidence=rec.get('match_evidence', {}))
        elif not f.get('manual'):
            f.update(recording_id=None, status='review' if rec and rec.get('candidates') else 'unmatched',
                     resolution_state=rec.get('resolution_state', 'UNMATCHED') if rec else 'UNMATCHED')


def attach_library(p, library, prefs=None):
    from store import file_version
    def evidence(rec):
        return (copy.deepcopy(rec.get('selected')),rec.get('match_status'),list(rec.get('rejected',[])))
    before={rid:evidence(p['recordings'][rid]) for rid in playlist_ids(p)}
    current_shared={rid for rid,r in p['recordings'].items() if r.get('shared_version') and rid in library['recordings'] and r['shared_version']==file_version(library['recordings'][rid])}
    p['_library_versions']={f['path']:file_version(f) for f in library['files']}
    p['_library_recording_versions']={rid:file_version(r) for rid,r in library['recordings'].items()}
    existing = {f['path']:f for f in p['local_files']}
    for f in library['files']:
        existing[f['path']] = copy.deepcopy(f)
    p['local_files'] = list(existing.values())
    # Upgrade legacy unmatched files into independent source identities. This is
    # deterministic and does not turn old playlist-only suggestions into matches.
    for f in p['local_files']:
        if not f.get('identity_id') and not f.get('recording_id'):
            rid='local:'+f['id']
            f['identity_id']=rid
            p['recordings'].setdefault(rid, dict(
                id=rid, **{k:f.get(k) for k in ('title','artist','album','duration','explicit','isrc')},
                included=False,required=False,owned=False,ownership_override=None,
                match_status='unmatched',resolution_state='UNMATCHED',selected=None,
                candidates=[c for c in f.get('candidates',[]) if 'song' in c],rejected=[],
                source_type='local_file',library_identity=True))
    for rid, rec in library['recordings'].items():
        if rid not in p['recordings']:
            p['recordings'][rid] = dict(copy.deepcopy(rec), included=False, required=False, owned=False, ownership_override=None, playlist_seen=False)
        else:
            current = p['recordings'][rid]
            # Shared evidence is authoritative; playlist decisions stay local.
            for key in ('title','artist','album','duration','explicit','isrc','musicbrainz_id',
                        'itunes_track_id','selected','candidates','rejected','match_status',
                        'resolution_state','match_evidence','identity_evidence','resolution_error'):
                if key in rec: current[key] = copy.deepcopy(rec[key])
                elif key in ('resolution_error',): current.pop(key, None)
    p['library_folders'] = sorted(set(p.get('library_folders', []) + library.get('folders', [])))
    remap=consolidate(p,prefs)
    if any((rid not in current_shared or remap[rid]!=rid) and value != evidence(p['recordings'][remap[rid]]) for rid,value in before.items()):
        from matching import rebuild_coverage
        rebuild_coverage(p,prefs or {})


def summary(p):
    ids = playlist_ids(p)
    counts = {state:0 for state in ('EXACT','HIGH_CONFIDENCE','NEEDS_REVIEW','UNMATCHED')}
    for rid in ids:
        r = p['recordings'][rid]
        state = r.get('resolution_state') or ('HIGH_CONFIDENCE' if r.get('match_status') in ACCEPTED else 'NEEDS_REVIEW' if r.get('candidates') else 'UNMATCHED')
        counts[state] = counts.get(state, 0) + 1
    return dict(entries=len(p['tracks']), recordings=len(ids), duplicate_appearances=len(p['tracks'])-len(ids), states=counts)
