# MusicHarbor

**Project docs:** [GitHub upload instructions](docs/GITHUB_UPLOAD_GUIDE.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Interface notes](docs/INTERFACE_CHANGES.md)

Current version: **1.3.0**. The project code is licensed under the GNU General Public License v3.0 or, at your option, any later version; see [LICENSE](LICENSE). Third-party dependencies retain their respective licenses. The reorganized source built successfully on macOS. Checks on this revision: 182 passed and 4 existing failures reproduced on the previous layout; the packaged runtime smoke check could not run because port 8765 was already in use. GitHub checks are manual until explicitly started.

Formerly Playlist Purchaser. Existing collections, settings, and older backups remain supported; see [rebranding and compatibility notes](docs/REBRANDING.md). New installations use the data paths below; upgrades reuse their existing data folder.

The latest feature update is documented in [FEATURE_IMPROVEMENTS.md](docs/FEATURE_IMPROVEMENTS.md). It adds export-copy preferences, strategy/grouped purchase views, explicit ownership removal, project/full-library backups, scoped library loading, cancellable cached planning, retention controls, consistent Spotify imports, token reuse, and safer runtime packaging. These changes have **not** been run through application, regression, browser, or smoke tests; historical pass counts below refer to earlier revisions.

Purchase planning now starts when you choose **Calculate plan**. Cancel a calculation in the operation history. Library pages show 100 files at a time. Backup scope is selected on **Projects**; full-library backups include private file paths and all projects, and restored files require rescanning.

A local desktop application for finding purchase options for Spotify playlist recordings, comparing Store prices, tracking owned music, and exporting playlists of your own local files. The browser interface is also available for development.

## Use your Exportify CSV — no Spotify Premium needed

You can use the complete import → match → purchase-plan → ownership → local-file export workflow without configuring Spotify credentials. File import does not contact Spotify. Catalog discovery still needs an internet connection to query the iTunes Store.

