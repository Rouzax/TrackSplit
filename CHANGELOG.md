# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Artist image lookup (`folder.jpg` / `artist.jpg`) now resolves CrateDigger's artwork cache by the canonical slug read from the `CRATEDIGGER_ALBUMARTIST_SLUGS` tag (index 0, the primary album artist), rather than by the sanitized display name. The slug is normalized for the filesystem and used to locate `cache/artists/<slug>/` in the CrateDigger data directory. For files that do not carry the slug tag, the slug is derived from the artist name using the same `slugify` logic CrateDigger applies, so the fallback is consistent. This fixes artwork misses caused by display-name truncation (e.g. "Above & Beyond" stored under "Above"), case differences, Unicode normalization differences, and trailing punctuation.

  **Coupling:** this requires CrateDigger to key its artwork cache by slug (the slug-keyed artwork cache change). Both tools must be updated together.

### Removed

- The sanitized-name-based artist image lookup path (`safe_artist_name` helper) is removed. Slug-based lookup is now the sole resolution strategy.

## [0.12.0] - 2026-06-11

### Added

- `--output` now refuses a path that points inside an existing TrackSplit library (an artist or album folder), printing the correct library root and exiting without writing files. This prevents accidentally creating a nested `Artist/Artist/...` path when the library root was intended.

## [0.11.0] - 2026-05-26

### Changed

- Per-chapter title tag now prefers `CRATEDIGGER_TRACK_TITLE` with fallback
  to legacy `TITLE`, matching the rename CrateDigger is making to prevent
  VLC/MediaInfo from flattening the last chapter's title into the
  file-level display.
- Album cover art harmonized with CrateDigger v0.19.0 poster layout:
  merged draw helpers (drop shadow removed), accent line glow matched,
  `PAD_LINE_TO_ARTIST` 28 to 30, `glow_radius` 14 to 16, letter spacing
  on hero text.
- Long artist names on album covers now word-wrap at balanced boundaries
  when the font would shrink below size 80 (e.g. "Swedish House Mafia"
  renders as two lines instead of one cramped line).

### Fixed

- Progress bar no longer leaves a ghost line in the terminal when all files
  are skipped.

## [0.10.2] - 2026-05-23

### Changed

- Tag schema version bump retag path now reuses the existing `cover.jpg`
  from disk instead of re-extracting the background from the source MKV
  and recomposing via PIL. Falls back to recomposition when the cover
  schema is also outdated or `cover.jpg` is missing. Reduces I/O
  contention when retagging many albums in parallel.

## [0.10.1] - 2026-05-23

### Fixed

- Tag schema version bump on the skip path now correctly reports "done"
  instead of "skip (unchanged)". Files were being retagged but
  `process_file` returned `False`, making the CLI display the wrong status.

## [0.10.0] - 2026-05-22

### Added

- `ORIGINALDATE` and `RELEASEDATE` Vorbis comments are now written alongside
  `DATE`, all with the same value. Navidrome (and other servers) use these to
  populate the "original date" and "release date" fields, which were previously
  empty.
- `DISCTOTAL` Vorbis comment (always `1`) written alongside the existing
  `DISCNUMBER`.
- Retag-only pipeline path: when only album-level tags change (artist spelling
  fix, date correction, genre update) but audio and timecodes are identical,
  TrackSplit now retags existing files and rebuilds cover art without
  re-extracting or re-splitting audio. This is significantly faster for
  metadata corrections.
- Tag schema versioning (`TAG_SCHEMA_VERSION`): existing albums are
  automatically retagged on the next run when the output tag set evolves,
  without needing `--force`. Mirrors the existing cover schema version
  mechanism.

### Changed

- `should_regenerate` refactored into `check_regen_level`, returning a
  tri-state `RegenLevel` (SKIP, RETAG, FULL) instead of a boolean. The track
  filename check now runs before the tag comparison to prevent indirect
  filename changes from being missed.

## [0.9.5] - 2026-05-16

### Added

- CrateDigger `CRATEDIGGER_1001TL_LOCATION` tag is now used as a fallback
  when no venue or festival is present. Standalone venue shows that only
  carry a location tag now produce clean album names like "Bay Oval Park
  2026" instead of the raw filename. The location value is also shown on
  the cover art accent line and canonicalized through `places.json` aliases.

## [0.9.4] - 2026-05-12

### Added

- Batch summary panel now shows the log file path at the end of directory runs.

### Changed

- Bug report issue template asks for the automatic log file instead of `--debug` output.
- Troubleshooting docs and CONTRIBUTING.md point at the per-run log file instead of suggesting `--debug`.

## [0.9.3] - 2026-05-11

### Fixed

- Venue names (e.g. "Red Rocks Amphitheatre") are now resolved through
  `places.json` aliases, producing canonical album folder names like
  "Red Rocks 2025" instead of "Red Rocks Amphitheatre 2025". Cover art
  also uses the canonical name.

