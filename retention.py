"""Bound generated history without deleting projects or user decisions."""
import json
import time
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field

class Retention(BaseModel):
    job_days: int = Field(default=30,ge=1,le=3650)
    price_days: int = Field(default=365,ge=1,le=3650)
    export_count: int = Field(default=100,ge=1,le=10000)

def trim_project(p, policy):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=policy.price_days)).isoformat()
    p['price_history']=[x for x in p.get('price_history',[]) if x.get('checked','')>=cutoff]
    p['exports']=p.get('exports',[])[-policy.export_count:]

def cleanup():
    import store
    policy=Retention.model_validate(store.setting('retention',{}))
    cutoff=(datetime.now(timezone.utc)-timedelta(days=policy.job_days)).isoformat()
    with store.connection() as c:
        c.execute('DELETE FROM api_cache WHERE expires<=?',(time.time(),))
        for row in c.execute('SELECT id,project,payload FROM jobs').fetchall():
            job=json.loads(row['payload'])
            if job.get('status') in ('running','queued'): continue
            orphan=row['project']!='__listening__' and not c.execute('SELECT 1 FROM projects WHERE id=?',(row['project'],)).fetchone()
            if orphan or job.get('finished',job.get('created',''))<cutoff:
                c.execute('DELETE FROM jobs WHERE id=?',(row['id'],))
        for row in c.execute('SELECT id,payload FROM projects').fetchall():
            p=json.loads(row['payload']);trim_project(p,policy)
            c.execute('UPDATE projects SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),row['id']))
