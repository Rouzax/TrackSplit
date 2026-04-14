# TrackSplit

Chapter-based audio extractor for music servers. TrackSplit turns chaptered video files into gapless, tagged FLAC or Opus albums ready for Jellyfin and Lyrion.

## What it does

Point TrackSplit at a video with chapter markers and it will split the audio at chapter boundaries, write one file per track, embed rich metadata and cover art, and lay everything out in an `Artist/Album/` structure your music server will scan without complaint. Lossless sources stay lossless. Lossy sources are stream-copied when possible, re-encoded only when needed.

## How it fits your workflow

1. **[Install and check](getting-started.md)** the required tools (FFmpeg, optionally MKVToolNix) and confirm with `tracksplit --check`.
2. **[Run on a file or folder](usage.md)** and let TrackSplit handle probing, splitting, tagging, and cover art.
3. **[Point your music server](output.md)** at the output directory. Jellyfin, Lyrion, Plex, anything that reads Vorbis comments will pick it up.

A second run on the same input is near-instant unless the chapters actually changed, thanks to the per-album manifest.

## Pairs with CrateDigger

TrackSplit reads any chaptered video but shines when paired with **[CrateDigger](https://github.com/Rouzax/CrateDigger)**, which embeds 1001Tracklists metadata, chapter markers, and DJ artwork into your MKV library in the first place. Together they keep canonical artist names, festival spellings, and MusicBrainz IDs consistent across your video and music libraries.

## Learn more

- **[Getting Started](getting-started.md)**: prerequisites, install, first run.
- **[Usage](usage.md)**: every CLI flag, with examples.
- **[Configuration](configuration.md)**: TOML config for custom tool paths.
- **[Output Structure](output.md)**: what gets written where, and what every tag means. Per-track multi-artist linking (`ARTISTS`, aligned `MUSICBRAINZ_ARTISTID`) is new in v0.6.
- **[Troubleshooting](troubleshooting.md)**: what to do when something goes wrong.
- **[FAQ](faq.md)**: short answers to common questions.
