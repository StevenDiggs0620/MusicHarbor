"""Deterministic selection of local copies, independent of scan order."""
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal

class ExportOptions(BaseModel):
    format: Literal['m3u', 'm3u8'] = 'm3u'
    extinf: bool = False
    slashes: Literal['windows', 'macos'] = 'windows'
    custom_path: bool = False
    path_mode: Literal['text','prefix'] = 'text'
    path_from: str = ''
    path_to: str = ''
    preferred_format: Literal['any','flac','m4a','mp3','wav','aac','ogg'] = 'any'
    preferred_folder: str = Field(default='',max_length=4000)
    prefer_quality: bool = True

def select_files(p, options):
    groups={}
    for file in p.get('local_files',[]):
        rid=file.get('recording_id')
        if rid and file.get('status')=='matched' and Path(file['path']).is_file():
            groups.setdefault(rid,[]).append(file)
    def key(file):
        path=Path(file['path']); folder=options.preferred_folder.strip()
        in_folder=bool(folder) and path.is_relative_to(Path(folder).expanduser())
        suffix=path.suffix.lower().lstrip('.')
        lossless=suffix in ('flac','wav') or file.get('codec')=='alac'
        quality=(-int(lossless),-(file.get('bits_per_sample') or 0),
                 -(file.get('sample_rate') or 0),-(file.get('bitrate') or 0)) if options.prefer_quality else (0,0,0,0)
        return (not in_folder,options.preferred_format!='any' and suffix!=options.preferred_format,
                *quality,file['path'].casefold(),file['path'])
    selected={}
    for rid,files in groups.items():
        override=p.get('export_file_overrides',{}).get(rid)
        if override:
            chosen=next((f for f in files if f['path']==override),None)
            if chosen is None: raise ValueError('A preferred export file is missing or no longer matched. Clear its override or rescan before exporting.')
        else: chosen=min(files,key=key)
        selected[rid]=chosen
    for rid,path in p.get('export_file_overrides',{}).items():
        if rid in {t['recording_id'] for t in p['tracks']} and p['recordings'][rid].get('included',True) and rid not in groups:
            raise ValueError('A preferred export file is unavailable. Clear its override or rescan before exporting.')
    return selected,groups
