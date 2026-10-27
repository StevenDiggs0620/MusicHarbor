"""Structured stage progress; plain callbacks remain supported for service tests."""
def report(callback, stage, label, completed=0, total=None, detail='', status=None):
    if hasattr(callback, 'stage'):
        callback.stage(stage, label, completed, total, detail, status)
    else:
        callback(f'{label}: {completed}' + (f' of {total}' if total is not None else '') + (f' — {detail}' if detail else ''))


STAGES = {
    'discover': [('search','Searching recordings'),('releases','Reading releases'),('coverage','Matching release coverage'),('save','Saving results')],
    'update_playlist': [('import','Updating playlist'),('search','Searching new recordings'),('releases','Reading new releases'),('coverage','Matching release coverage'),('save','Saving results')],
    'import_and_discover': [('import','Importing playlist'),('search','Searching recordings'),('releases','Reading releases'),('coverage','Matching release coverage'),('save','Saving results')],
    'scan': [('scan','Scanning local files'),('identify','Identifying local recordings'),('coverage','Matching release coverage'),('save','Saving results')],
    'refresh_prices': [('alternatives','Finding alternative releases'),('releases','Refreshing releases'),('tracks','Refreshing individual tracks'),('coverage','Matching release coverage'),('save','Saving results')],
    'load_release': [('releases','Reading selected release'),('coverage','Matching release coverage'),('save','Saving results')],
}


class JobProgress:
    def __init__(self, job): self.job = job

    def __call__(self, message):
        if self.job['status'] != 'running': raise RuntimeError('Operation cancelled')
        self.job['message'] = message

    def stage(self, key, label, completed=0, total=None, detail='', status=None):
        self(label + (': ' + detail if detail else ''))
        stages=self.job['stages']
        current=next((s for s in stages if s['id']==key), None)
        if current is None:
            current=dict(id=key,label=label,status='pending'); stages.append(current)
        # Only explicitly finished stages are completed, never fabricate 100%.
        current.update(label=label,completed=completed,total=total,detail=detail,
                       status=status or ('done' if total is not None and completed>=total else 'running'))
        current['percent'] = round(100*min(completed,total)/total,1) if total else (100 if total==0 else None)
