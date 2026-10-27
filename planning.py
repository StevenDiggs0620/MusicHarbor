"""Bounded, cancellable solver processes with a small content-addressed cache."""
import asyncio
import copy
import hashlib
import json
import multiprocessing
import time
from collections import OrderedDict
from matching import owned_ids

CACHE=OrderedDict()

def prepare(p,options,counts):
    owned=owned_ids(p)
    # Solver inputs omit search candidates and raw Store track lists.
    snapshot=dict(storefront=p['storefront'],tracks=p['tracks'],
                  recordings={rid:dict(title=r.get('title',''),artist=r.get('artist',''),album=r.get('album',''),included=r.get('included',True),required=r.get('required',False)) for rid,r in p['recordings'].items()},
                  releases={rid:{k:v for k,v in r.items() if k not in ('songs','artwork','url')} for rid,r in p['releases'].items()})
    for rid,r in p['releases'].items():
        snapshot['releases'][rid]['songs']=[{k:s.get(k) for k in ('collectionId','collectionName','discNumber','trackNumber')} for s in r.get('songs',[])[:1]]
    key=hashlib.sha256(json.dumps([snapshot,options,counts,sorted(owned)],sort_keys=True).encode()).hexdigest()
    return owned,snapshot,key

def worker(connection,p,options,counts,owned):
    try:
        from optimizer import calculate
        from purchase_order import purchase_groups
        result=calculate(p,**options,play_counts=counts,owned=owned,time_budget=20)
        result['purchase_groups']=purchase_groups(p,result['release_ids'],counts)
        connection.send(('ok',result))
    except Exception as exc:
        connection.send(('error',str(exc)))
    finally: connection.close()

async def run(p,options,counts):
    owned,snapshot,key=await asyncio.to_thread(prepare,p,options,counts)
    if key in CACHE:
        stamp,result=CACHE[key]
        if time.monotonic()-stamp<300:
            CACHE.move_to_end(key);return copy.deepcopy(result)
        del CACHE[key]
    ctx=multiprocessing.get_context('spawn')
    parent,child=ctx.Pipe(duplex=False)
    process=ctx.Process(target=worker,args=(child,snapshot,options,counts,owned),daemon=True)
    try:
        process.start();child.close()
        deadline=time.monotonic()+35
        while not parent.poll():
            if not process.is_alive(): raise ValueError('Purchase calculation stopped unexpectedly. Please retry.')
            if time.monotonic()>deadline: raise ValueError('Purchase calculation exceeded its time budget. Try a priority strategy or a smaller project.')
            await asyncio.sleep(.1)
        status,result=await asyncio.to_thread(parent.recv)
        if status!='ok': raise ValueError(result)
        CACHE[key]=(time.monotonic(),copy.deepcopy(result))
        while len(CACHE)>12: CACHE.popitem(last=False)
        return result
    finally:
        if process.pid:
            if process.is_alive(): process.terminate()
            await asyncio.to_thread(process.join,2)
            if process.is_alive(): process.kill();await asyncio.to_thread(process.join)
        parent.close();child.close()
