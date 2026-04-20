# FAQ

## Do I need CrateDigger to use TrackSplit?

No. TrackSplit works on any video file that has chapter markers and an audio stream.

Without CrateDigger you still get a properly split, tagged album: one file per chapter, numbered tracks, cover art, and whatever metadata the source file carries. With CrateDigger-tagged sources you also get canonical artist names, festival and venue details, MusicBrainz IDs for every artist, and per-track genre. That richer metadata is what lets Jellyfin and Lyrion link artists, albums, and collaborators correctly across your library.

See [Getting Started](getting-started.md) for more on how the two tools work together.

## My video has no chapters. What happens?

If the video has a readable duration, TrackSplit produces a single-track album covering the whole file. If it cannot read the duration either, the file is skipped with a warning.

If you expected chapters but there are none, the source may have had them stripped by a downloader or remuxer. [CrateDigger](https://github.com/Rouzax/CrateDigger) can identify recordings and embed chapter markers automatically. You can also add chapters manually with MKVToolNix.

## Why is there no `00 - Intro` track even though the first chapter starts after 0:00?

If the gap between the start of the file and the first chapter is less than 5 seconds, TrackSplit folds that audio into track 1 instead of creating a standalone intro track. This avoids very short "Intro" files that are not musically meaningful. Gaps of 5 seconds or longer still produce a `00 - Intro` track.

## A file was skipped even though I expected it to be processed. Why?

Two common reasons:

1. **The output is already up to date.** TrackSplit keeps a record of the last run in each album folder. If nothing changed (same chapters, same metadata, same format), it skips the album. Pass `--force` to rebuild it anyway.
2. **No audio stream or zero duration.** TrackSplit warns and moves on.

Re-run with `--verbose` to see which reason triggered.

## Can I delete `.tracksplit_manifest.json`?

Yes. It is only used by TrackSplit to decide whether to skip an album on the next run. Delete it to force a full rebuild of that album. You do not need to back it up, and your music server ignores it entirely.

## Does TrackSplit modify my source videos?

No. TrackSplit only reads your source files. All output goes to the directory you specify with `--output`, or your current working directory if you omit it. Your source videos are never touched.

## Can I change the folder or filename template?

Not yet. For CrateDigger-tagged sources the album folder is named `Festival Year (Stage)` when a festival tag is present, or `Venue Year` for venue recordings without a festival name. Plain chaptered videos use the source filename. The album folder is always placed inside an `Artist/` folder. Track filenames follow `NN - Title`. The template is fixed in the current release.

## Does it need the internet?

No. TrackSplit is fully offline. It reads metadata from your source files and does all processing locally. No API keys, no external lookups.

## Parallel mode is slow on my disk. What do I do?

Try `--workers 1` first. On spinning disks and network shares, sequential processing is usually faster because parallel writes cause expensive disk seeks.

On fast SSDs, the default (roughly `logical_cores / 4`, between 2 and 12) is a good starting point. You can push it higher if your sources use Opus audio, because in that case TrackSplit copies the audio directly without re-encoding and CPU usage per worker is near zero. If your sources require re-encoding (FLAC output or Opus from a lossy source), raising workers beyond the default risks overloading your CPU.

See [Troubleshooting](troubleshooting.md#batch-processing-is-slow-or-hanging) for a full breakdown.

## How do Jellyfin and Lyrion show multi-artist tracks?

TrackSplit writes a multi-value `ARTISTS` tag listing every individual contributor alongside the display `ARTIST` string. It also writes a positionally-aligned `MUSICBRAINZ_ARTISTID` tag so each artist links to their own page. Both Jellyfin and Lyrion read these tags and surface every collaborator, not just the headliner.

If you upgraded TrackSplit and re-ran it against existing albums, trigger a library rescan in your music server so it picks up the updated tags.

## Does TrackSplit produce gapless output?

Yes, for both output formats, subject to player support.

**FLAC:** gapless in any player that handles FLAC correctly.

**Opus:** gapless in players that support gapless playback, such as Symfonium and mpv. TrackSplit inserts the necessary warmup frame and sets the correct `pre_skip` value so the decoder trims it cleanly at each boundary. The Jellyfin mobile app does not support gapless playback and introduces a 1-2s gap between tracks regardless of file content. That gap is a player-side limitation and cannot be fixed at the file level.

## How does TrackSplit differ from CrateDigger?

They do different jobs and work best together. **CrateDigger** builds a video library: it identifies recordings, embeds chapter markers and metadata, generates posters, and syncs with Kodi. **TrackSplit** reads that video library and produces a parallel music library of tagged FLAC or Opus albums for music servers like Jellyfin and Lyrion.

Because they share the same artist names, festival spellings, and MusicBrainz IDs, the same set shows up consistently whether you are browsing your video library or your music library.

## What is the yellow "!" message on startup?

That message means a newer release of TrackSplit is available on GitHub. The line shows the new version number and an upgrade command suited to your install method.

To upgrade, run the command printed in the notice. The three common variants are:

- pipx: `pipx upgrade tracksplit`
- uv: `uv tool upgrade tracksplit`
- pip: `pip install --upgrade git+https://github.com/Rouzax/TrackSplit.git`

To silence the notice, set `TRACKSPLIT_NO_UPDATE_CHECK=1` in your environment (the values `true` and `yes` are also accepted, case-insensitively). The notice is already suppressed automatically whenever stdout is not a terminal, such as in pipes, redirects, cron jobs, and CI environments.

The check involves no telemetry. It is a standard read-only request to the GitHub Releases API, results are cached locally for 24 hours, and the check never delays or blocks your run. If the network is unreachable, TrackSplit continues silently.
