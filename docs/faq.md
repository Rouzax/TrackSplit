# FAQ

## Do I need CrateDigger to use TrackSplit?

No. TrackSplit works on any video file that has chapter markers and an audio stream. It just reads more metadata when CrateDigger-style tags are present.

## My video has no chapters. What happens?

If `ffprobe` can read a duration, TrackSplit writes a single track covering the whole file. If it can not, the file is skipped with a warning. If you expected chapters but there are none, check the source: some downloaders strip chapters, and some containers need to be re-muxed. [CrateDigger](https://github.com/Rouzax/CrateDigger) can embed chapters for you.

## A file got skipped even though I expected it to be processed. Why?

Two common reasons:

1. **The manifest matched.** TrackSplit saw no meaningful change since the last run. Pass `--force` to rebuild.
2. **No audio stream, or zero-duration.** TrackSplit warns and moves on.

Re-run with `--verbose` to see which branch triggered.

## Can I delete `.tracksplit_chapters.json`?

Yes. It is a re-run manifest, nothing more. Delete it to force TrackSplit to rebuild that one album the next time you run. It does not need to be backed up and it contains no information that is not already in the source file.

## How do Lyrion and Jellyfin surface multi-artist tracks?

TrackSplit writes the Picard-standard `ARTISTS` multi-value tag alongside the display `ARTIST`, plus a positionally-aligned `MUSICBRAINZ_ARTISTID` multi-value tag. Both Lyrion and current Jellyfin read these and link each individual contributor to its own artist page. After upgrading TrackSplit and re-running it against previously-split albums, trigger a library rescan in your music server so it picks up the new multi-value fields.

## How does TrackSplit differ from CrateDigger?

They are complementary, not redundant. **CrateDigger** curates a video library: it identifies recordings, embeds chapters and metadata, generates posters, and syncs with Kodi. **TrackSplit** reads that video library and produces a parallel music library (FLAC/Opus albums, tagged and cover-embedded) for music servers like Jellyfin and Lyrion. The two share naming conventions and canonical IDs so the same set shows up consistently in both worlds.

## Does TrackSplit modify my source videos?

No. It only reads. All writes go to the output directory you specify (or the current working directory if you omit `--output`).

## Can I change the folder or filename template?

Not yet. Album folders follow `Artist @ Festival Year (Stage)` derived from the tags; track filenames follow `NN - Title`. The template is fixed in the current release.

## Does it need the internet?

No. TrackSplit is fully offline. No API keys, no external lookups. All metadata comes from the source file.

## Parallel mode is slow on my disk. What do I do?

- On spinning disks or network shares, try `--workers 1`.
- On fast SSDs, the default `min(4, CPU count)` is usually good; push to 8 if your CPU has cores to spare and your disk is not saturated.
- If the bottleneck is FFmpeg re-encoding, more workers help. If it is disk I/O, fewer workers help.
