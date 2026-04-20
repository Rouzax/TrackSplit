# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `--version` flag on the CLI.
- scripts/git-hooks/pre-push hook that gates 'chore: release' commits behind an interactive prompt.
- Startup update notification: prints a notice when a newer GitHub Release is available. Silent in non-interactive contexts; suppressible with TRACKSPLIT_NO_UPDATE_CHECK=1.

## [0.6.7] - 2026-04-19

### Changed

- TrackSplit now automatically refreshes outdated cover art when you upgrade to a version that ships a revised cover renderer. On a normal skip run, if the stored cover layout version for an album is older than the current one, TrackSplit recomposes the cover from saved metadata and re-embeds it into every existing track, then logs either `Cover-only rebuild for <album>: N track(s) re-embedded` or `Cover already current for <album>; schema version bumped to N`. Audio is never re-extracted or re-encoded during this refresh, so it completes much faster than a full rebuild. No `--force` flag is needed. If a cover rebuild fails mid-album, TrackSplit falls through to a full regeneration in the same run so the album is always left in a consistent state.

## [0.6.6] - 2026-04-19

### Fixed

- Noisy `Manifest schema mismatch` warnings when rerunning TrackSplit after the 0.6.5 schema bump. The pipeline's rename-detection scan (`find_prior_album_dirs`) loads every manifest under the output root once per source file, so with pre-0.6.5 manifests still on disk, users saw the same mismatch warning logged many times per run. The warning is now a debug-level log: schema mismatches remain visible under `--verbose` but no longer clutter normal output. Regeneration behaviour is unchanged; affected albums still rebuild automatically.

## [0.6.5] - 2026-04-19

### Fixed

- Short click at track boundaries in gapless-aware players (Symfonium, mpv) when output format is Opus. The root cause was that ffmpeg wrote `pre_skip = 312` on stream-copied mid-stream cuts; Opus is a lapped-transform codec whose SILK mode keeps multi-frame prediction history, so the decoder needed warmup samples that weren't there. The fix prepends two 20ms prefix frames (40ms total) to every track after the first and rewrites OpusHead `pre_skip` to 1920, so the decoder discards the warmup cleanly and audio starts at the chapter boundary. One prefix frame was not enough in practice; two frames give the SILK predictor enough context to stabilise. Sources with non-20ms Opus frames or multichannel mapping fall back to libopus re-encode. The manifest schema version is bumped to 2, so every album is rebuilt on the first run after upgrading; this regenerates affected Opus albums without requiring `--force` or manual intervention. Note: the 1-2s gap between tracks in the Jellyfin app is a player architecture limitation (no continuous decode across tracks) and cannot be fixed at the file level. Use Symfonium, mpv, or another gapless-aware player for seamless playback.
- Artist canonical-name resolution was non-deterministic when `dj_cache.json` and `artists.json` disagreed on the casing of a canonical name (for example, `"AFROJACK"` vs `"Afrojack"`). Both casings were inserted as canonical values, and the fallback resolver iterated them via `set(...)`, whose hash-randomized ordering changed between Python processes. Symptom: affected albums were regenerated on every rerun with a log line such as `regenerate ...: tag 'artist' changed ('AFROJACK' -> 'Afrojack')`. The fix replaces `set(...)` with `dict.fromkeys(...)`, preserving insertion order so `dj_cache.json` (loaded first) consistently wins. Users with conflicting configs now get a stable canonical on every run, but should still reconcile the two files to choose the casing they actually want.
- Status lines in the terminal rendered backslashes before `[` and `]` in filenames, for example `2025 - Afrojack - EDC Las Vegas \[kineticFIELD\].mkv` instead of `2025 - Afrojack - EDC Las Vegas [kineticFIELD].mkv`. The cause was `rich.markup.escape()` being applied to name and detail strings passed to `Text.append()`, which does not parse markup and does not need escaping. Brackets in filenames now display correctly across all status lines (done, skipped, error, cancelled).

## [0.6.4] - 2026-04-18

### Added

- Multi-line artist rendering on `cover.jpg`. When the artist field contains ` & `, ` B2B `, ` VS `, or ` X ` (with surrounding spaces), each artist renders on its own line, with the connector carried to each subsequent line. The parenthetical form `"Act (A & B)"` splits into the act on line 1 and the inner artists on line 2. The shared font is sized to fit the longest line so the stack stays aligned. Readability on small Kodi/Jellyfin thumbnails is preserved because each line is shorter and fits at a larger font size.
- Festival accent-line fallback on `cover.jpg`. The line just below the accent rail previously rendered only when a festival name was present. It now falls back to venue, then to the first comma segment of stage. When stage fills the slot, the separate stage subline below is suppressed so the same text does not appear twice. Whitespace-only festival, venue, or stage values are treated as empty and fall through the chain.

