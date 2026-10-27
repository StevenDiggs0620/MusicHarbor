# Static review repairs — October 6, 2026

Changes implement the 35 retained findings from the bugs-only review. This is an implementation record, not a test-pass report. No application code, tests, builds, linters, or dependency installations were run during these repairs. Regression tests were added/updated for later execution.

| Review finding | Implementation |
| --- | --- |
| 1, 13 | Consistent recovery checkpoints rebuild coverage before saving interrupted work; ordinary discovery also saves completed work. |
| 2 | Consolidation preserves an explicit ownership override when the surviving identity has no override. |
| 3 | Backup and restore share a 128 MiB limit and a validation schema; the old 10,000-recording restriction is removed. Backup creation validates that its output is restorable. |
| 4, 5 | Resolution, consolidation, and coverage receive the same preferences. Permitted version differences and whitespace are normalized consistently. |
| 6, 7 | Recording changes have independent shared-library version tracking. Existing project copies receive current shared evidence while retaining project decisions. Changed evidence invalidates derived coverage. |
| 8 | Shared-write conflicts return an explicit error instead of reporting success. |
| 9 | Identifier-free updates allocate existing occurrence counts deterministically, including identities already consolidated by catalog matching. |
| 11 | Manual file identification retains embedded identifiers and provenance; conflicting evidence is retained separately. |
| 12 | Partial artist-credit overlap alone cannot establish a high-confidence automatic match. |
| 14 | Job initialization failures release busy/running state. |
| 15 | Scanning enumerates incrementally and checks a cooperative cancellation event between entries. A currently blocked individual filesystem operation must still return. |
| 16 | Project mutations, expensive searches, settings recomputation, exports, restore processing, and project/job writes use worker execution while retaining project reservations. |
| 17 | A settings reservation blocks new project mutations through network shutdown and settings recomputation. |
| 18 | Legacy migration commits atomically and skips already migrated project IDs. |
| 19 | Partial release refreshes retain the previous complete track list, update prices independently, and display the incomplete-refresh condition. |
| 20, 21, 23 | Nested backup models validate types, finite numbers, and references; restore rebuilds coverage and limits upload bytes while streaming. |
| 22 | Candidate scores, source row numbers, identity summary values, and export counts are escaped before HTML interpolation; restored values also receive type validation. |
| 24, 25 | Selection and rendering generation checks prevent stale responses from replacing the current project or accessing a departed page. Export previews use the same stale-response protection. |
| 26 | Background refreshes retain actual dirty form elements, including selected files, CSV draft state, and export options. |
| 27 | Progress polling and completion refresh retry transient failures with capped backoff. |
| 28 | Both recording and local-file review offer additional candidate batches beyond the first 100. |
| 30 | Release-card counts filter by current playlist membership. |
| 31 | Currency estimates render with every plan-result refresh, including filtering. |
| 32 | CSV header detection skips empty leading lines. |
| 33 | Known MusicBrainz identifier conflicts cannot receive title-only listening credit. |
| 34 | Consolidation returns a canonical-ID map used by match-decision responses. |
| 39 | Related project and library changes commit in one transaction; version baselines advance only after commit. |
| 41, narrowed | Pending OAuth requests bind to a client and authorization generation; disconnect/client changes invalidate completion. |
| 47, narrowed | The import regression wait treats both queued and running jobs as nonterminal. |

Earlier README statements about passing tests describe earlier revisions, not these changes. Runtime, browser, desktop, and regression verification remain pending at the user's request.
