"""Conservative recording matching. Releases never define recording identity."""
import re
import unicodedata
from difflib import SequenceMatcher

VERSION_WORDS = ('live', 'acoustic', 'remix', 'remaster', 'radio edit', 'instrumental', 'karaoke', 'demo', 'sped up', 'slowed', 're recorded', 'rerecorded', 're recording', 'clean', 'explicit')

def normalize(text):
    text = unicodedata.normalize('NFKD', text or '').casefold().replace('&', ' and ')
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())

def title_base(title):
    title = re.sub(r'\s*[\[(](?:feat\.?|ft\.?|featuring)\s+.*?[\])]', '', title or '', flags=re.I)
    title = re.sub(r'\s+(?:feat\.?|ft\.?|featuring)\s+.*$', '', title, flags=re.I)
    return normalize(title)

def comparison_title(title, prefs=None):
    prefs = prefs or {}
    text = title_base(title)
    if prefs.get('remasters_equivalent'):
        text = re.sub(r'\b(?:(?:19|20)\d{2}\s+)?remaster(?:ed|ing)?(?:\s+(?:19|20)\d{2})?\b', ' ', text)
    if prefs.get('clean_explicit_equivalent'):
        text = re.sub(r'\b(?:clean|explicit)\b', ' ', text)
    return ' '.join(text.split())

def versions(title):
    n = normalize(title).replace('remastered', 'remaster').replace('remastering', 'remaster')
    return {v for v in VERSION_WORDS if re.search(r'\b' + v + r'\b', n)}

def artists(text):
    return set(filter(None, (normalize(x) for x in re.split(r'\s*(?:,|&|\bfeat\.?\s|\bft\.?\s|\bfeaturing\s|\band\b)\s*', text or '', flags=re.I))))

def song_data(s):
    explicit = s.get('trackExplicitness')
    return dict(title=s.get('trackName', ''), artist=s.get('artistName', ''),
                album=s.get('collectionName', ''), duration=(s.get('trackTimeMillis') or 0)/1000,
                explicit=True if explicit == 'explicit' else False if explicit in ('cleaned','notExplicit') else None,
                isrc=s.get('isrc'), itunes_track_id=str(s['trackId']) if s.get('trackId') else None)

def score(a, b, prefs=None):
    prefs = prefs or {}
    av, bv = versions(a.get('title')), versions(b.get('title'))
    if prefs.get('remasters_equivalent'):
        av.discard('remaster'); bv.discard('remaster')
    if prefs.get('clean_explicit_equivalent'):
        av -= {'clean', 'explicit'}; bv -= {'clean', 'explicit'}
    reasons = []
    if av != bv:
        return dict(score=0, confidence='low', reasons=['Different recording version labels'], compatible=False)
    if not prefs.get('clean_explicit_equivalent') and a.get('explicit') is not None and b.get('explicit') is not None and a['explicit'] != b['explicit']:
        return dict(score=0, confidence='low', reasons=['Clean / explicit versions differ'], compatible=False)
    ta, tb = comparison_title(a.get('title'), prefs), comparison_title(b.get('title'), prefs)
    title = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0
    aa, ba = artists(a.get('artist')), artists(b.get('artist'))
    artist = len(aa & ba) / max(1, len(aa | ba))
    # Primary artist must agree. A featured artist alone is insufficient.
    primary_a = normalize(re.split(r',|&|\band\b|\bfeat\.?\s|\bft\.?\s|\bfeaturing\s', a.get('artist',''), flags=re.I)[0])
    primary_b = normalize(re.split(r',|&|\band\b|\bfeat\.?\s|\bft\.?\s|\bfeaturing\s', b.get('artist',''), flags=re.I)[0])
    primary = primary_a == primary_b and bool(primary_a)
    dur_a, dur_b = a.get('duration') or 0, b.get('duration') or 0
    delta = abs(dur_a - dur_b)
    duration = max(0, 1 - delta / 15) if dur_a and dur_b else 0
    value = round(55 * title + 30 * artist + 15 * duration)
    same_listing = bool(a.get('itunes_track_id') and b.get('itunes_track_id') and str(a['itunes_track_id']) == str(b['itunes_track_id']))
    same_mbid = bool(a.get('musicbrainz_id') and a.get('musicbrainz_id') == b.get('musicbrainz_id'))
    same_isrc = bool(a.get('isrc') and b.get('isrc') and a['isrc'].upper() == b['isrc'].upper())
    if same_listing:
        reasons.append('Embedded iTunes track ID agrees')
    if same_mbid:
        reasons.append('MusicBrainz recording ID agrees')
    if same_isrc or same_mbid or same_listing:
        value = max(value, 99)
        if same_isrc: reasons.append('ISRC agrees')
    reasons.extend([f'Title similarity {title:.0%}', f'Artist overlap {artist:.0%}',
                    f'Duration differs by {delta:.1f}s' if dur_a and dur_b else 'Duration unavailable'])
    high = (title == 1 and primary and artist >= .5 and dur_a and dur_b and delta <= 3) or ((same_isrc or same_mbid or same_listing) and title >= .8 and primary and (not dur_a or not dur_b or delta <= 3))
    if aa != ba and not (same_isrc or same_mbid or same_listing):
        high = False
        reasons.append('Artist credits differ; review before accepting a partial artist-name match')
    if not prefs.get('clean_explicit_equivalent') and (a.get('explicit') is None or b.get('explicit') is None):
        high = high and (same_isrc or same_mbid or same_listing)
        reasons.append('Explicitness unknown; shared recording identifier used' if high else 'Explicitness is unknown on one side; review the version')
    if a.get('musicbrainz_id') and b.get('musicbrainz_id') and not same_mbid:
        high = False
        reasons.append('Different MusicBrainz recording IDs')
    if a.get('isrc') and b.get('isrc') and not same_isrc:
        high = False
        reasons.append('Different ISRCs; review recording identity')
    if (av or bv) and ta != tb:
        high = False  # Two different remix/live qualifiers need a human decision.
    confidence = 'high' if high else 'medium' if value >= 65 and primary else 'low'
    return dict(score=value, confidence=confidence, reasons=reasons, compatible=True,
                state='EXACT' if high and (same_isrc or same_mbid or same_listing) else 'HIGH_CONFIDENCE' if high else 'NEEDS_REVIEW',
                identifier_match=bool(same_isrc or same_mbid or same_listing))