### Changed

- Stage rendering is symmetric regardless of role. When stage fills the festival accent slot, it uses the same first-comma-segment collapse as the stage subline, so `"Main Stage, Boom, Belgium"` renders as `"Main Stage"` whether it lands in the accent slot or the subline.

### Docs

- `docs/output.md`: `cover.jpg` section expanded to describe layout, multi-artist line breaks, the group-name short-alias workaround, and the festival accent fallback chain.

## [0.6.3] - 2026-04-16

### Changed

- Intro tracks are now only created when the pre-chapter gap is 5 seconds or longer. Shorter gaps are folded into track 1 so no audio is dropped and no sliver files are written. Affected albums are rebuilt automatically on the next run.
- `.tracksplit_manifest.json` now records `intro_min_seconds`. Manifests written before this version lack the field and are treated as up-to-date unless the stored first-chapter gap falls under the new threshold.

## [0.6.2] - 2026-04-14

### Fixed

- Album name for venue-based Tier-2 events (no `CRATEDIGGER_1001TL_FESTIVAL` tag, e.g. Red Rocks, single-artist venue recordings). Previously the album fell back to the full filename stem, producing names like `"2025 - Martin Garrix & Alesso - Red Rocks"`. Now falls back to `CRATEDIGGER_1001TL_VENUE` first, then `CRATEDIGGER_1001TL_STAGE`, producing clean names like `"Red Rocks Amphitheatre 2025"`. Year comes from `CRATEDIGGER_1001TL_DATE` when present, otherwise from the filename stem. The year is not appended when it is already present in the location string, so stages that embed their own date (`"Bay Oval Park, New Zealand 2026-01-31"`) stay unchanged. Named festivals (Tomorrowland, AMF, etc.) are unaffected.
- B2B venue sets no longer collide with solo sets at the same venue + year. When `CRATEDIGGER_ALBUMARTIST_DISPLAY` is empty but `CRATEDIGGER_1001TL_ARTISTS` lists 2+ performers, TrackSplit now synthesizes the album-artist display by joining names with `" & "`. This produces a distinct artist folder (`Martin Garrix & Alesso/Red Rocks Amphitheatre 2025/`) instead of folding the B2B into the uploader's solo folder. Files where CrateDigger has set `CRATEDIGGER_ALBUMARTIST_DISPLAY` (festival B2B sets) are unaffected: the explicit value still wins. Existing B2B venue outputs will rebuild into a new artist folder on the next run; the old folder remains as an orphan until deleted.

### Changed

- Per-chapter CrateDigger tags renamed in CrateDigger 0.12.5 are now read under their new prefixed names: `CRATEDIGGER_TRACK_PERFORMER`, `CRATEDIGGER_TRACK_PERFORMER_NAMES`, `CRATEDIGGER_TRACK_LABEL`, `CRATEDIGGER_TRACK_GENRE`. The legacy unprefixed names (`PERFORMER`, `PERFORMER_NAMES`, `LABEL`, `GENRE`) remain supported for files enriched by older CrateDigger versions, so a mixed library keeps working through the compat window. `MUSICBRAINZ_ARTISTIDS` and the per-chapter `TITLE` were not renamed and continue to be read under their existing names.

### Docs

- Added "CrateDigger cache reuse" section to `docs/output.md` documenting which CrateDigger cache files TrackSplit reads and the lookup chain (global `~/.cratedigger` plus walk-up to 10 parents).

## [0.6.1] - 2026-04-14

### Removed

- Internal `CRATEDIGGER_MBID` single-value fallback path. `ALBUMARTISTS` and `MUSICBRAINZ_ALBUMARTISTID` are now always sourced through the unified multi-value pipeline: CrateDigger's `CRATEDIGGER_ALBUMARTIST_MBIDS` for enriched files, or a single-element list synthesized from `ARTIST` and filled from `mbid_cache.json` for tier-1 sources and older enrichments. The `AlbumMeta.musicbrainz_artistid` field and the regex-based collab suppression guard are gone; equivalence is preserved because a collab display string like "X & Y" misses the MBID cache, lands an empty slot, and the "omit all-empty" rule in the tagger drops the tag. Re-run `cratedigger enrich` on any stale pre-`CRATEDIGGER_ALBUMARTIST_MBIDS` enrichments whose artist is not in `mbid_cache.json`.

### Changed

- Tier-1 MKVs (no CrateDigger tags) now emit `ALBUMARTISTS` in addition to `ALBUMARTIST`. Value is a single-element list containing the resolved album artist. Picard-compatible, no behavior change for solo sets in Jellyfin / Lyrion.

## [0.6.0] - 2026-04-14

### Added

