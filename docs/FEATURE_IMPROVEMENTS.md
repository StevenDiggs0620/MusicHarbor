# Feature improvements

All twelve requested areas have code changes. Implementation was reviewed by reading source; no tests, application launches, linters, browser checks, or smoke checks were executed. Packaging is the sole execution step authorized for this update. Earlier test-pass statements in README describe earlier revisions.

| Area | What changed |
| --- | --- |
| 1. Export copies | Format, folder, and quality preferences; deterministic path tie-breaks; saved per-recording overrides; missing overrides require correction instead of silently choosing another copy. Existing files acquire quality metadata on their next scan. |
| 2. Purchase views | Strategy-order cards retain exact queue positions. Grouped albums remain available independently. Cheapest and budget set selections are explicitly distinguished from priority queues. |
| 3. Ownership | Removing full-release ownership offers either preservation of previous partial ownership or clearing that release's contribution. Other ownership sources remain effective. |
| 4. Backup choices | Project-only downloads remove unrelated library identities and local path settings. Full-library downloads contain all projects and shared file metadata. Full restores are additive, atomic, preserve existing file decisions, and require rescanning restored files. Both use the existing 128 MiB limit; audio and credentials are excluded. |
| 5. Library loading | Indexed candidate selection fetches related library identities for project work. The Local Library screen loads 100 files per page. Saved projects reference shared match evidence and omit already-shared file rows. Legacy snapshots are compacted on subsequent saves. Full scans and explicit file decisions still load the library needed for consolidation. |
| 6. Calculation speed | One ownership pass, direct sparse coverage population, pre-indexed album/source relationships, and compact solver inputs replace repeated scans. Preparation and solving share a time budget; a parent process enforces an overall worker timeout. |
| 7. Planning jobs | Planning starts on Calculate, shares the configured job gate, supports cancellation by terminating its isolated solver process, and caches a bounded set of results for five minutes using relevant data, ownership, listening counts and options. Cheapest comparison runs sequentially and reuses the cache. |
| 8. Retention | Settings control job age, price-change age, and export count. Startup/hourly maintenance clears expired cache and orphaned/old completed jobs. Project saves trim generated histories. Only changed prices add observations. |
| 9. Spotify imports | Before/after snapshot IDs and item totals must agree; changed imports retry up to three times before leaving existing membership untouched. Missing consistency evidence produces a retryable error. |
| 10. Tokens | Application tokens are reused until expiry, keyed by credentials and invalidated on disconnect. Authorization generation also guards an in-flight refresh. |
| 11. Packaging/upgrades | Private source runtimes use interpreter/architecture/dependency fingerprints, an OS setup lock, and atomic publication. The current macOS CPython 3.14 environment has exact release dependency pins, enforced by packaging. Bundles include a dependency/source manifest. Optional packaged-runtime and native-window checks are provided. |
| 12. Structure/coverage | Export policy, library indexing, retention, portable backups, runtime setup, planning and interface workflow components have separate modules and typed boundary models. New backend and optional browser regressions cover these workflows. |

## Verification for a later authorized run

- Existing and new Python checks: `python -m pytest -q`.
- Browser checks: install the `browser` extra with `python -m pip install -e ".[browser]"` and install Playwright Chromium, then run `tests/test_browser_workflows.py`. These use mocked API responses and an isolated static server.
- Packaged runtime: run the packaged executable with `--packaging-smoke`.
- Native window: run it with `--window-smoke` on a desktop session. Both smoke modes use an isolated temporary database and never open the user's projects.
- Before public release, manually exercise the native save dialog for exports/backups, external Store links, and Spotify's external-browser authorization return. These require real desktop/service interaction and are not claimed verified by the smoke modes.

## Distribution boundaries

The local macOS app uses ad-hoc signing unless a `PLAYLIST_SIGNING_IDENTITY` is supplied. Public Apple notarization still requires the owner's signing credentials and a separate submission; it was not performed. Windows/Linux CI retains its platform dependency installation and now checks packaged runtime startup; those platforms do not yet have a lock captured from a validated release environment. The exact macOS pins describe the local packaging environment, not a claim that its runtime tests have passed.
