"""Update playlist occurrences while retaining expensive catalog and user decisions."""
from collections import Counter, defaultdict
from copy import deepcopy
import json

import musicharbor.store as store
from musicharbor.matching import normalize, score

FIELDS = ('title', 'artist', 'album', 'duration', 'explicit', 'isrc', 'spotify_id')


def same_source(a, b):
    """Strong source ID, or identical metadata; never merge competing versions."""
    evidence = score(a, b)
    if not evidence['compatible']:
        return False
    if a.get('isrc') and b.get('isrc') and a['isrc'].upper() != b['isrc'].upper():
        return False
    if a.get('duration') and b.get('duration') and abs(a['duration']-b['duration']) > 3:
        return False
    same_spotify = a.get('spotify_id') and a.get('spotify_id') == b.get('spotify_id')
    if same_spotify:
        return normalize(a.get('title')) == normalize(b.get('title')) and normalize(a.get('artist')) == normalize(b.get('artist'))
    if a.get('isrc') and b.get('isrc') and a['isrc'].upper() == b['isrc'].upper():
        return evidence['confidence'] == 'high'
    # With no shared identifier, exact metadata is a conservative reuse fallback.
    return (not a.get('spotify_id') and not b.get('spotify_id') and
            all(a.get(k) == b.get(k) for k in FIELDS) and bool(a.get('title')) and bool(a.get('artist')))


def merge_playlist(p, incoming, mode):
    if mode not in ('add', 'replace'):
        raise ValueError('Choose Add to playlist or Replace playlist.')
    old_count = len(p['tracks'])
    known_ids = set(p['recordings'])
    existing = Counter(t['recording_id'] for t in p['tracks'])
    # Retain source aliases even if canonical consolidation later chooses another ID.
    for entry in p['tracks']:
        rec = p['recordings'][entry['recording_id']]
        rec['playlist_seen'] = True
        metadata = entry.get('source_metadata') or {k: rec.get(k) for k in FIELDS}
        history = rec.setdefault('source_identities', [])
        if metadata not in history:
            history.append(deepcopy(metadata))
    index = defaultdict(list)
    indexed = set()
    def index_record(rid, rec):
        for source in [rec, *rec.get('source_identities', [])]:
            signature = (rid, json.dumps({k: source.get(k) for k in FIELDS}, sort_keys=True))
            if signature in indexed: continue
            indexed.add(signature)
            keys = [('spotify', source.get('spotify_id')), ('isrc', (source.get('isrc') or '').upper()),
                    ('title', normalize(source.get('title')))]
            for key in keys:
                if key[1]: index[key].append((rid, source))
    for rid, rec in p['recordings'].items():
        index_record(rid, rec)
    remap = {}; reused = set(); added = set()
    claimed = Counter()
    incoming_counts = Counter(t['recording_id'] for t in incoming['tracks'])
    for source_id, rec in incoming['recordings'].items():
        candidates = index.get(('spotify', rec.get('spotify_id')), []) + index.get(('isrc', (rec.get('isrc') or '').upper()), []) + index.get(('title', normalize(rec.get('title'))), [])
        matches = {rid for rid, old in candidates if same_source(rec, old)}
        if not rec.get('spotify_id') and not rec.get('isrc'):
            # Pair repeated source rows one-to-one without merging their identities.
            matches = {rid for rid in matches if claimed[rid] < max(1,existing[rid])}
            if matches: matches = {min(matches,key=lambda rid:(not bool(existing[rid]),rid))}
        if len(matches) == 1:
            rid = matches.pop()
            if rid in known_ids: reused.add(rid)
        else:
            rid = store.uid(); added.add(rid)
            p['recordings'][rid] = dict(deepcopy(rec), id=rid)
        target = p['recordings'][rid]
        if not rec.get('spotify_id') and not rec.get('isrc'): claimed[rid] += incoming_counts[source_id]
        if not target.get('playlist_seen') and (target.get('library_identity') or target.get('source_type') == 'local_file'):
            target.update(included=True, required=False)
        target['playlist_seen'] = True
        metadata = {k: rec.get(k) for k in FIELDS}
        history = target.setdefault('source_identities', [])
        if metadata not in history: history.append(metadata)
        remap[source_id] = rid
        index_record(rid, target)
    incoming_entries = [dict(deepcopy(t), id=store.uid(), recording_id=remap[t['recording_id']]) for t in incoming['tracks']]
    if mode == 'replace':
        p['tracks'] = incoming_entries
        added_entries = len(incoming_entries)
    else:
        seen = Counter(); added_entries = 0
        for entry in incoming_entries:
            rid = entry['recording_id']; seen[rid] += 1
            if seen[rid] > existing[rid]:
                p['tracks'].append(entry); added_entries += 1
    p['refreshed'] = store.now()
    result = dict(mode=mode, before=old_count, incoming=len(incoming_entries), count=len(p['tracks']),
                  added_entries=added_entries, reused_recordings=len(reused), new_recordings=len(added))
    p['last_playlist_update'] = result
    return result