1. Open [Exportify](https://exportify.net), authorize it as needed, and export your playlist as a CSV. If you already have the CSV, start at step 2.
2. Double-click **MusicHarbor.app** (macOS desktop build), or start from source with `python3 scripts/launch.py` (Windows: `py -3 scripts/launch.py`).
3. Open **Import Playlist**. The **Import your Exportify playlist** panel appears first.
4. Choose your CSV, check the project name, and choose your purchase storefront.
5. Click **Import a File** to preview the contents. This step does not create a project.
6. Check the entry count, artists, duration, and explicit status. If the file contains invalid rows, fix the reported rows and choose the corrected CSV before continuing.
7. Click **Create project from CSV**. The application creates and selects a new saved project.
8. Automatic matching starts after import. Use **Review Matches** only for uncertain results; **Find Store matches** retries discovery for existing projects.
9. Open **Purchase Plan**, select a strategy, and calculate your purchases.
10. After buying music, mark it owned, scan your music folder in **Local Library**, review uncertain file identities, and export your M3U or M3U8. Identified local files automatically mark their recordings owned.

You do not need to visit Settings, create a Spotify developer app, provide a Client ID or Secret, or subscribe to Premium for this file-based workflow. Direct Spotify import remains available under **Optional: import directly with Spotify API access**.

### Update an existing project

Select a project, then use **Import Playlist → Update this playlist project**. Choose an Exportify CSV or a Spotify playlist link and select:

- **Add to playlist:** keep all existing entries and append missing songs or additional duplicate appearances. Repeating the same import does not duplicate the entire playlist. For example, existing `A, B, A` plus incoming `A, C` becomes `A, B, A, C`.
- **Replace playlist:** use only the incoming entries in their source order, including duplicates. Removed songs remain in the project catalog for reuse if you add them later, but do not appear in the playlist, export, or purchase requirements.

Updates keep the project name, storefront, matched recordings, candidate evidence, review decisions, release catalog, ownership and local-file relationships. Source identifiers and compatible metadata determine reuse; conflicting versions remain separate. Existing complete release lists are reused even after the network cache expires. Only new or unfinished recordings are searched automatically. Use **Find Store matches** to explicitly retry catalog search or **Refresh prices** to request current prices.

CSV row errors block the entire update. A failed Spotify fetch leaves the original playlist intact. Once membership is saved, cancelling subsequent discovery keeps the new membership and completed searches. Spotify links still require the access described below.

### Playlist export options

Export offers **M3U** (default) or **M3U8**, optional **EXTINF** artist/title/duration information (off by default), and Windows backslashes (default) or macOS forward slashes. Both formats use UTF-8 text.

Optional path replacement changes only the exported text. The find field starts with the scanned music-folder path; for example, replace that folder with `iTunes` to produce `iTunes\Artist\Album\Song.mp3` with Windows slashes. With replacement off, matched local file paths are used. The preview uses the same options as the download; source files are never moved or renamed.

### Supported Exportify columns

| CSV column | How the app uses it |
| --- | --- |
| Track Name | Required song title; version labels are preserved. |
| Artist Name(s) | Required artist credits; semicolons become comma-separated credits. |
| Album Name | Original album metadata for display and review. |
| Track URI | Optional Spotify ID and link; repeated entries with agreeing metadata refer to one recording. |
| Duration (ms) or Track Duration (ms) | Converted to seconds while retaining millisecond precision. |
| Explicit or Explicit? | TRUE/FALSE becomes explicit/not-explicit. A blank value remains unknown. |
| Release Date or Album Release Date | Source release-date metadata. |
| ISRC | Optional recording identifier, when present and valid. |

For the supplied example, **God Driven** imports with artists **116, 1K Phew, Sam Rivera**, duration **176.937 seconds**, explicit status **false**, and release date **2026-07-31**. This is enough to search the Store without Spotify API access. A Store result still needs to be found and matched; import does not guarantee purchase availability.

Popularity, Added By, Added At, Genres, Record Label, and audio-analysis columns are accepted as extra CSV columns but are not stored or used for purchasing. Store prices, availability, and purchasable release track lists come from the iTunes API after import, not from the CSV.

The importer accepts quoted commas and line breaks, Unicode, UTF-8 BOM, UTF-16 BOM, and comma-, semicolon-, or tab-separated files. Limits are **10 MB**, **20,000 entries**, and **200 columns**. The preview shows the first 50 valid entries and up to 50 messages; the counts cover the whole file. Blank rows are ignored. Invalid nonblank rows block import so songs cannot silently disappear.

The original playlist order and repeated occurrences are retained. Matching Spotify IDs with conflicting supplied metadata stay separate for review. Rows without usable Spotify IDs are not merged just because their titles match. Missing duration and explicitness remain unknown and produce more conservative Store matching.

CSV files are sent only to the local application on your computer. The source file is not modified or retained. The app stores the imported metadata and source filename in the project. Exportify is an external service with its own access requirements; an existing CSV remains usable even if that service changes.

Importing another CSV can create a new project or update the selected project through **Update this playlist project**, as described above.

## Current delivery status

The application includes automated tests, launchers, and a GitHub Actions workflow for checks and desktop packaging. Desktop release bundles have not been signed or notarized. The active interface is in `src/musicharbor/static/`; unused prototype files have been removed.

## Start the application

### Desktop app on macOS

Open the versioned `MusicHarbor.app` identified by `dist/LATEST_RELEASE.txt` by double-clicking it in Finder. You can drag it into Applications for everyday use. The bundle includes Python and its dependencies: no terminal or separate Python installation is needed. Closing its window stops its local server; completed work remains saved, while running jobs are interrupted.

Projects, catalog results, credentials, and music-library records use the same database as the previous browser version, in the existing data folder (historically `~/Library/Application Support/Playlist Purchaser/`). Updating or moving the `.app` does not move or delete that data. `MUSICHARBOR_DATA` and the legacy `PLAYLIST_PURCHASER_DATA` remain supported for custom data locations. The desktop window keeps its own interface preferences, so you may need to select your saved project on first launch.

Quit the old terminal server before opening the desktop app. Both use local port 8765 for Spotify's registered callback. A port conflict displays an explanation rather than starting a second server. Store links and Spotify sign-in open in your normal browser; return to the app after signing in. Exports and backups offer a native save dialog. Startup diagnostics are written to `desktop.log` in the data folder.

This local build is not notarized for public distribution. If macOS blocks a downloaded copy, use **System Settings → Privacy & Security → Open Anyway** only for a build you trust.

### Running from source

Install **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/).

Recommended first launch from this folder:

```sh
python3 scripts/launch.py
```

On Windows:

```powershell
py -3 scripts/launch.py
```

The source launcher creates an isolated runtime, installs dependencies when needed, and opens a dedicated MusicHarbor window. Closing the app stops its server. The first source launch requires an internet connection. Linux requires a pywebview-compatible GTK/WebKit or Qt runtime installed by the operating system.