- Per-track `ARTISTS` multi-value Vorbis tag for individual artist linking in Lyrion and Jellyfin. Remixers are included even when they are not in the display `ARTIST` string.
- Per-track `MUSICBRAINZ_ARTISTID` multi-value tag, positionally aligned with `ARTISTS`. Empty slots preserved when an individual's MBID is unknown, so indexed consumers stay aligned.
- Per-track `GENRE` sourced from CrateDigger's chapter-level `GENRE` tag when present. On enriched tracks this replaces the old behavior of stamping every track with the album's full 1001Tracklists genre list, so Lyrion and Jellyfin genre browsers now show the track's own genre rather than a superset. Tracks without a chapter-level genre still fall back to the album's list.
- Album-level `ALBUMARTISTS` multi-value tag for B2B sets (`"Armin van Buuren"`, `"KI/KI"`), plus aligned multi-value `MUSICBRAINZ_ALBUMARTISTID`.
- Opt-in end-to-end integration test (`tests/integration/`) that runs `cratedigger identify` + `enrich` + `tracksplit` against fresh MKVs. Env-gated, skips by default.

### Changed

- `ARTIST` display string now prefers CrateDigger's per-chapter `PERFORMER` tag, preserving "Artist ft. Remixer" forms verbatim.
- `ALBUMARTIST` display prefers CrateDigger's `CRATEDIGGER_ALBUMARTIST_DISPLAY` when present (e.g. "Armin van Buuren & KI/KI" for B2B sets).
- `MUSICBRAINZ_ALBUMARTISTID` is now multi-value when CrateDigger supplies the album-level artist list. Single-value legacy path (with collab suppression) kept for older enrichments (removed in 0.6.1).

## [0.5.1] - 2026-04-12

### Fixed

- Per-track artist display in Lyrion/LMS: the album-artist MusicBrainz ID was being written as the per-track `MUSICBRAINZ_ARTISTID`, causing LMS to dedupe all tracks to a single contributor row and show the first track's artist for every row. The MBID now goes to `MUSICBRAINZ_ALBUMARTISTID` (Picard-canonical), and the per-track key is never written. Jellyfin display is unchanged by this fix (it dedupes by name, not MBID).
- Per-track artists whose case-insensitive form equals the album artist are now normalized to the album artist's casing (e.g. "AFROJACK - ID" with album artist "Afrojack" → `ARTIST=Afrojack`). Prevents duplicate contributor rows in Lyrion and stray upper/lowercase variants in Jellyfin. Applied as defense-in-depth so tier-1 sources and un-cached artists still get clean output.
- Album-artist MBID is now suppressed for B2B/collab album artists ("X & Y", "X vs. Y", "X x Y"): a single MBID cannot identify two performers, and emitting only one half's MBID would merge the collab album into that member's solo discography.

## [0.5.0] - 2026-04-12

First release with a proper project presence: a hero README, a published docs site, an animated landing page, CI, and a rounded-out CLI UX.

### Added

- Pre-flight tool check on every run: `ffmpeg` and `ffprobe` are verified up front with OS-specific install hints.
- `tracksplit --check` subcommand that probes `ffmpeg`, `ffprobe`, and `mkvextract` and prints their versions.
- Single-file runs now print a final summary line naming the album directory and the number of tracks written.
- `tracksplit.toml.example` shipped at repo root with a commented `[tools]` section.
- MkDocs Material documentation site: Home, Getting Started, Usage, Configuration, Output Structure, Troubleshooting, FAQ.
- Custom animated landing page with hero, four-card feature grid, two-row poster gallery, three-step workflow, and install block.
- GitHub Actions: pytest matrix on Python 3.11 / 3.12 / 3.13; MkDocs + landing page deploy to Pages.
- Issue templates (bug + feature) and Dependabot for pip and github-actions.
- `LICENSE` (GPL-3.0) and `[project.urls]` metadata in `pyproject.toml`.

### Changed

- Error reporting across the pipeline: known failures (missing tools, disk full, FFmpeg subprocess errors) now surface as one-line reasons; full tracebacks are kept behind `--debug`.
- `--workers` help text expanded to explain the default and when to tune it.
- README rewritten with a hero banner, badges, poster gallery, Configuration section, and a pointer to the sibling [CrateDigger](https://github.com/Rouzax/CrateDigger) project.

### Fixed

- Documentation corrected to reflect the actual output folder layout (`Artist/Festival Year (Stage)/` for CrateDigger-tagged sources, `Artist/<filename-stem>/` for untagged sources).
- `test_cli_format_flag_in_help` made robust to Rich's line-wrapping in narrow CI terminals.

## [0.1.0] - initial

- Initial chapter splitting, codec-aware output, metadata tagging, cover art generation, and re-run detection.
