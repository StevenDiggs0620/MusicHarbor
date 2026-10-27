"""Group chosen purchases by their parent release without changing the plan."""
from collections import defaultdict
from optimizer import cents


def purchase_groups(p, ids, play_counts=None):
    playlist = {t['recording_id'] for t in p['tracks']}
    def individual(r):
        return r.get('purchase_type') == 'track' or r['id'].startswith('track:') or r.get('kind') == 'individual song'
    def song(r):
        return (r.get('songs') or [{}])[0]
    def track_key(r):
        return (r.get('disc_number') or song(r).get('discNumber') or 1,
                r.get('track_number') or song(r).get('trackNumber') or 9999, r['id'])

    by_release = defaultdict(list)
    for rid in ids:
        if rid not in p['releases']:
            continue
        r = p['releases'][rid]
        cid = str(r.get('release_id') or song(r).get('collectionId') or
                  (rid.removeprefix('album:') if not individual(r) else rid))
        by_release[cid].append(r)

    groups = []
    for cid, items in by_release.items():
        whole = [r for r in items if not individual(r)]
        parent = p['releases'].get('album:' + cid) or (whole[0] if whole else {})
        ordered = sorted(items, key=lambda r: (individual(r), track_key(r)))
        first = ordered[0]
        name = parent.get('name') or first.get('release_name') or song(first).get('collectionName') or 'Unknown album'
        coverage = set().union(*(set(r.get('coverage', [])) for r in items)) & playlist
        # Every release competes equally, regardless of release or purchase type.
        # Count unique playlist recordings represented by the displayed group.
        count = len(coverage)
        plays = sum(play_counts.get(rid,0) for rid in coverage) if play_counts is not None else None
        prices = [cents(r.get('price')) for r in items]
        price = sum(prices) if all(value is not None for value in prices) else float('inf')
        # Missing history preserves track-count ordering. A known zero instead
        # goes after played releases and ignores track count within that group.
        unplayed = plays == 0
        key = (unplayed, 0 if unplayed else -count, -(plays or 0), price,
               (parent.get('artist') or first.get('artist', '')).casefold(), name.casefold(), cid)
        suffix = 'full release' if whole else f"{len(items)} individual " + ('track' if len(items) == 1 else 'tracks')
        groups.append((key, dict(label=f'{name} — {suffix}', type='releases' if whole else 'tracks',
                                 release_ids=[r['id'] for r in ordered], play_count=plays)))
    return [group for _, group in sorted(groups, key=lambda pair: pair[0])]
