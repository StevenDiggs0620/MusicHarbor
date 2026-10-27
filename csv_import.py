"""Import playlist metadata from Exportify CSV without contacting Spotify.

Playlist occurrences remain separate from recordings. Only repeated Spotify IDs
with agreeing supplied metadata are consolidated; titles alone never establish
recording identity. Unavailable fields stay unknown.
"""
import csv
import io
import math
import re
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

import store
from matching import normalize

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20000
MAX_FIELD = 32768

# Exportify has used both short and prefixed headers across versions.
ALIASES = {
    'title': ('track name', 'track title', 'song name', 'song title', 'title'),
    'artist': ('artist names', 'artist name', 'artists', 'artist'),
    'album': ('album name', 'album'),
    'uri': ('track uri', 'spotify track uri', 'spotify uri', 'track url', 'spotify url'),
    'duration_ms': ('duration ms', 'track duration ms', 'duration milliseconds'),
    'duration_seconds': ('duration seconds', 'duration s', 'track duration seconds'),
    'duration': ('duration', 'track duration'),
    'explicit': ('explicit', 'track explicitness'),
    'isrc': ('isrc',),
    'release_date': ('release date', 'album release date'),
}


def header_key(text):
    text = text.casefold().replace('(', '').replace(')', '')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def field_text(value):
    return (value or '').strip()


def parse_explicit(value):
    value = value.strip().casefold()
    if value in ('true', '1', 'yes', 'explicit'): return True
    if value in ('false', '0', 'no', 'clean', 'cleaned', 'notexplicit', 'not explicit'): return False
    if value in ('', 'unknown', 'n/a', 'null'): return None
    raise ValueError('Explicit must be TRUE, FALSE, or blank.')


def parse_duration(value, unit):
    value = value.strip()
    if not value: return None
    try:
        if unit == 'clock':
            parts = value.split(':')
            if len(parts) not in (2, 3): raise ValueError()
            numbers = [float(x) for x in parts]
            if any(not math.isfinite(x) or x < 0 for x in numbers): raise ValueError()
            if any(x >= 60 for x in numbers[1:]): raise ValueError()
            seconds = sum(n * (60 ** i) for i, n in enumerate(reversed(numbers)))
        else:
            seconds = float(value) / (1000 if unit == 'ms' else 1)
        if not math.isfinite(seconds) or seconds < 0 or seconds > 86400: raise ValueError()
        return round(seconds, 3) if seconds else None
    except (ValueError, OverflowError):
        raise ValueError('Duration is invalid; use milliseconds in Duration (ms), seconds in Duration (seconds), or m:ss in Duration.')


def spotify_id(value):
    value = value.strip()
    match = re.fullmatch(r'spotify:track:([A-Za-z0-9]{22})', value)
    if match: return match.group(1)
    try:
        parsed = urlparse(value)
        match = re.fullmatch(r'/(?:intl-[a-z]+/)?track/([A-Za-z0-9]{22})/?', parsed.path)
        if parsed.scheme == 'https' and parsed.hostname == 'open.spotify.com' and match: return match.group(1)
    except ValueError:
        pass
    return None


def release_date(value):
    value = value.strip()
    if not value: return ''
    for fmt in ('%Y-%m-%d', '%m/%d/%y', '%m/%d/%Y', '%Y-%m', '%Y'):
        try:
            parsed = datetime.strptime(value[:10] if 'T' in value else value, fmt)
            return parsed.strftime('%Y-%m-%d') if fmt not in ('%Y', '%Y-%m') else value
        except ValueError:
            continue
    return value  # Retain an unfamiliar date as supplied, not an invented date.


def decode(data):
    if len(data) > MAX_BYTES: raise ValueError('Choose a CSV smaller than 10 MB.')
    if not data: raise ValueError('This file is empty. Choose an Exportify CSV.')
    try:
        text = data.decode('utf-16') if data.startswith((b'\xff\xfe', b'\xfe\xff')) else data.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('This CSV is not UTF-8 or UTF-16. Export it again from Exportify, or save it as CSV UTF-8.')
    if '\0' in text: raise ValueError('This does not look like a text CSV file.')
    return text