Platform launch files:

- Windows: double-click `scripts/start_windows.bat`.
- macOS: double-click `scripts/start_macos.command`. If needed, enable it once with `chmod +x scripts/start_macos.command`, or run `python3 scripts/launch.py`.
- Linux: run `sh scripts/start_linux.sh`.

Manual installation, if you prefer managing the runtime:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m musicharbor.app
```

Windows virtual-environment activation is `.venv\Scripts\activate`. `python -m musicharbor` opens the desktop window; `python -m musicharbor.app` uses your browser, and `python -m musicharbor.app --no-browser` starts only the local server.

If Python cannot install SciPy, use a supported 64-bit CPython version with available SciPy wheels; Python 3.12 is the packaging workflow's target. Dependencies are declared in `pyproject.toml`; the macOS release environment also has a captured package lock in `requirements/macos-release.lock`.

## Spotify setup

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Register this exact redirect address: `http://127.0.0.1:8765/api/oauth/callback`.
3. Open Settings in MusicHarbor and save your Client ID.
4. Select **Connect Spotify** and authorize access.
5. Import your playlist and choose its purchase storefront.

The application uses OAuth authorization code with PKCE, validates expiring one-time state, and refreshes tokens. A Client Secret is optional for OAuth. If provided without an OAuth connection, the app can request a Client Credentials token for public access where Spotify permits it.

**Spotify's current development-mode restrictions matter:** public visibility does not ensure playlist-item access. Development-mode apps require an eligible Premium app owner and can read playlist contents only when the signed-in user owns or collaborates on that playlist. The application cannot bypass those limits. See [Spotify's February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).

Environment variables `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` override stored values. If you use them, change or remove those environment variables to change the effective credentials.

## Main workflow

1. **Import Playlist:** import an Exportify CSV without credentials, or optionally connect Spotify for direct import. Creates a project, stores its source type, preserves playlist occurrence order, and separates repeated entries from recordings when identity is supported.
2. **Find Store matches:** searches the selected iTunes storefront and reads candidate release track lists. Long requests run as cancellable background operations with progress text.
3. **Review Matches:** inspect metadata, confirm or reject results, search manually, select a different Store result, skip recordings, and mark required songs. Confirmed choices persist. Confirming a match also attempts to load its release automatically. If that lookup fails, the match stays saved; enable Show all recordings and use Load selected release to retry.
4. **Purchase Plan:** select cheapest, fewest purchases, best value, most songs first, songs per dollar, or artist-focused ordering. Refresh prices when ready to buy.
5. **Owned Music:** mark recordings, complete releases, or parts of releases owned. An explicit recording override can represent owning a different version. Undoing release ownership removes only that ownership source.
6. **Local Library:** scan a folder. Files are identified independently of the playlist using metadata and a shared resolver. Review uncertain identities with catalog search. Identified files mark recordings owned automatically and the library is reused across projects.
7. **Export:** preview and download an M3U or M3U8 containing included, owned recordings with existing confirmed local files. Original ordering and repeated entries are retained.
8. **Projects:** switch, rename, duplicate, delete, back up, or restore projects. Restore intentionally discards local file mappings, which must be scanned on the destination computer.

## Matching and discovery

- Recording identity is separate from purchasable products. Individual Store songs, singles, EPs, albums, deluxe/expanded editions, compilations, and soundtracks can cover a wanted recording.
- The matcher considers normalized titles, artists, duration, explicitness, version labels, and ISRC when supplied on both sides. iTunes Search generally does not provide ISRC; the app never invents it.
- Different live, acoustic, remix, instrumental, radio-edit, and other version labels are not silently merged. Clean/explicit and remaster equivalence are configurable.
- High-confidence matches may be accepted automatically. Other matches need review. An explicit manual choice becomes the reference for comparing alternate releases.
- Artist credits and API metadata can be incomplete. Human review remains available even for automatically matched recordings.
- Album type classification is a heuristic based on naming and track count, because the Search API does not consistently identify every release category.
- Discovery uses iTunes Search and collection lookup. Search results are bounded; there is no guarantee that every edition or compilation will be discovered. Optional Apple Music API enrichment is not implemented.
- An unavailable price is not converted into an invented price. Currency and storefront must agree before an option participates in optimization.

## Purchase calculations

The SciPy/HiGHS integer solver models each purchase option as a set of recordings.

