"""Validate portable snapshots before they enter application state."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_BYTES = 128 * 1024 * 1024

class Model(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)

class Song(Model):
    trackId: int = Field(gt=0)
    trackName: str
    artistName: str
    collectionId: int | None = Field(default=None, gt=0)
    collectionName: str = ''
    trackTimeMillis: float = Field(default=0, ge=0)
    trackExplicitness: str | None = None
    trackPrice: float | None = None
    collectionPrice: float | None = None
    currency: str | None = None
    trackViewUrl: str = ''
    collectionViewUrl: str = ''
    artworkUrl100: str = ''
    releaseDate: str = ''
    trackNumber: int | None = Field(default=None, ge=0)
    discNumber: int | None = Field(default=None, ge=0)
    trackCount: int | None = Field(default=None, ge=0)
    isrc: str | None = None

class Candidate(Model):
    song: Song
    score: float = Field(default=0, ge=0, le=100)
    confidence: Literal['high','medium','low'] = 'low'
    compatible: bool = True
    reasons: list[str] = Field(default_factory=list)

class Evidence(Model):
    score: float = Field(default=0, ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)

class Source(Model):
    title: str
    artist: str
    album: str | None = ''
    duration: float | None = Field(default=None, ge=0)
    explicit: bool | None = None
    isrc: str | None = None
    musicbrainz_id: str | None = None
    itunes_track_id: str | None = None
    spotify_id: str | None = None
    spotify_url: str | None = ''

class Recording(Source):
    id: str
    included: bool = True
    required: bool = False
    owned: bool = False
    ownership_override: bool | None = None
    match_status: Literal['high','confirmed','medium','low','unmatched'] = 'unmatched'
    resolution_state: Literal['EXACT','HIGH_CONFIDENCE','NEEDS_REVIEW','UNMATCHED'] | None = None
    selected: Song | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    source_identities: list[Source] = Field(default_factory=list)
    match_evidence: Evidence = Field(default_factory=Evidence)
    identity_evidence: Evidence = Field(default_factory=Evidence)
    library_identity: bool = False
    playlist_seen: bool = False
    source_type: str = ''

class Product(Model):
    id: str
    catalog_id: str = ''
    name: str = ''
    artist: str = ''
    kind: str = 'unknown'
    release_kind: str = 'unknown'
    purchase_type: Literal['track','release'] = 'release'
    release_id: str = ''
    release_name: str = ''
    date: str = ''
    checked: str | None = None
    price: float | None = None
    currency: str | None = None
    url: str = ''
    artwork: str = ''
    track_number: int | None = Field(default=None, ge=0)
    disc_number: int | None = Field(default=None, ge=0)
    track_count: int | None = Field(default=None, ge=0)
    songs: list[Song] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    owned: bool = False
    excluded: bool = False
    preference_rank: int | None = Field(default=None,ge=0,le=5)
    incomplete_tracklist: bool = False
    tracklist_refresh_incomplete: bool = False

class Entry(Model):
    id: str
    recording_id: str
    source_metadata: Source | None = None
    source_row: int | None = Field(default=None, ge=1)
    source_position: int | None = Field(default=None, ge=1)

class Export(Model):
    created: str
    count: int = Field(ge=0)
    skipped: int = Field(ge=0)

class Price(Model):
    release_id: str
    price: float | None = None
    currency: str | None = None
    checked: str
    storefront: Literal['us','ca','gb']

class Project(Model):
    id: str
    name: str
    storefront: Literal['us','ca','gb']
    tracks: list[Entry]
    recordings: dict[str, Recording]
    releases: dict[str, Product]
    exports: list[Export] = Field(default_factory=list)
    price_history: list[Price] = Field(default_factory=list)
    source_url: str = ''
    source_filename: str = ''
    source_type: str = ''
    created: str = ''
    refreshed: str | None = None
    export_file_overrides: dict[str,str] = Field(default_factory=dict)

def validate(blob):
    try:
        json.dumps(blob,allow_nan=False)
        if not isinstance(blob, dict) or blob.get('format') not in ('musicharbor','playlist-purchaser') or blob.get('version') != 2:
            raise ValueError()
        model = Project.model_validate(blob['project'])
        p = model.model_dump(exclude_unset=True)
        # Include required application defaults while leaving optional source keys absent.
        for key in ('exports','price_history','source_url','source_filename','source_type','refreshed'):
            p.setdefault(key, getattr(model, key))
        for rid, rec in model.recordings.items():
            if rid != rec.id: raise ValueError()
            p['recordings'][rid] = rec.model_dump(exclude_none=True)
            p['recordings'][rid].update(explicit=rec.explicit, duration=rec.duration,
                                        ownership_override=rec.ownership_override, selected=rec.selected.model_dump() if rec.selected else None)
        ids = set(p['recordings'])
        if not set(model.export_file_overrides)<=ids: raise ValueError()
        if any(not path or any(c in path for c in ('\n','\r','\0')) for path in model.export_file_overrides.values()): raise ValueError()
        for entry in p['tracks']:
            if entry['recording_id'] not in ids: raise ValueError()
            if entry.get('source_metadata') is None: entry.pop('source_metadata', None)
        for key, rel in model.releases.items():
            if rel.id != key or not set(rel.coverage + rel.partial) <= ids: raise ValueError()
            p['releases'][key] = rel.model_dump()
            if rel.preference_rank is None: p['releases'][key].pop('preference_rank',None)
            if 'release_kind' not in blob['project']['releases'][key]:
                p['releases'][key]['release_kind']=rel.kind
            if 'purchase_type' not in blob['project']['releases'][key]:
                p['releases'][key]['purchase_type']='track' if key.startswith('track:') or rel.kind=='individual song' else 'release'
        p.update(local_files=[], library_folders=[])
        return p
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError('That is not a valid MusicHarbor project backup. Its recording, release, or history data is invalid.') from exc

def encode(p):
    blob = dict(format='musicharbor', version=2,
                project={k:v for k,v in p.items() if not k.startswith('_')})
    validate(blob)  # Never offer a file that our restore schema rejects.
    data = json.dumps(blob, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('This project exceeds the 128 MB portable backup limit. Reduce retained catalog/history data before backing it up.')
    return data
