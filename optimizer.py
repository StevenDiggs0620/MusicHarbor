"""Integer set-cover optimization with explicit solver status and price validation."""
import math
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from matching import rec_owned, normalize, owned_ids
from identity import playlist_ids

CURRENCIES = {'us': 'USD', 'ca': 'CAD', 'gb': 'GBP'}

def cents(price):
    if isinstance(price, bool) or price is None:
        return None
    try:
        value = float(price)
        if not math.isfinite(value) or value < 0:
            return None
        return int((Decimal(str(price)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError):
        return None

def calculate(p, strategy='cheapest', purchase_penalty=1.0, budget=None, artist='', play_counts=None, owned=None, time_budget=20):
    deadline=time.monotonic()+time_budget
    owned=owned_ids(p) if owned is None else owned
    playlist = playlist_ids(p)
    wanted = {rid for rid, r in p['recordings'].items() if rid in playlist and r.get('included', True) and rid not in owned}
    currency = CURRENCIES[p['storefront']]
    options = []
    for r in p['releases'].values():
        price = cents(r.get('price'))
        cover = set(r.get('coverage', [])) & wanted
        if cover and price is not None and r.get('currency') == currency and not r.get('excluded') and not r.get('owned'):
            options.append((r, cover, price))
    options = rank_album_options(p, options)
    # Equal-price products with identical required coverage are interchangeable
    # for every strategy. Retain only the best release class among those ties.
    best = {}
    for r,cover,price in options:
        key = (frozenset(cover),price)
        best[key] = min(best.get(key,5),release_preference(r))
    options = [(r,cover,price) for r,cover,price in options
               if release_preference(r)==best[(frozenset(cover),price)]]
    covered = set().union(*(s for _,s,_ in options)) if options else set()
    missing = sorted(wanted - covered)
    base = dict(currency=currency, remaining=len(wanted), unavailable=missing,
                complete=False, optimal=False, release_ids=[], cost=0, covered=0,
                coverage_percent=100 if not wanted else 0, strategy=strategy)
    if not wanted:
        return dict(base, complete=True, optimal=True, status='Nothing left to purchase.')
    if strategy == 'best-value' and any(p['recordings'][rid].get('required') for rid in missing):
        return dict(base, status='A required recording has no usable priced match. Review it before calculating a budget plan.')
    if not options:
        return dict(base, status='No priced, confirmed purchase options. Review matches or refresh prices.')
    if strategy in ('most-songs','songs-per-dollar','artist'):
        remaining = wanted.copy(); chosen=[]; total=0
        while remaining:
            if time.monotonic()>=deadline: raise ValueError('Planning time limit reached. Try a smaller project.')
            useful=[o for o in options if o[1] & remaining and o[0]['id'] not in chosen]
            if not useful: break
            def key(o):
                r,s,price=o; n=len(s & remaining)
                date=r.get('date') or ''
                if strategy == 'songs-per-dollar':
                    rank = n/price if price else float('inf')
                elif strategy == 'artist':
                    rank = sum(artist.casefold() in p['recordings'][rid]['artist'].casefold() for rid in s & remaining)
                else: rank=n
                return (rank, n if strategy == 'artist' else 0, -price, -release_preference(r), date, r['id'])
            r,s,price=max(useful,key=key)
            chosen.append(r['id']); total += price; remaining -= s
        n=len(wanted-remaining)
        return dict(base, release_ids=chosen, cost=total/100, covered=n, complete=not remaining,
                    coverage_percent=round(100*n/len(wanted),1), status='Purchase priority queue; recalculated after every purchase.')
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import lil_matrix
    import numpy as np
    targets=sorted(covered)
    m,n=len(targets),len(options)
    A=lil_matrix((m,n),dtype=float)
    target_rows={rid:i for i,rid in enumerate(targets)}
    for j,(_,s,_) in enumerate(options):
        if time.monotonic()>=deadline: raise ValueError('Planning preparation reached its time limit.')
        for rid in s: A[target_rows[rid],j]=1
    prices=np.array([x[2] for x in options],dtype=float)
    if strategy == 'best-value':
        # x products + y covered recordings. Required recordings are hard constraints.
        from scipy.sparse import hstack, vstack, eye, csr_matrix
        constraint=hstack([A,-eye(m)]).tocsr()
        lb=np.zeros(m); ub=np.full(m,np.inf)
        money=np.r_[prices,np.zeros(m)]
        max_budget=cents(budget) if budget is not None else int(sum(prices))
        if max_budget is None: raise ValueError('Budget must be zero or greater.')
        constraint=vstack([constraint,csr_matrix(money.reshape(1,-1))])
        lb=np.r_[lb,0]; ub=np.r_[ub,max_budget]
        penalty=max(0, float(purchase_penalty))*100
        costs=prices+penalty
        reward=float(sum(costs)+1)
        objective=np.r_[costs,-np.full(m,reward)]
        lower=np.zeros(n+m); upper=np.ones(n+m)
        for i,rid in enumerate(targets):
            if p['recordings'][rid].get('required'): lower[n+i]=1
    else:
        constraint=A.tocsr(); lb=np.ones(m); ub=np.full(m,np.inf)
        # Lexicographic tie breaks: count then cost, or cost then count.
        preference = np.array([release_preference(o[0]) for o in options], dtype=float)
        # Total preference is strictly smaller than one purchase, and total
        # purchase count is strictly smaller than one cent. No price tradeoff.
        tie = 1 + preference / (6*n+1)
        objective = prices*(2*n+1)+tie if strategy == 'cheapest' else np.full(n,(sum(prices)+1)*(2*n+1))+prices*(2*n+1)+preference/(6*n+1)
        lower=np.zeros(n); upper=np.ones(n)
    # Optimize listening priorities before spending budget on unplayed songs.
    # Separate solves keep these priorities exact without huge numeric weights.
    if strategy == 'best-value' and play_counts is not None:
        priorities=[np.array([int(play_counts.get(rid,0)>0) for rid in targets]),
                    np.array([play_counts.get(rid,0) for rid in targets]), np.ones(m)]
        objectives=[-np.r_[np.zeros(n),values] for values in priorities if np.any(values)]
        objectives.append(np.r_[costs,np.zeros(m)])
        previous=None
        for stage_objective in objectives:
            if previous is not None and time.monotonic()>=deadline:
                result=previous; result.status=1
                break
            result=milp(c=stage_objective,integrality=np.ones(n+m),bounds=Bounds(lower,upper),
                constraints=LinearConstraint(constraint,lb,ub),
                options={'time_limit':max(.01,deadline-time.monotonic()),'mip_rel_gap':0})
            if result.x is None or result.status!=0:
                if result.x is None and previous is not None:
                    result=previous; result.status=1
                break
            previous=result
            optimum=float(stage_objective @ np.rint(result.x))
            constraint=vstack([constraint,csr_matrix(stage_objective.reshape(1,-1))])
            lb=np.r_[lb,optimum]; ub=np.r_[ub,optimum]
    else:
        result=milp(c=objective,integrality=np.ones(len(objective)),bounds=Bounds(lower,upper),
                constraints=LinearConstraint(constraint,lb,ub),options={'time_limit':max(.01,deadline-time.monotonic()),'mip_rel_gap':0})
    if result.x is None:
        return dict(base, status='No feasible plan within the budget / required-song constraints.' if result.status==2 else 'Solver could not finish. Try a smaller project or a priority strategy.')
    selected=[i for i in range(n) if result.x[i] > .5]
    actual=set().union(*(options[i][1] for i in selected)) if selected else set()
    total=sum(options[i][2] for i in selected)
    optimal=result.status==0
    return dict(base, release_ids=[options[i][0]['id'] for i in selected],cost=total/100,
                covered=len(actual),coverage_percent=round(100*len(actual)/len(wanted),1),
                complete=actual>=wanted,optimal=optimal,
                status=('Optimal for the discovered, confirmed, priced options.' if optimal else 'Time limit reached; best plan found, optimality unproven.'))


def release_preference(release):
    if 'preference_rank' in release: return release['preference_rank']
    kind = release.get('release_kind', release.get('kind', 'unknown'))
    return {'album':0, 'deluxe album':1, 'other album':2, 'ep':3,
            'compilation':4, 'soundtrack':4, 'single':5}.get(kind, 5)


def rank_album_options(p, options):
    """Prefer the source's main album, or earliest dated full album when known.

    This is a release preference heuristic, never evidence of recording identity.
    If metadata cannot distinguish full albums, they keep equal preference.
    """
    def album_key(name):
        return normalize(re.sub(r'\b(deluxe|expanded|edition|anniversary)\b', '', name or '', flags=re.I))
    preferred = {}
    from collections import defaultdict
    albums_by_recording=defaultdict(list);sources_by_recording=defaultdict(set)
    for r in p['releases'].values():
        if r.get('release_kind',r.get('kind'))=='album':
            for rid in r.get('coverage',[]): albums_by_recording[rid].append(r)
    for t in p['tracks']: sources_by_recording[t['recording_id']].add(album_key(t.get('source_metadata',{}).get('album')))
    for rid in set().union(*(cover for _,cover,_ in options)) if options else ():
        albums = albums_by_recording[rid]
        sources = sources_by_recording[rid].copy()
        sources.add(album_key(p['recordings'][rid].get('album')))
        matches = [r for r in albums if album_key(r.get('release_name') or r.get('name')) in sources - {''}]
        if not matches:
            dated = [r for r in albums if r.get('date')]
            if dated:
                earliest = min(r['date'] for r in dated)
                matches = [r for r in dated if r['date']==earliest]
        preferred[rid] = {r.get('release_id') or r.get('catalog_id') for r in matches}
    ranked = []
    for r,cover,price in options:
        rank = release_preference(r)
        if rank == 0 and any(preferred[rid] for rid in cover):
            cid = r.get('release_id') or r.get('catalog_id')
            if not any(cid in preferred[rid] for rid in cover): rank = 2
        ranked.append((dict(r,preference_rank=rank),cover,price))
    return ranked