## [0.9.2] - 2026-05-11

### Changed

- CrateDigger integration now reads `places.json` (renamed from `festivals.json`
  in CrateDigger). The old filename is still accepted as a fallback.

### Fixed

- Removed per-chapter `probe.title_synthesized` debug log that fired once per
  untitled chapter, producing hundreds of redundant lines during parallel
  processing.

## [0.9.1] - 2026-05-08

### Fixed

- Per-chapter MKV tags (track artist, title, genre, label, MBIDs) are now stored in the album manifest and included in change detection. Updates to per-track metadata from CrateDigger now correctly trigger regeneration instead of being silently skipped.
- Track filenames are now compared during change detection. If the resolved filename for any track differs from the stored manifest (e.g. because the track artist or title changed), the album is regenerated.

## [0.9.0] - 2026-05-08

### Changed

- Multi-artist (B2B) sets are now placed under the primary artist's folder with a `(with X)` annotation on the album folder name (e.g. `Martin Garrix/Red Rocks Amphitheatre 2025 (with Alesso)/`) instead of a combined artist folder. The `ALBUM` and `ALBUMARTIST` tags inside track files are unchanged. On re-run, affected albums are regenerated in the new location; the old combined artist folder is not deleted automatically.

## [0.8.2] - 2026-05-08

### Fixed

- Artist folder images now find DJ artwork from CrateDigger's platform cache directory (`~/.cache/CrateDigger/artists/` on Linux, `AppData\Local\CrateDigger\Cache\artists\` on Windows). Previously only the data directories were searched, which never contain the downloaded artwork.
- Artist name sanitization now matches CrateDigger's convention (e.g. "Tiësto" looks up "Ti_sto"), so artists with non-ASCII or special characters in their names get their photos.
- Debug logging in `find_dj_artwork` now reports which directories are checked, whether artwork was found, and the source (cache vs data), making lookup failures diagnosable from the log.

## [0.8.1] - 2026-05-08

### Changed

- Debug log files are now per-command. Each CLI invocation creates its own timestamped log file (e.g. `split-2026-05-08T14-22-01-a3f2.log`) instead of appending to a single rotating `tracksplit.log`. Log files older than seven days are cleaned up automatically on the next run.
- All debug log messages now use a structured `prefix.event: key=value` format (e.g. `pipeline.regenerate: file=X reason=force`) instead of freeform prose, making log files easier to grep and parse.
- `--check` output now includes a "Log directory" row showing the log directory path and the number of log files present.
- Subprocess logging (ffmpeg, ffprobe, mkvmerge, mkvextract) now records failures only. Successful invocations no longer appear in the debug log, significantly reducing log noise during normal operation.
- CrateDigger config resolution is now logged once at startup instead of once per file. Festival alias resolution is deduplicated so each alias is logged at most once per run. Previously a 100-file batch could produce hundreds of identical "candidate dirs" lines.

## [0.8.0] - 2026-04-25

### Changed

- Re-extraction now uses an audio-stream fingerprint (codec, sample rate, channels, duration, time base, bit rate) read from ffprobe instead of the source file's mtime and size. CrateDigger container-level tag rewrites via `mkvpropedit` no longer trigger a spurious re-extract. The fingerprint moves only on real audio changes: re-encode, re-mux to a different codec, trim, channel layout change. Manual re-extracts via `--force` are unaffected.
- The output-tag allowlist that drives re-extraction now matches the tags actually embedded into per-track Vorbis comments. Added: `genres`, `comment`, `albumartist_display`, `albumartists`, `albumartist_mbids`. Changes to any of these now correctly invalidate the cache; previously they were silently ignored.

### Removed

- Manifest source fingerprint no longer stores `mtime_ns`, `size`, or `enriched_at`. Album manifest schema bumps from 2 to 3; existing schema-2 manifests are treated as missing on first run under the new code, triggering a one-time forced re-extract per album.
- Dead `album` and `mbid` keys removed from the tag allowlist (they were never returned by `parse_tags`, so they could never trigger anything).

## [0.7.2] - 2026-04-25

### Changed

