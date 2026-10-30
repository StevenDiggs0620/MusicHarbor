# MusicHarbor

MusicHarbor is a desktop app for turning Spotify playlists into practical music purchase plans and playlists of files in your own music library. Import a playlist, find matching releases in the iTunes Store, compare purchase options, track what you own, and export a playlist for your local player.

MusicHarbor runs on your computer. It does not buy, download, rip, or upload music.

## Features

- Import playlists from Spotify or an Exportify CSV.
- Find and review matching songs and releases in an iTunes Store storefront.
- Build purchase plans using price, coverage, and artist-focused strategies.
- Track owned recordings and releases across projects.
- Scan a local music folder and export matching files as M3U or M3U8 playlists.
- Save, update, back up, and restore playlist projects.

## Getting started

### Run from source

Install Python 3.11 or newer, download or clone this repository, then run the launcher from the project folder:

```sh
python3 scripts/launch.py
```

On Windows, use:

```powershell
py -3 scripts/launch.py
```

The first launch sets up the app's runtime and may need an internet connection to install its dependencies. You can also use the platform launchers in `scripts/`.

### Import a playlist

You can start without connecting a Spotify account:

1. Export a playlist as a CSV with [Exportify](https://exportify.net), or use a CSV you already have.
2. Open MusicHarbor and choose **Import Playlist**.
3. Select the CSV, review the preview, and create a project.
4. Review the matching Store results and build a purchase plan.

CSV import does not require Spotify credentials. Store search requires an internet connection. You can also connect Spotify for direct playlist import; see [Spotify setup](#optional-spotify-setup).

## Optional Spotify setup

Direct Spotify import requires a Spotify developer app:

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add this redirect URI to its settings: `http://127.0.0.1:8765/api/oauth/callback`.
3. Enter the app's Client ID in MusicHarbor Settings, then choose **Connect Spotify**.

Spotify controls which playlists an app in development mode can access. Check Spotify's [Web API documentation](https://developer.spotify.com/documentation/web-api) for current access requirements. Exportify CSV import remains available without connecting Spotify.

## Your data and privacy

MusicHarbor stores projects, settings, and local library records on your computer. Data is kept in the operating system's application data folder, separate from the source code. Set `MUSICHARBOR_DATA` to use a different location.

Spotify credentials and tokens are stored locally and are not encrypted. Disconnect Spotify in Settings to remove saved authorization. Backups may contain local file paths, so keep them private.

MusicHarbor sends playlist or search metadata to Spotify or Apple's iTunes Search API when you use those services. It reads your existing audio files to identify them; it does not send the audio files. The local app server listens only on your computer (`127.0.0.1`).

## Supported platforms

MusicHarbor is designed for macOS, Windows, and Linux. Running from source requires Python 3.11 or newer. Linux may require an operating-system GTK/WebKit or Qt component for the desktop window.

## Development

To install the development dependencies:

```sh
python -m pip install -e ".[dev]"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidance. The application package is in `src/musicharbor/`, and project tests are in `tests/`.

## License

MusicHarbor is licensed under the [GNU General Public License v3.0 or later](LICENSE). Third-party dependencies retain their own licenses.