def owned_ids(p):
    """Check each file once, then apply explicit project overrides last."""
    from pathlib import Path
    owned={f['recording_id'] for f in p.get('local_files',[]) if f.get('recording_id') and f.get('status')=='matched' and Path(f['path']).is_file()}
    for rel in p['releases'].values():
        owned.update(rel.get('partial',[]))
        if rel.get('owned'): owned.update(rel.get('coverage',[]))
    for rid,r in p['recordings'].items():
        if r.get('owned'): owned.add(rid)
        if r.get('ownership_override') is True: owned.add(rid)
        elif r.get('ownership_override') is False: owned.discard(rid)
    return owned

def rec_owned(p, rid):
    r = p['recordings'][rid]
    if r.get('ownership_override') is not None:
        return bool(r['ownership_override'])
    from pathlib import Path
    local_owned = any(f.get('recording_id') == rid and f.get('status') == 'matched'
                      and Path(f['path']).is_file() for f in p.get('local_files', []))
    return bool(local_owned or r.get('owned') or any(rid in x.get('coverage', []) and (x.get('owned') or rid in x.get('partial', [])) for x in p['releases'].values()))

def rebuild_coverage(p, prefs, progress=None):
    """Index candidate songs before scoring; retain the original matching rules."""
    from collections import defaultdict
    import json
    by_title=defaultdict(set); by_isrc=defaultdict(set); by_id=defaultdict(set)
    songs={}; release_keys={}
    def key_title(data):
        return comparison_title(data.get('title'), prefs)
    for rel in p['releases'].values():
        keys=[]
        for song in rel.get('songs',[]):
            data=song_data(song)
            key=json.dumps([str(song.get('trackId')),data],sort_keys=True)
            keys.append(key)
            if key in songs: continue
            songs[key]=(song,data)
            by_title[key_title(data)].add(key)
            if data.get('isrc'): by_isrc[data['isrc'].upper()].add(key)
            by_id[str(song.get('trackId'))].add(key)
        release_keys[rel['id']]=keys
    covered=defaultdict(set)
    records=list(p['recordings'].items())
    for i,(rid,rec) in enumerate(records):
        if rec.get('match_status') in ('confirmed','high') and rec.get('selected'):
            selected=rec['selected']; data=song_data(selected)
            possible=by_title[key_title(data)] | by_id[str(selected.get('trackId'))]
            if data.get('isrc'): possible=possible | by_isrc[data['isrc'].upper()]
            rejected=set(rec.get('rejected',[]))
            for key in possible:
                song,other=songs[key]
                if str(song.get('trackId')) in rejected: continue
                if str(song.get('trackId'))==str(selected.get('trackId')) or score(data,other,prefs)['confidence']=='high':
                    covered[key].add(rid)
        if progress: progress(i+1,len(records))
    order={rid:i for i,(rid,_) in enumerate(records)}
    for rel in p['releases'].values():
        ids=set().union(*(covered[k] for k in release_keys[rel['id']]))
        rel['coverage']=sorted(ids,key=order.get)