- `tracksplit --version` now performs a live check against GitHub Releases on every invocation, ignoring the cached freshness window. Output is one of three states: a single `tracksplit X.Y.Z` line followed by `(latest)` when current; the stale notice when a newer release is available; or just the version line when the network call fails or the check is suppressed via `TRACKSPLIT_NO_UPDATE_CHECK=1`. Suppression by non-TTY output no longer applies on `--version`, since explicit invocation overrides the implicit-suppression rule.
- `tracksplit --check` adds a new `Update status` row reporting the same freshness state. A newer release counts as a warning in the summary; failed or suppressed checks show as informational and do not affect the count.
- The legacy-path warning (added in 0.7.0) now fires at most once per calendar day. A stamp file at `~/.local/state/TrackSplit/legacy-warning.stamp` (or the platform equivalent) records the date of the last warning; subsequent runs on the same day stay silent. Users running several TrackSplit commands in a single session will no longer see the same warning block repeated on every invocation. The warning text, the set of paths that trigger it, and all other behaviour are unchanged. Mirrors the identical change in CrateDigger (PR #24).

## [0.7.1] - 2026-04-24

### Changed

- The rotating log file introduced in 0.7.0 now captures a complete post-mortem trail. Every subprocess invocation (ffmpeg, mkvextract, mkvmerge) routed through `tracked_run` logs its command line and, on non-zero exit, a tail of stderr. Per-track progress (`splitting N/M: <title>`) and Opus-prefix decisions (applied vs skipped, with reason) are logged in `split.py`. Per-file tag-writes in `tagger.py` log a one-line diff (`Tags for X: +added -removed ~changed`) and wrap Mutagen exceptions with a WARNING that names the failing file before re-raising. `extract.decide_codec` logs an INFO line explaining the copy-vs-reencode decision (visible at `--verbose`). `probe.get_opus_packet_duration_ms` distinguishes three reasons for returning None (no packets, duration parse failure, packet-duration disagreement). `update_check` silent-exception paths now log their failure mode. Companion to [CrateDigger 0.14.1](https://github.com/Rouzax/CrateDigger/releases/tag/v0.14.1); the two rotating logs read symmetrically. No behaviour change; console output is unchanged.
- The release workflow is now triggered manually via `gh workflow run release.yml -f version=X.Y.Z` (or the GitHub UI), replacing the prior commit-message-matched trigger. The workflow still validates `pyproject.toml` and `CHANGELOG.md`, builds, tags, and publishes. The local `scripts/release.sh`, `scripts/git-hooks/pre-push`, and `scripts/setup-hooks.sh` have been removed; they existed to construct and gate a very specific commit-message format that the workflow no longer relies on.
- README now has a dedicated `Update Notifications` section covering the startup notice, automatic suppression in non-interactive contexts, and `TRACKSPLIT_NO_UPDATE_CHECK`. The Features list entry is trimmed to a short pointer into that section. No behaviour change.

## [0.7.0] - 2026-04-21

Companion release to CrateDigger 0.14.0, which implements the matching storage layout on the CrateDigger side.

### Added

- Rotating log file written on every run to the platform log directory (`~/.local/state/TrackSplit/log/tracksplit.log` on Linux, `~/Library/Logs/TrackSplit/tracksplit.log` on macOS, `$env:LOCALAPPDATA\TrackSplit\Logs\tracksplit.log` on Windows). The log rotates at 5 MB with five backups kept. Console output is unchanged; the log supplements it.
- Startup warning on every run while any legacy config path from a version before 0.7.0 still exists. Affected paths: `~/.config/tracksplit/config.toml`, `~/tracksplit.toml`, `~/.tracksplit.toml` (Linux/macOS); `$env:APPDATA\tracksplit\config.toml`, `$env:APPDATA\tracksplit\tracksplit.toml` (Windows). The warning lists the offending paths and instructs the user to migrate or delete them.

### Changed

- Config file now lives at a single canonical location per platform: `~/TrackSplit/config.toml` on Linux, `Documents\TrackSplit\config.toml` on Windows. The previous search order (current directory, `~/.config/tracksplit/`, home directory) is removed.
- Update-check cache moved to `~/.cache/TrackSplit/update-check.json` (Linux) and `$env:LOCALAPPDATA\TrackSplit\Cache\update-check.json` (Windows), matching the new folder naming convention.
- CrateDigger data discovery now uses a single-source strategy (first match wins): `CRATEDIGGER_DATA_DIR` environment variable, then walk-up from the input file (max 10 parents), then CrateDigger's own data directory (`~/CrateDigger/` on Linux, `Documents\CrateDigger\` on Windows). No merging across multiple directories.

### Removed

- Config search fallbacks: `./tracksplit.toml`, `./config.toml`, `~/.config/tracksplit/config.toml`, `~/tracksplit.toml`, `~/.tracksplit.toml`. Use the single canonical location instead.
- `~/.cratedigger/` global CrateDigger fallback. CrateDigger data is now discovered via env var, walk-up, or CrateDigger's own data directory.

## [0.6.9] - 2026-04-20

### Added

- `--check` flag: verifies your environment before processing any files. Checks that all required external tools (ffmpeg, mkvmerge, etc.) and Python packages are installed and that config files are present, then exits without processing any video. Exits with code 0 when all required items pass; exits with code 1 if any required tool or package is absent. Optional/informational items produce warnings that do not affect the exit code. Output is grouped by category with a summary line at the end.

## [0.6.8] - 2026-04-20

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
