"""MusicHarbor identity and backwards-compatible data location selection."""
import os
import sys
from pathlib import Path


def data_dir():
    override = os.getenv('MUSICHARBOR_DATA') or os.getenv('PLAYLIST_PURCHASER_DATA')
    if override:
        return Path(override).expanduser()
    if sys.platform == 'win32':
        root = Path(os.getenv('LOCALAPPDATA', Path.home()))
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library/Application Support'
    else:
        root = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local/share'))
    legacy = root / ('playlist-purchaser' if sys.platform not in ('darwin', 'win32') else 'Playlist Purchaser')
    # Keep existing installations in place: moving live SQLite files could lose data.
    if legacy.exists():
        return legacy
    return root / ('musicharbor' if sys.platform not in ('darwin', 'win32') else 'MusicHarbor')
