"""Indexed library projections; project loads only fetch possible identity matches."""
import json
from musicharbor.matching import comparison_title, song_data

def keys(rec):
    result={('id',rec['id'])}
    for source in (rec,song_data(rec['selected']) if rec.get('selected') else {}):
        title=comparison_title(source.get('title'),{'remasters_equivalent':True,'clean_explicit_equivalent':True})
        if title: result.add(('title',title))
        for key in ('isrc','musicbrainz_id','itunes_track_id'):
            if source.get(key): result.add((key,str(source[key]).casefold()))
    return result

def index_record(c,rid,rec):
    c.execute('DELETE FROM library_keys WHERE recording=?',(rid,))
    c.executemany('INSERT OR IGNORE INTO library_keys VALUES (?,?,?)',[(kind,value,rid) for kind,value in keys(rec)])

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS library_keys(kind TEXT,value TEXT,recording TEXT,PRIMARY KEY(kind,value,recording))')
    c.execute('CREATE INDEX IF NOT EXISTS library_file_identity ON library_files(json_extract(payload,\'$.identity_id\'))')
    c.execute('CREATE INDEX IF NOT EXISTS library_file_recording ON library_files(json_extract(payload,\'$.recording_id\'))')
    # Only backfill records absent from the index; subsequent saves update it.
    for row in c.execute('SELECT id,payload FROM library_recordings WHERE id NOT IN (SELECT recording FROM library_keys)').fetchall():
        index_record(c,row['id'],json.loads(row['payload']))

def related(c,recordings):
    c.execute('CREATE TEMP TABLE IF NOT EXISTS wanted_library_keys(kind TEXT,value TEXT,PRIMARY KEY(kind,value))')
    c.execute('DELETE FROM wanted_library_keys')
    c.executemany('INSERT OR IGNORE INTO wanted_library_keys VALUES (?,?)',
                  (key for rec in recordings.values() for key in keys(rec)))
    rows=c.execute('SELECT DISTINCT r.id,r.payload FROM library_recordings r JOIN library_keys k ON k.recording=r.id JOIN wanted_library_keys w ON w.kind=k.kind AND w.value=k.value').fetchall()
    records={r['id']:json.loads(r['payload']) for r in rows}
    c.execute('CREATE TEMP TABLE IF NOT EXISTS wanted_library_ids(id TEXT PRIMARY KEY)')
    c.execute('DELETE FROM wanted_library_ids')
    c.executemany('INSERT INTO wanted_library_ids VALUES (?)',[(rid,) for rid in records])
    files=[json.loads(r[0]) for r in c.execute("SELECT payload FROM library_files WHERE json_extract(payload,'$.identity_id') IN (SELECT id FROM wanted_library_ids) OR json_extract(payload,'$.recording_id') IN (SELECT id FROM wanted_library_ids)")]
    return files,records

def page(offset=0,limit=100):
    import musicharbor.store as store
    with store.connection() as c:
        total=c.execute('SELECT count(*) FROM library_files').fetchone()[0]
        matched_total=c.execute("SELECT count(*) FROM library_files WHERE json_extract(payload,'$.status')='matched'").fetchone()[0]
        files=[json.loads(r[0]) for r in c.execute('SELECT payload FROM library_files ORDER BY path LIMIT ? OFFSET ?',(limit,offset))]
        ids={f.get('identity_id') or f.get('recording_id') for f in files}
        records={}
        for rid in ids:
            row=c.execute('SELECT payload FROM library_recordings WHERE id=?',(rid,)).fetchone()
            if row: records[rid]=json.loads(row[0])
    return dict(files=files,recordings=records,total=total,matched_total=matched_total,unresolved_total=total-matched_total,offset=offset,next_offset=offset+len(files) if offset+len(files)<total else None)