def parse(data):
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=',;\t')
        delimiter = dialect.delimiter
    except csv.Error:
        # Exportify's normal format is comma-separated. A quoted multiline field
        # can prevent Sniffer from recognizing a truncated sample.
        first = text.splitlines()[0] if text.splitlines() else ''
        delimiter = '\t' if '\t' in first and ',' not in first else ','
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
        while not headers or not any(x.strip() for x in headers): headers = next(reader)
    except (StopIteration, csv.Error):
        raise ValueError('The CSV has no readable header row.')
    if len(headers) > 200: raise ValueError('This CSV has too many columns (maximum 200).')
    keys = [header_key(h) for h in headers]
    mapping = {}
    for field, aliases in ALIASES.items():
        matches = [i for i, key in enumerate(keys) if key in aliases]
        if len(matches) > 1:
            raise ValueError(f'The CSV has more than one {field.replace("_", " ")} column. Keep one before importing.')
        if matches: mapping[field] = matches[0]
    if not {'title', 'artist'} <= mapping.keys():
        raise ValueError('The CSV needs Track Name and Artist Name(s) columns. Choose the original Exportify CSV, not an Excel workbook or a pasted Markdown table.')
    if sum(k in mapping for k in ('duration_ms','duration_seconds','duration')) > 1:
        raise ValueError('Keep one duration column so its units are unambiguous.')
    recordings = {}; tracks = []; rows = []; errors = []; warnings = []
    identity = {}; seen_spotify_ids = set(); rows_read = 0; blank_rows = 0
    try:
        for cells in reader:
            if not cells or not any(x.strip() for x in cells): blank_rows += 1; continue
            rows_read += 1
            if rows_read > MAX_ROWS: raise ValueError('The CSV exceeds the 20,000-entry import limit.')
            line = reader.line_num
            if len(cells) != len(headers):
                errors.append({'line':line, 'message':f'Expected {len(headers)} columns, found {len(cells)}. Check CSV quoting.'})
                continue
            if any(len(x) > MAX_FIELD for x in cells):
                errors.append({'line':line, 'message':'A field exceeds the 32 KB limit.'}); continue
            def get(field): return field_text(cells[mapping[field]]) if field in mapping else ''
            title = get('title'); artist = ', '.join(x.strip() for x in get('artist').split(';') if x.strip())
            if not title or not artist:
                errors.append({'line':line, 'message':'Track name and artist are required.'}); continue
            if len(title)>2000 or len(artist)>2000:
                errors.append({'line':line, 'message':'Track name or artist is too long (2,000 characters maximum).'}); continue
            try:
                explicit = parse_explicit(get('explicit'))
                if 'duration_ms' in mapping: duration = parse_duration(get('duration_ms'),'ms')
                elif 'duration_seconds' in mapping: duration = parse_duration(get('duration_seconds'),'seconds')
                elif 'duration' in mapping:
                    raw = get('duration')
                    if raw and ':' not in raw: raise ValueError('The Duration column needs m:ss values; rename a numeric column to Duration (ms) or Duration (seconds).')
                    duration = parse_duration(raw,'clock')
                else: duration = None
            except ValueError as exc:
                errors.append({'line':line, 'message':str(exc)}); continue
            raw_uri = get('uri'); sid = spotify_id(raw_uri)
            if raw_uri and not sid:
                warnings.append({'line':line, 'message':'Unrecognized Track URI; imported using its title and artist without a Spotify ID.'})
            isrc = get('isrc').upper() or None
            if isrc and not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}\d{7}',isrc):
                warnings.append({'line':line,'message':'Unrecognized ISRC; left unknown.'}); isrc=None
            # An ID is evidence of identity, but conflicting version metadata
            # must never be discarded simply because an export reused that ID.
            signature = (normalize(title), normalize(artist), explicit, duration, isrc)
            key = (sid, signature) if sid else None
            rid = identity.get(key) if key else None
            if not rid:
                rid = store.uid()
                if sid and sid in seen_spotify_ids:
                    warnings.append({'line':line,'message':'Repeated Spotify ID has different metadata. Kept as a separate recording for review.'})
                if key:
                    identity[key] = rid
                    seen_spotify_ids.add(sid)
                recordings[rid] = dict(
                    id=rid, title=title, artist=artist, album=get('album'), duration=duration,
                    spotify_id=sid, spotify_url=f'https://open.spotify.com/track/{sid}' if sid else '',
                    explicit=explicit, isrc=isrc, release_date=release_date(get('release_date')),
                    included=True, required=False, owned=False, ownership_override=None,
                    match_status='unmatched', selected=None, candidates=[], rejected=[],
                    source_type='exportify_csv')
            tracks.append(dict(id=store.uid(),recording_id=rid,source_row=line,source_position=rows_read,
                               source_metadata=dict(title=title,artist=artist,album=get('album'),duration=duration,explicit=explicit,isrc=isrc,spotify_id=sid),
                               source_album=get('album'),source_release_date=release_date(get('release_date'))))
            rows.append(dict(position=rows_read,title=title,artist=artist,album=get('album'),
                             duration=duration,explicit=explicit,spotify_id=sid,isrc=isrc))
    except csv.Error as exc:
        raise ValueError(f'CSV formatting error near line {reader.line_num}: {exc}. Export the playlist again.')
    if not rows_read: raise ValueError('This CSV has a header but no playlist entries.')
    return dict(recordings=recordings,tracks=tracks,rows=rows,errors=errors,warnings=warnings,
                rows_read=rows_read,blank_rows=blank_rows,columns={k:headers[i] for k,i in mapping.items()},
                missing_duration=sum(r['duration'] is None for r in rows),
                missing_explicit=sum(r['explicit'] is None for r in rows))


def preview(parsed):
    return dict(count=len(parsed['tracks']),recording_count=len(parsed['recordings']),
                repeated_entries=len(parsed['tracks'])-len(parsed['recordings']),
                rows_read=parsed['rows_read'],blank_rows=parsed['blank_rows'],rows=parsed['rows'][:50],
                errors=parsed['errors'][:50],error_count=len(parsed['errors']),
                warnings=parsed['warnings'][:50],warning_count=len(parsed['warnings']),
                columns=parsed['columns'],missing_duration=parsed['missing_duration'],
                missing_explicit=parsed['missing_explicit'],can_import=not parsed['errors'] and bool(parsed['tracks']))


def build_project(parsed, name, storefront, filename):
    if parsed['errors']: raise ValueError('Fix the rows shown in the preview before importing. No project has been created.')
    if not parsed['tracks']: raise ValueError('This CSV contains no importable songs.')
    filename = PurePosixPath(filename.replace('\\','/')).name[:255]
    name = name.strip() or re.sub(r'\.csv$', '', filename, flags=re.I) or 'Imported playlist'
    if len(name)>200: raise ValueError('Use a project name of 200 characters or fewer.')
    p = store.new_project(name,storefront)
    p.update(recordings=parsed['recordings'],tracks=parsed['tracks'],source_type='exportify_csv',
             source_filename=filename,imported_at=store.now(),import_summary=preview(parsed))
    # Preview rows are only needed during upload, not in every project snapshot.
    p['import_summary'].pop('rows',None)
    return p