- **Cheapest:** minimize total price in integer cents, then product count.
- **Fewest purchases:** minimize product count, then price. Product count is not the number of checkout sessions.
- **Best value:** with synced listening history, first maximize the number of played wanted recordings covered, then their combined plays, then total wanted recordings, then minimize price plus the configurable cost per purchase. This can choose fewer total songs to include music you actually play. Without listening history (or when all wanted songs have zero plays), maximize total coverage before cost. The budget and required recordings remain hard constraints. A missing required recording is reported.
- **Most songs first:** repeatedly choose the release covering the most still-uncovered wanted recordings; break ties by lower price and newer release date.
- **Songs per dollar:** repeatedly choose the highest remaining wanted-coverage/price ratio. Free products are valid.
- **Artist focused:** prioritize the specified artist's remaining recordings, then total coverage and price.

Optimization has a 10-second solver limit. A timed-out feasible solution is labeled as unproven, not mathematically optimal. All claims apply only to discovered, confirmed, priced options in the selected storefront. Incomplete coverage is explicitly labeled. Taxes and checkout adjustments are not predicted.

An optional **user-supplied exchange rate** displays an estimate in another currency. It is not a live exchange-rate service and does not mix currencies in purchase calculations.

## Storage and privacy

The SQLite database and launcher runtime are stored outside the source folder and its OneDrive sync:

- macOS: `~/Library/Application Support/MusicHarbor/`
- Windows: `%LOCALAPPDATA%\MusicHarbor\`
- Linux: `$XDG_DATA_HOME/musicharbor/` or `~/.local/share/musicharbor/`

Set `MUSICHARBOR_DATA` (or the legacy `PLAYLIST_PURCHASER_DATA`) to override the data directory. Use a local, non-synchronized path for a live SQLite database. One running application instance should use a given database.

Projects are transactional JSON snapshots in SQLite, with a separate settings table and expiring API cache. Snapshots contain recording, release, occurrence, ownership, file-match, price-history, and export-history data. Independent `library_files` and `library_recordings` tables retain the reusable local library across projects. This is an intentional alternative to many relational tables; project mutations are saved together.

On first run, an original `playlist_purchaser.sqlite3` in the source folder is imported if present. Set `MUSICHARBOR_LEGACY` (or the legacy `PLAYLIST_PURCHASER_LEGACY`) to another legacy database path if needed. Legacy metadata and ownership are preserved; legacy release matches need rediscovery because the prototype did not record adequate version evidence. Already-lost cross-project data in an old prototype database cannot be reconstructed.

Credentials are stored locally with file permissions restricted where supported. They are **not encrypted**. They are never returned by the settings API or included in project backups. Tokens can be removed with Disconnect. Deleting a project removes its saved snapshot, not your music files. Backups may contain local paths and should be treated as private.

The server binds only to `127.0.0.1:8765`. Host and Origin checks, a per-run request token for mutations, and a restrictive content-security policy protect local operations from other websites. This is a single-user local application, not a public hosting service.

Only playlist metadata, catalog terms, and authorization data go to external APIs. The app reads your existing audio files but does not upload, download, rip, or transcode music. It never initiates a Store purchase.

## API behavior

iTunes requests are cached for 24 hours and paced at roughly one request per 3.1 seconds. Explicit price refresh bypasses the cache. API requests have timeouts, bounded retries, and Retry-After handling. A long rate-limit delay is reported for retry later. Completed stages may already be saved when an operation fails or is cancelled. Playlist updates save membership before catalog discovery and retain completed search work; an update that fails before membership changes leaves the existing playlist intact.

References:

- [Spotify PKCE flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify playlist access migration](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html)

## Development checks

Run the project checks against the current working tree; historical pass counts elsewhere in this README refer to earlier revisions.

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
node --check src/musicharbor/static/ui.js
```

Tests cover optimization objectives, missing/invalid prices, partial ownership, version and explicitness safeguards, project isolation, credential exposure, local request protections, OAuth state, playlist import ordering, and exports with real file paths. Test HTTP traffic uses FastAPI's in-process test client; Spotify import fixtures are mocked. Real account authorization and Store responses still need integration verification.

CSV regression tests additionally cover the supplied Exportify example, older header names, multiple artist credits, quoted fields, Unicode and BOMs, milliseconds, unknown metadata, repeated entries, conflicting IDs, malformed rows, local upload limits, and credential-free import. The tests also cover restoring a project whose imported recordings have unknown durations.

## Desktop packaging

### Before you start

