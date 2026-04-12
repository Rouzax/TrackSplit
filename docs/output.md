# Output Structure

TrackSplit writes one directory per album, grouped by artist.

## Directory layout

```
<output>/
  Artist/
    folder.jpg
    artist.jpg
    Festival Year (Stage)/
      00 - Intro.flac      (or .opus)
      01 - Track Title.flac
      02 - Track Title.flac
      ...
      cover.jpg
      .tracksplit_chapters.json
```

The album folder name depends on the metadata tier (see below). With full CrateDigger tags (Tier 2) it is `Festival Year (Stage)` or `Festival Year` when no stage is set. Without them (Tier 1) it falls back to the source filename stem.

- `folder.jpg` and `artist.jpg` live at the artist level so Jellyfin, Kodi, and other servers can pick them up as artist artwork.
- `cover.jpg` at the album level is the 1:1 cover image, also embedded into every track.
- Track filenames use zero-padded numbers (`00` for an intro if the first chapter does not start at zero, `01..NN` for the rest).

## What each file is

| File | Purpose |
|------|---------|
| `NN - Title.flac` / `.opus` | One audio file per chapter. Gapless boundaries. |
| `cover.jpg` | Album cover, 1:1. Also embedded as a picture frame in each track. |
| `folder.jpg` | Jellyfin-style artist folder image (duplicate of the artist cover). |
| `artist.jpg` | Artist cover composed from DJ artwork and artist name. |
| `.tracksplit_chapters.json` | Manifest used for re-run detection. Safe to delete. |

## Tags written

Vorbis comments written on every track:

`TITLE`, `ARTIST`, `ALBUMARTIST`, `ALBUM`, `TRACKNUMBER`, `TRACKTOTAL`, `DISCNUMBER`, `DATE`, `GENRE`, `PUBLISHER`, `COMMENT`, `MUSICBRAINZ_ARTISTID`, `FESTIVAL`, `STAGE`, `VENUE`.

Most servers only read the common fields (TITLE/ARTIST/ALBUM/TRACKNUMBER/DATE). The custom `FESTIVAL`, `STAGE`, `VENUE` fields preserve festival context for scripts, filters, or smart playlists that care.

## Metadata tiers

- **Tier 1 (basic):** any chaptered video. TrackSplit infers artist and album from the filename and embedded tags, numbers tracks, and writes whatever metadata it can find.
- **Tier 2 (enriched):** when the source carries the `CRATEDIGGER_*` custom tag set (written by [CrateDigger](https://github.com/Rouzax/CrateDigger)), TrackSplit uses the canonical artist, festival, venue, date, and MusicBrainz IDs directly. No guessing.

## Re-run manifest

`.tracksplit_chapters.json` is a small JSON file that records:

- The source path and its size / mtime.
- A hash of the chapter list and the metadata that affects output.
- The output format and codec mode used.
- The list of track filenames written.

On subsequent runs TrackSplit loads this manifest and skips the album entirely unless something meaningful changed. It is safe to commit, ignore, or delete: deleting it forces that one album to rebuild the next time you run TrackSplit.
