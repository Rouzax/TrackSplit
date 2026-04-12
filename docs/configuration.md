# Configuration

TrackSplit needs to find `ffmpeg` and `ffprobe`, and optionally `mkvextract`. If they are on your `PATH` you do not need a config file at all. If they are installed elsewhere (Windows, custom builds, portable installs), point TrackSplit at them via a TOML file.

## Search order

The first file that exists wins:

1. `./tracksplit.toml` (current directory)
2. `./config.toml` (current directory, alternate name)
3. `~/.config/tracksplit/config.toml` (Linux/macOS) or `%APPDATA%/tracksplit/config.toml` (Windows)
4. `~/tracksplit.toml`
5. `~/.tracksplit.toml`

## Example

Copy [`tracksplit.toml.example`](https://github.com/Rouzax/TrackSplit/blob/main/tracksplit.toml.example) to one of the locations above and uncomment the keys you need.

```toml
[tools]
ffmpeg     = "/usr/local/bin/ffmpeg"
ffprobe    = "/usr/local/bin/ffprobe"
mkvextract = "/usr/bin/mkvextract"
mkvmerge   = "/usr/bin/mkvmerge"
```

Windows example:

```toml
[tools]
ffmpeg     = "C:/ffmpeg/bin/ffmpeg.exe"
ffprobe    = "C:/ffmpeg/bin/ffprobe.exe"
mkvextract = "C:/Program Files/MKVToolNix/mkvextract.exe"
mkvmerge   = "C:/Program Files/MKVToolNix/mkvmerge.exe"
```

Only the keys you set are overridden. Anything left unset falls back to the bare command name and is resolved via `PATH`.

## Verify

After editing your config, re-run:

```bash
tracksplit --check
```

TrackSplit prints each resolved tool's version (or an install hint if the configured path is wrong).
