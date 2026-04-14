# TrackSplit

Turn your chaptered video library into a tagged music library, ready for Jellyfin, Lyrion, or any music server that reads standard audio files.

## What it does

Point TrackSplit at a video file with chapter markers and it splits the audio into one file per chapter, tags every track, generates album and artist cover art, and lays everything out in an `Artist/Album/` folder structure your music server can scan immediately. Lossless sources stay lossless. Repeat runs skip albums that have not changed.

## Better together with CrateDigger

TrackSplit works on any chaptered video, but it works best when those videos were prepared by **[CrateDigger](https://github.com/Rouzax/CrateDigger)**.

CrateDigger identifies festival sets and concert recordings, embeds chapter markers at every track boundary, and writes rich metadata into your MKV files: canonical artist names, festival and venue details, MusicBrainz IDs, and DJ artwork. TrackSplit reads all of that and produces a music library where every artist, album, and collaborator is named and linked correctly.

Without CrateDigger you still get a properly split, tagged album from any chaptered video. With CrateDigger the result is a fully enriched music library that stays in sync with your video library. That is the 1+1=3.

## How it fits your workflow

1. **[Install and verify](getting-started.md):** install FFmpeg (required) and optionally MKVToolNix, then confirm everything works with `tracksplit --check`.
2. **[Run on a file or folder](usage.md):** one command handles probing, splitting, tagging, and cover art.
3. **[Point your music server at the output](output.md):** Jellyfin, Lyrion, Plex, or anything that reads standard audio tags will pick it up.

## Learn more

- **[Getting Started](getting-started.md):** prerequisites, install, and your first run.
- **[Usage](usage.md):** every option explained as a user decision, with examples.
- **[Configuration](configuration.md):** only needed if TrackSplit cannot find your tools automatically.
- **[Output Structure](output.md):** every file and tag TrackSplit creates, and what each is for.
- **[Troubleshooting](troubleshooting.md):** organized by symptom, with fixes and confirmation steps.
- **[FAQ](faq.md):** plain answers to common questions.
