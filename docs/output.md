# Output Structure

TrackSplit writes one album folder per video into your output directory. This page explains what every file is, what it is for, and what changes when your source files carry CrateDigger metadata.

## What you get

After a successful run you will find a folder structure like this inside your output directory:

```
Artist/
  folder.jpg
  artist.jpg
  Festival Year (Stage)/
    01 - Track Title.flac
    02 - Track Title.flac
    ...
    cover.jpg
    .tracksplit_manifest.json
```

Every file in that structure has a specific purpose. Some are for your music server. One is for TrackSplit only.

## The two levels of output

The quality of your output depends on what metadata is in the source video.

**With CrateDigger tags (enriched sources):** TrackSplit has everything it needs. The album folder is named `Festival Year (Stage)` when the source carries a festival name (most common case), or `Venue Year` for non-festival venue recordings (e.g. a club or arena set with no named festival). Tracks get canonical artist names, MusicBrainz IDs, festival and venue details, and per-track genre. Your music server can link every artist, album, and collaborator correctly.

**Without CrateDigger tags (any chaptered video):** TrackSplit still works. It infers the artist and album from whatever it finds in the filename and embedded tags, numbers the tracks, and writes what it can. The album folder is named after the source filename. You get a properly split, tagged album, just without the rich festival metadata.

In both cases you get the same files. The difference is in how accurate and complete the metadata inside those files is.

## Directory layout explained

### Artist folder

```
Artist/
  folder.jpg
  artist.jpg
```

The top-level folder is named after the artist. Inside it, two image files are placed at the artist level so your music server can display artist artwork:

- `folder.jpg`: the artist cover image, picked up by Jellyfin and similar servers as the artist folder image.
- `artist.jpg`: the same image under a different name, used by Kodi and other players that look for `artist.jpg` specifically.

Both files contain the same image. TrackSplit writes both so the artist looks correct in whichever server you use.

### Album folder

```
Festival Year (Stage)/
  01 - Track Title.flac
  02 - Track Title.flac
  cover.jpg
  .tracksplit_manifest.json
```

Each video gets its own album folder inside the artist folder. The folder name comes from the metadata:

- **CrateDigger source with a festival tag:** `Festival Year (Stage)`, or `Festival Year` when no stage is set.
- **CrateDigger source without a festival tag (venue recording):** `Venue Year` using the venue name, or the stage name if no venue is set. If that location string already contains the year (e.g. `"Bay Oval Park 2026-01-31"`), the year is not appended a second time.
- **Plain chaptered video:** the source filename (without extension).

### Track files

One audio file per chapter. Filenames follow the pattern `NN - Title.flac` (or `.opus`), where `NN` is a zero-padded number starting at `01`.

If the video has audio before the first chapter marker (an unlabelled intro section) and that pre-chapter gap is at least 5 seconds, TrackSplit creates an extra track numbered `00 - Intro` for that segment. Gaps shorter than 5 seconds are folded into track 1 instead, so track 1 begins at the start of the file and absorbs the lead-in audio. This avoids tiny sliver files for negligible gaps. The threshold is fixed and not user-configurable.

### `cover.jpg`

The album cover image, placed at the album level. It is also embedded inside every track file, so your music server sees it whether it reads the folder image or the file tags.

This file is always created.

### `.tracksplit_manifest.json`

A small record file TrackSplit uses internally. It stores a fingerprint of the source file and the settings used, so TrackSplit can detect on the next run whether anything changed and skip the album if not.

**This file is only for TrackSplit, not for your music server.** Your server will ignore it. You can delete it at any time to force TrackSplit to rebuild that album. You do not need to back it up.

## What your music server uses

| File | Used by music server | Used by TrackSplit |
|---|---|---|
| `*.flac` / `*.opus` | Yes, these are the tracks | No |
| `cover.jpg` | Yes, album artwork | No |
| `folder.jpg` | Yes, artist artwork | No |
| `artist.jpg` | Yes, artist artwork (Kodi) | No |
| `.tracksplit_manifest.json` | No | Yes, skip detection only |

## Tags written to every track

TrackSplit embeds metadata tags inside each audio file. Your music server reads these to display artist names, album titles, track numbers, and dates.

The core tags written on every track:

| Tag | What it contains |
|---|---|
| `TITLE` | The track title (from the chapter name) |
| `ARTIST` | The performing artist for this track |
| `ALBUMARTIST` | The headlining artist for the whole set |
| `ALBUM` | The album name (same as the folder name) |
| `TRACKNUMBER` | The track number |
| `DISCNUMBER` | Always `1` |

Additional tags are written when the information is available:

| Tag | When it appears |
|---|---|
| `DATE` | When the source has a date |
| `TRACKTOTAL` | When the total track count is known |
| `GENRE` | Per-track genre from CrateDigger, or the album genre as a fallback |
| `PUBLISHER` | When present in the source |
| `COMMENT` | When present in the source |
| `ARTISTS` | Multi-value list of individual artists (enables per-artist linking in Jellyfin and Lyrion) |
| `ALBUMARTISTS` | Multi-value list of individual album artists (for B2B sets) |
| `MUSICBRAINZ_ARTISTID` | Per-artist MusicBrainz IDs, aligned with `ARTISTS` |
| `MUSICBRAINZ_ALBUMARTISTID` | Per-album-artist MusicBrainz IDs, aligned with `ALBUMARTISTS` |
| `FESTIVAL` | Festival name (CrateDigger sources only) |
| `STAGE` | Stage name (CrateDigger sources only) |
| `VENUE` | Venue name (CrateDigger sources only) |

Tags are omitted entirely when the information is not available. Empty tags are never written.

