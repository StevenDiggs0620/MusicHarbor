# Identity and purchasing changes

## Investigation of the existing implementation

Regression coverage includes a 505-entry playlist with 500 recording identities and five duplicate appearances. Playlist occurrence counts are distinct from unique recording counts.

1. `csv_import.parse` preserves occurrences in `tracks`, consolidating repeated Spotify IDs only when the supplied recording metadata agrees. The recording table displays unique objects, not every playlist appearance. There is no 500-entry limit.
2. CSV deduplication uses `(Spotify ID, metadata signature)`; direct Spotify import also consolidates agreeing ISRCs. Occurrence order is separate.
3. `tracks` represents playlist entries; `recordings` represents source recording identities. Newly imported identities are provisional until resolved.
4. Recording candidates already contained score, confidence, version compatibility and explanatory reasons. `selected` was an accepted iTunes reference listing, not the canonical recording ID.
5. The old scanner searched only `p['recordings']`, which previously contained just playlist recordings. Even a single high-confidence file result was deliberately left for review.
6. Existing title/artist/duration/ISRC scoring was reusable. Missing explicitness made all ordinary local files conservative matches. The new shared resolver preserves that safety unless there is stronger identifier evidence.
7. Local metadata and paths were saved, but only inside a project. Confirming a file did not affect `rec_owned`.
8. `releases` held both whole releases and individual track purchase products. Each had its own price and recording coverage. This structure and the existing integer set-cover solver were retained.
9. A Store track was not the literal recording ID, but its accepted metadata acted as the reference for alternate release coverage. It remains evidence rather than canonical identity.
10. Reused pieces: CSV parsing and validation, occurrence order, catalog search/cache/throttling, candidate scoring, manual search/rejection, release lookup, coverage validation, price refresh, solver, export, and project backup.

## Phase 1: identity and matching

- Import retains every occurrence and its source metadata. The import screen distinguishes entries, recording identities and duplicate appearances, and can expand the complete source-order list.
- Invalid CSV rows are reported with line numbers. Imports with errors remain atomic: no partial project is silently created.
- CSV import starts a background matching job automatically. Direct Spotify import runs matching after saving the imported entries.
- `identity.decide` is the common catalog-resolution decision for playlist and local sources. It reports EXACT, HIGH_CONFIDENCE, NEEDS_REVIEW or UNMATCHED and stores score/reasons/candidates. Scores are heuristic scores, not calibrated probabilities.
- Several equivalent release listings do not cause ambiguity. Close competing recording versions do.
- Library files and canonical local recording identities have independent SQLite tables. Files are identified without playlist membership; stable shared identities can be reused across projects. Legacy project files remain readable and unmatched files get independent review identities.
- Scanner reads title, artist, album, album artist, millisecond-resolution duration, track/disc numbers, filename, ISRC, MusicBrainz recording ID, embedded iTunes track ID (with direct catalog lookup), and supported explicitness/advisory tags. It retains unknowns rather than guessing from filenames or treating missing explicit tags as clean.
- A valid embedded recording identifier establishes a local identity even without a Store listing. Conflicting supplied versions, explicitness or durations prevent automatic cross-source consolidation.
- Existing identified local files confer recording-level ownership. Explicit project ownership overrides still take precedence. Missing files no longer confer ownership.
- Local review searches catalog recordings, not playlist entries. Correcting a file does not rewrite a formerly linked playlist recording, and correcting a playlist match does not reidentify an owned file.
- Optimization requirements come only from playlist entry recording IDs. Unrelated and unresolved library identities never become purchase requirements.

## Phase 2: release discovery

- Canonical identity is independent of album/single IDs. Equivalent accepted source identities consolidate without dropping playlist entries.
- Full releases and their individual track products retain separate price, purchase type, parent release ID/name, release classification, URL and coverage.
- Classification uses available collection name, artist, track count and full tracklist. Source-album agreement, then earliest available full-album date, distinguishes a likely main album from other artist albums. Original studio albums cannot always be distinguished definitively from other artist albums using these fields alone. Unknown short releases conservatively rank with fallback options.
- Same-price individual purchases prefer full albums, deluxe editions, EPs, compilations, then singles. Store recording/version correctness is checked before any purchase preference.
- The Store search is bounded and cannot enumerate every release or guarantee worldwide catalog completeness. Manual search and selected-release lookup remain available.

## Phase 3: purchase optimization

The existing global integer set-cover optimizer remains in use. For the cheapest strategy, actual cent cost is the primary objective, number of purchases is secondary, and release preference breaks remaining ties. Preference cannot justify paying an extra cent. Track and full-album coverage are separate purchase candidates. A duplicated playlist recording is required once. Results still explicitly report uncovered recordings and solver optimality for discovered priced candidates.

The album-track preference supports the requested future album-completion value; it does **not** invent eligibility or subtract speculative Complete My Album credits from the current plan.

## Validation and practical limits

**122 regression tests pass**, along with JavaScript syntax validation. Browser checks confirmed entry counts, album-track purchase presentation, local catalog search, manual confirmation and the resulting removal of owned recordings from the purchase plan. Regression tests cover the requested 505/500 distinction, invalid rows, equivalent single/standard/deluxe/compilation listings, live/remix/remaster/rerecording conflicts, explicit/clean conflicts, ambiguity, independent library identification, shared ownership, missing files, catalog interruption, override isolation, and individual-track versus whole-album costs.

September 16 performance verification added coverage for bounded parallel work, API pacing and cooldowns, request reuse, complete release batches and fallback, redundant price requests, indexed coverage equivalence, responsive confirmation, queued job cancellation, persistent history, progress percentages, safe cancellation of blocking work, stale shared-library writes, and all purchase ordering rules. A separate browser fixture with delayed mock Store responses verified settings saving, confirmation before release loading, 50% search progress, upcoming grey stages without bars, completed history after reload, dismissal, and three album tracks grouped in track order before a singleton from another album. No live Store or Spotify account integration was exercised in this update.

A separate sample database was used for browser checks. User data is kept outside the repository; development checks use isolated temporary databases. Restart the app to load the code and create the additive library tables; run Find Store matches for existing imports and rescan existing folders to perform the new automatic resolution.

Actual match rates depend on file tags and Store metadata. A file without sufficient version or identifier evidence stays in review. This implementation performs metadata matching, not acoustic fingerprinting, and cannot prove that indistinguishably tagged audio files contain identical masters.


## Playlist updates and catalog retention

`playlist_update.merge_playlist` maps incoming source identities to existing canonical records conservatively, keeps source aliases through consolidation, and retains catalog records removed from playlist membership. Add uses occurrence-count union; replace uses the incoming occurrence sequence. Neither operation clears purchase products or local-file relationships. Playlist membership alone controls optimization and export scope.

Both CSV and Spotify updates run through the project background-operation lock. CSV validation finishes before the operation starts. Spotify pagination completes before membership changes. Updates save membership before incremental discovery, reuse persisted searches and complete release lists, and save completed search work if a later stage fails. Explicit discovery and price refresh remain available.
