"""Playlist-scoped owned collection presentation; never changes ownership."""
from copy import deepcopy
from collections import defaultdict

from musicharbor.matching import normalize, owned_ids as effective_owned_ids
from musicharbor.optimizer import CURRENCIES, cents, release_preference
from musicharbor.purchase_order import purchase_groups


def owned_collection(p, play_counts=None):
    playlist = {t['recording_id'] for t in p['tracks']}
    owned = sorted(playlist & effective_owned_ids(p))
    currency = CURRENCIES[p['storefront']]
    owned_ids = set(owned)
    options = defaultdict(list)
    for product in p['releases'].values():
        if product.get('purchase_type') == 'track' or product['id'].startswith('track:') or product.get('kind') == 'individual song':
            for rid in set(product.get('coverage', [])) & owned_ids:
                options[rid].append(product)
    view = dict(tracks=p['tracks'], releases={})
    total = 0; unpriced = 0; whole = {}
    for rid in owned:
        rec = p['recordings'][rid]
        def key(r):
            parent = p['releases'].get('album:'+str(r.get('release_id')), {})
            actual = r.get('owned') or parent.get('owned') or rid in parent.get('partial', [])
            price = cents(r.get('price')) if r.get('currency') == currency else None
            return (not actual, release_preference(r), price is None, price if price is not None else 0, r['id'])
        if options[rid]:
            item = deepcopy(min(options[rid], key=key))
        else:
            album = rec.get('album') or 'Unknown album'
            item = dict(name=rec['title'], artist=rec.get('artist',''), release_name=album,
                        release_id='metadata:'+normalize(rec.get('artist'))+':'+normalize(album),
                        price=None, currency=currency, artwork='', songs=[], kind='individual song',
                        purchase_type='track', release_kind='unknown', url='')
        price = cents(item.get('price')) if item.get('currency') == currency else None
        if price is None: unpriced += 1
        else: total += price
        item.update(id='owned:'+rid, recording_id=rid, coverage=[rid], owned=True, excluded=False, partial=[],
                    price=price/100 if price is not None else None, currency=currency)
        cid = str(item.get('release_id') or (item.get('songs') or [{}])[0].get('collectionId') or 'metadata:'+normalize(item.get('artist'))+':'+normalize(item.get('release_name') or rec.get('album')))
        item['release_id'] = cid
        parent = p['releases'].get('album:'+cid)
        if parent:
            view['releases']['album:'+cid] = deepcopy(parent)
            if not item.get('artwork'): item['artwork'] = parent.get('artwork','')
        if parent and parent.get('owned'):
            if cid not in whole:
                whole[cid] = dict(deepcopy(parent), id='owned-album:'+cid, coverage=[], price=0,
                                  currency=currency, owned=True, excluded=False, partial=[], unpriced=0)
            group = whole[cid]; group['coverage'].append(rid)
            group['unpriced'] += price is None
            group['price'] += (price or 0)/100
        else:
            view['releases'][item['id']] = item
    for cid, item in whole.items():
        parent = p['releases']['album:'+cid]
        full_price = cents(parent.get('price')) if parent.get('currency') == currency else None
        item['price'] = full_price/100 if full_price is not None else None
        view['releases'][item['id']] = item
    selected = [key for key in view['releases'] if key.startswith(('owned:', 'owned-album:'))]
    groups = purchase_groups(view,selected,play_counts)
    return dict(count=len(owned), total=len(playlist), percent=round(100*len(owned)/len(playlist),1) if playlist else 0,
                value=total/100, currency=currency, unpriced=unpriced, groups=groups,
                releases={key:view['releases'][key] for key in selected})
