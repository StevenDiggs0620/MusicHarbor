# MusicHarbor — version 1.3.0

MusicHarbor is the new name for the app. The interface, desktop titles, source launchers, packaging, API identity, service user agent, documentation, and newly exported backup identifiers use the new name.

## Existing installations

Existing data is reused in place. The historical data directory and database filename remain supported to avoid moving a live database, splitting collections, or losing credentials. New installations use MusicHarbor (musicharbor on Linux) and musicharbor.sqlite3. MUSICHARBOR_DATA overrides the data directory; the older PLAYLIST_PURCHASER_DATA variable still works. MUSICHARBOR_LEGACY and the older legacy variable are supported for prototype imports.

Old playlist and full-library backups can still be restored. New backups identify themselves as musicharbor or musicharbor-library. Older app versions may not recognize new backups. Existing browser preference keys and the local service port remain unchanged.

The source folder has not been renamed, and earlier release bundles remain historical artifacts. The new release is under dist/releases, with its exact location in dist/LATEST_RELEASE.txt. Quit the previous running instance before opening MusicHarbor; both versions use the same local service port and may share the same saved data.

## Verification

Source review and packaging only. The app and tests were not run, following the existing request. Packaging verification is not runtime verification of data compatibility or application behavior.