## What does NOT change

TrackSplit only reads your source video files. It never modifies, moves, or deletes them. All output goes to the directory you specify (or the current working directory if you omit `--output`).

## Advanced details

### Artist tagging policy

- **`ARTIST`** is the display string for this specific track: for example `"AFROJACK ft. Eva Simons"`. When CrateDigger supplies a per-chapter `PERFORMER` tag, TrackSplit uses it verbatim so "Artist ft. Remixer" forms are preserved. When a chapter title has no artist separator, `ARTIST` falls back to `ALBUMARTIST`.
- **`ARTISTS`** is a multi-value list of the individual artists on this track: `"AFROJACK"`, `"Eva Simons"`. Jellyfin and Lyrion use this to link each contributor to their own artist page.
- **`MUSICBRAINZ_ARTISTID`** is positionally aligned with `ARTISTS`. Empty slots are preserved when an individual artist's MusicBrainz ID is unknown, so the position still matches. The whole tag is omitted if every slot is empty.
- **`ALBUMARTIST`** is the headliner display string for the whole set. For B2B sets with CrateDigger metadata this is something like `"Armin van Buuren & KI/KI"`.
- **`ALBUMARTISTS`** is a multi-value list of individual headliners: `"Armin van Buuren"`, `"KI/KI"`. Written for both solo and B2B sets.
- **`MUSICBRAINZ_ALBUMARTISTID`** is positionally aligned with `ALBUMARTISTS`. Omitted entirely if every slot is empty.
- Per-track artists whose name matches the album artist (case-insensitively) are normalized to the album artist's exact casing. This prevents Lyrion from listing two rows for the same artist and stops Jellyfin from showing stray uppercase variants.
- **`GENRE`** is per-track when CrateDigger supplies a chapter-level genre tag. It falls back to the album's genre list otherwise.

### Metadata tiers

- **Tier 1 (any chaptered video):** TrackSplit infers artist and album from filename and embedded tags. The album folder uses the filename stem. You get numbered, tagged tracks with whatever metadata the source carries.
- **Tier 2 (CrateDigger-tagged source):** TrackSplit uses the canonical artist, festival, venue, date, and MusicBrainz IDs embedded by CrateDigger. The album folder uses `Festival Year (Stage)` naming for festival sets, or `Venue Year` for venue recordings without a festival name. Every tag is populated precisely with no guessing.

### CrateDigger cache reuse

TrackSplit reads CrateDigger's caches directly, not just the tags baked into the MKV. This is how consistent artist spellings, festival aliases, MusicBrainz IDs, and DJ artwork stay in sync between your video library (CrateDigger) and your music library (TrackSplit) without TrackSplit needing any of its own config.

**Lookup chain.** For each input video, TrackSplit searches for `.cratedigger` directories in this order:

1. Global: `~/.cratedigger/` on Linux and macOS, or `%USERPROFILE%\.cratedigger\` on Windows.
2. Walk-up: starting from the folder containing the input video, walk up to 10 parent directories looking for a `.cratedigger` subfolder. All matches are collected (nearest last).

Directories closer to the input file override the global cache, so you can keep a per-project override next to a library without disturbing your global setup. Missing files or directories are silently skipped, so TrackSplit keeps working when no CrateDigger config exists.

**Cache files TrackSplit reads:**

| File | What TrackSplit uses it for |
|---|---|
| `festivals.json` | Canonical festival name and alias resolution. Rewrites raw festival names (e.g. `"TML"`, `"A State Of Trance Festival"`) to their canonical form (`"Tomorrowland"`, `"ASOT"`), and decomposes edition suffixes (`"Tomorrowland Winter"` to `"Tomorrowland"` + edition `"Winter"`). Drives the `FESTIVAL` tag and the album folder name. |
| `artists.json` | Canonical artist name resolution (e.g. `"tiesto"` to `"Tiësto"`). Applied before the artist folder name and the `ALBUMARTIST` tag are written. Case- and diacritic-insensitive, so both `"Tiesto"` and `"TIËSTO"` resolve correctly. |
| `dj_cache.json` | Supplements `artists.json` with per-DJ aliases scraped by CrateDigger. Loaded before `artists.json` so manual entries in `artists.json` win when the same alias appears in both. |
| `mbid_cache.json` | Fills missing MusicBrainz artist IDs. For Tier-1 sources (no CrateDigger tags) the `ALBUMARTIST` is looked up here to populate `MUSICBRAINZ_ALBUMARTISTID`. For Tier-2 sources, any empty slot in the positional MBID list (per-track `MUSICBRAINZ_ARTISTID` and album-level `MUSICBRAINZ_ALBUMARTISTID`) is backfilled from this cache. Unknown names stay empty. |
| `artists/{Artist}/dj-artwork.jpg` | DJ portrait used to compose the artist cover (`folder.jpg` / `artist.jpg`). Looked up by the canonical artist name. |
| `artists/{Artist}/fanart.jpg` | Fallback portrait used when `dj-artwork.jpg` is not present. |

The resolver merges all discovered `.cratedigger` directories into one config view before any tag is written. If you have CrateDigger installed and its caches populated, TrackSplit picks them up automatically. No TrackSplit-side configuration is required.

### Re-run manifest details

`.tracksplit_manifest.json` records:

- The source file path, size, and modification time.
- A hash of the chapter list and the metadata that affects output.
- The output format and codec mode used.
- The list of track filenames written.

On a subsequent run, TrackSplit loads the manifest and compares it against the current source file and settings. If nothing meaningful changed, the album is skipped. Deleting the manifest forces a full rebuild for that one album. Passing `--force` on the command line rebuilds everything regardless of manifests.