1. Download and extract the complete project source, or clone its repository. The project root contains `pyproject.toml`, `tools/build.py`, and `src/musicharbor/`.
2. Install **64-bit Python 3.11 or newer** from [python.org](https://www.python.org/downloads/). Python 3.12 is the version used by the packaging workflow.
3. Have an internet connection for installing dependencies. Quit any previously built copy before rebuilding it.

Build on the operating system you intend to use: macOS for a `.app`, Windows for an `.exe`. Builds also depend on the processor architecture and system libraries; this script does not create a universal Mac build. See [PyInstaller's platform guidance](https://www.pyinstaller.org/en/stable/usage.html).

### macOS

Open Terminal. Replace the example path below with your extracted project folder, keeping the quotes if the path contains spaces. Run these commands one at a time:

```sh
cd "/path/to/MusicHarbor"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/macos-release.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python tools/build.py
```

Wait until the build reports completion. In Finder, open the project's versioned release folder shown in `dist/LATEST_RELEASE.txt` and double-click **MusicHarbor.app**. You can copy the entire `.app` into Applications. Do not extract or move files from inside the app bundle.

### Windows

Open PowerShell. Replace the example path with your extracted project folder, then run:

```powershell
cd "C:\path\to\MusicHarbor"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\build.py
```

Open `dist\releases\<release-id>\MusicHarbor\MusicHarbor.exe`. Keep the **entire `MusicHarbor` folder** together, including `_internal`; the `.exe` alone is not sufficient. Create a shortcut to the executable for convenient access. The desktop window requires Microsoft Edge WebView2 Runtime; see [pywebview's installation requirements](https://pywebview.flowrl.com/guide/installation).

### Linux

Install a supported GTK/WebKit or Qt backend using [pywebview's Linux instructions](https://pywebview.flowrl.com/guide/installation), then use the macOS terminal commands above with your Linux project path. The output is `dist/releases/<release-id>/MusicHarbor/MusicHarbor`, not a `.app`. Keep its containing folder intact. System GUI libraries are still required, so test on the intended Linux distribution before distributing a build.

### Updating and troubleshooting

- **Rebuild after code changes:** repeat the dependency-install and `tools/build.py` commands for your platform. The build replaces existing generated output without prompting. Quit the old app first, then replace any copy you placed in Applications or elsewhere.
- **Your data stays separate:** rebuilding does not delete projects, settings, or catalog data. The desktop app uses the same data folder as the browser version. The finished bundle includes Python and the Python packages, so end users do not need to install Python.
- **“Already running” or port 8765 is in use:** quit the previous desktop app, or stop the old terminal server with Ctrl+C. Closing a browser tab alone does not stop that server.
- **Missing Python or packages:** check that Python is installed and use the virtual-environment interpreter shown above. No virtual-environment activation command is needed. First-time downloads require internet access.
- **Startup problems:** inspect `desktop.log` in the app's data folder (`~/Library/Application Support/MusicHarbor/` on macOS; `%LOCALAPPDATA%\MusicHarbor\` on Windows).
- **Distribution:** these instructions do not provide a signed/notarized release or an installer. macOS may require approval in **System Settings → Privacy & Security** for a downloaded app you trust. Public releases need separate signing/notarization work.

Installing the `dev` extra installs the build tools and test dependencies; it does not run tests. The macOS build uses its captured dependency lock instead. The GitHub workflow also defines cross-platform tests and packaging, but these local build instructions do not require GitHub.

## Performance, progress, and purchase order update

Settings now expose **API requests in flight** (default 3, range 1–6) and **background jobs at once** (default 2, range 1–4). Background jobs are concurrent application tasks, not additional server processes. One project is modified by one operation at a time. All Apple traffic shares a paced request limit, including retries; more concurrency does not override the service's approximate 20 requests per minute. See [Apple's published guidance](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/Searching.html).

Release lookups batch up to five collections, check returned track counts, and fall back to individual lookups when a batch is incomplete. Connections and in-flight requests are reused. Price refresh avoids requesting every individual track again when its parent release was already refreshed. Recording coverage uses an index instead of comparing every recording against every catalog song.

Confirming a match saves its decision independently of the subsequent release lookup. That lookup runs as a visible background job. Progress shows completed-item counts and percentages for each stage; upcoming stages remain grey. Finished, cancelled and failed operations stay in the project history until dismissed with ×, including after an app restart. History occupies one process card in height; scroll upward to review and dismiss older operations.

Recommended purchases and Owned Music group entries by release and sort by unique playlist-recording count descending, combined plays during the selected listening period descending, group price ascending, artist A–Z, then release title A–Z. When synced history is available, releases with plays come first. Releases with zero plays follow and ignore playlist-recording count, sorting by price, artist, then title. Without synced history, playlist-recording count remains first. Release type never affects the order. Group price is the sum of displayed individual-track prices or the full-release price when buying the full release; unknown prices sort after known prices when counts and plays tie. Tracks inside each group retain disc/track order. Display ordering does not change the optimizer's selected purchases or its preference for equivalent same-price album tracks over standalone singles.

**Historical validation:** An earlier source revision reported 122 tests and JavaScript syntax checks passing. Browser checks used a separate sample database and delayed mock Store responses. Those results do not validate the current revision. Real Store traffic was not used for those checks; a completely uncached playlist can still take substantial time under Apple's request limit.


## Source layout and publishing

- `src/musicharbor/`: installable application package, including API, desktop entry point, domain modules, and web assets.
- `scripts/`: first-run launcher and platform-specific source launchers.
- `tools/`: desktop build entry point, PyInstaller shim, and packaged-runtime checks.
- `tests/`: automated checks with isolated databases and mocked services.
- `requirements/`: captured macOS release dependency lock.
- `docs/`: project history, feature notes, interface notes, and GitHub setup documentation.
- `.github/workflows/checks.yml`: cross-platform tests and package builds.

The ignore file excludes local runtimes, databases, secrets, music, exports, and build artifacts. Do not upload project backup JSON files or your application data folder: those can contain personal playlist metadata and local file paths. No credentials or user database are required in the repository. MusicHarbor is licensed under the GNU GPL v3 or any later version; see [LICENSE](LICENSE).

Historical verification results above refer to earlier source revisions. Run the checks in CONTRIBUTING.md on the revision you are using before relying on them. Live account access and signed desktop distribution remain separate integration/release checks.


### Refresh alternative releases and prices

**Purchase Plan → Refresh releases & prices** performs fresh Store searches for each included, identified playlist recording. It checks new listings against the accepted recording, loads matching albums/EPs/singles, and refreshes existing prices. Saved recording identities, selected matches, rejections and ownership decisions stay intact. This lets a newly released album become an option for songs previously available as singles. Unresolved recordings still use Find Store matches. Search results are bounded by the Store API, so discovery cannot guarantee every edition.


### Listening history and ranking

Open **Settings → Sort by your listening history**, choose one source, enter your username, and select **Connect & sync**. ListenBrainz public history needs no password or API key; an optional token field is available if access requires it. Last.fm read-only history does not require account sign-in, but its API requires an application key. The setup panel links to Last.fm’s key-registration page. A distributor can instead configure `LASTFM_API_KEY` on the host. Never commit that key.

Choose **Look back (days)** in Settings (1–3,650 days; default 90), then **Save & sync**. Longer periods take longer to download. Increasing the period temporarily falls back to alphabetical ordering until sufficient history is synced. **Sync last N days** is also available in Purchase Plan and Owned Music. A complete snapshot is saved locally and shared across projects, with progress, errors, and the last-sync time shown. Failed or cancelled syncs retain the previous complete snapshot. Disconnect clears the saved connection, keys and history. Only one provider is used at a time, so mirrored histories are not added together. Data and keys stay outside project backups.

Groups sort by playlist-track count, combined plays over the selected rolling period, price, artist, and release title. With synced history, zero-play groups go last and sort only by price, artist, and title. Without a synced connection, the play-count criterion is skipped and playlist-track count remains first. Duplicate playlist appearances count once. Track order inside albums is unchanged, and listening counts influence Best Value budget selections but never change recording matches. Other purchase strategies retain their original objectives.

History metadata is matched conservatively by title/version and artist, with recording IDs and album metadata used when available to resolve ambiguity. Ambiguous or unmatched listens are not assigned; missing explicitness/master metadata can limit attribution. Refresh history to include new plays; old plays age out automatically. The APIs cannot reconstruct listening that was never scrobbled.

### Consistent release cards and listening processes

Release names and play counts appear inside their cards; the duplicate heading above full releases and single-track groups has been removed. Listening sync now appears in the shared scrollable process history alongside catalog operations. Running syncs can be cancelled; completed, failed, and cancelled syncs remain until dismissed with ×. Listening processes are shared across projects and remain available when no project is selected. Connection and last-sync details remain in Settings.
