# Interface usability fixes — version 1.2.0

This update supersedes the earlier ten-change guided interface. Frequent controls are visible again, with supporting details in clearly named disclosures. Existing features remain accessible.

| Requested improvement | Implementation |
| --- | --- |
| 1. Direct navigation | Six sidebar destinations: Overview, Playlist songs, Check matches, Purchase plan, My music, and Export. Management, Settings, and Help remain available. |
| 2. Accessible song list | Search, inclusion, ownership, review, original playlist order, and Add or replace songs. |
| 3. Less repeated navigation | Compact workflow guidance during import; other screens focus on their own actions. |
| 4. Visible review controls | Accept, search, skip, ownership, and alternative versions are visible. Technical evidence is expandable. |
| 5. Accurate review scope | Playlist review excludes unrelated library recordings. Needs review, Set aside, and All songs have distinct counts. |
| 6. Weak suggestions | Warnings and version differences accompany uncertain suggestions. Search is primary; acceptance is secondary. |
| 7. All strategies visible | One selector exposes all six strategies, with descriptions and relevant budget or artist fields. Penalty and conversion remain advanced. |
| 8. Direct purchase actions | Store links, ownership, and Choose owned songs are visible. Exclusion and price history use specific labels. |
| 9. Clear purchase views | Priority strategies use Buying order; set-based strategies use Individual purchases. By album groups the same selected purchases without changing selection or total. |
| 10. Stale-plan notice | Results show their calculated settings. Relevant edits show a recalculate warning. Request guards prevent outdated results replacing newer calculations. |
| 11. Budget results | Successful partial plans show songs and cost within the budget. Available songs not selected are distinguished from unavailable priced matches. |
| 12. Export first | Download and ready-entry count appear above collapsed omission categories, with full counts and bounded examples. |
| 13. Device paths | Visible destination folder and before/after example. Source folder, replacement method, format, and slash style remain advanced. Device export does not assume Windows paths. |
| 14. Collection first | My music starts with owned music. Scan and local-file review remain visible; listening history is secondary. |
| 15. Consistent language | Primary screens use playlist/song terminology. Cards distinguish songs, singles, EPs, albums, and other releases when metadata permits. |
| 16. Desktop and packaging | Protected local endpoint for the native folder chooser. Versioned release folders avoid overwriting a running bundle; packaging checks executable structure and signature. |

## Feature access

- Add playlist: CSV preview/import, Exportify guidance, direct Spotify import.
- Playlist songs → Add or replace songs: CSV/Spotify updates and linked Spotify replacement.
- Check matches: confirmation, rejection, manual search, pagination, required songs, release lookup, ownership overrides/reset.
- Purchase plan: six strategies, refresh prices, release search, comparison, alternatives, conversion, and listening ranking.
- Purchase cards: song/release purchases, ownership/undo, partial ownership, inclusion/exclusion, covered songs, whole-release alternatives, and price history.
- My music → Local files: native folder choice or manual path, scan, paged library, search/confirmation, and file details.
- Export → Advanced: M3U/M3U8, EXTINF, slash style, source-folder or legacy text replacement, format/folder/quality preferences, per-song file overrides.
- Manage playlists: create, rename, duplicate, delete, backups, restore. Settings retains Spotify, listening, matching, performance, and retention.

## Verification boundary

Reviewed by reading source. The app, tests, linters, and standalone syntax checks were not run. Packaging does not establish runtime correctness. Fresh macOS launch and the native folder chooser still require runtime checking; the earlier launch failure is not proven resolved.

The latest packaged app is identified by `dist/LATEST_RELEASE.txt`, with its ZIP alongside it. Quit any older running instance before opening the new release. Saved user data remains outside the application bundle.
