# Configuration

**You probably do not need a config file.** If you installed FFmpeg and MKVToolNix through a standard package manager and they are on your `PATH`, TrackSplit finds them automatically and works out of the box.

You only need a config file if:
- your tools are installed somewhere non-standard (a custom path, a portable build, a Windows install not on `PATH`), or
- `tracksplit --check` shows a red `✗` or yellow `!` for a tool you know is installed.

## How to create a config file

Copy the example file to the config location for your platform:

| Platform | Config file location |
|---|---|
| Linux | `~/TrackSplit/config.toml` |
| macOS | `~/TrackSplit/config.toml` |
| Windows | `Documents\TrackSplit\config.toml` |

**Linux / macOS:**

```bash
mkdir -p ~/TrackSplit
cp tracksplit.toml.example ~/TrackSplit/config.toml
```

**Windows (PowerShell):**

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Documents\TrackSplit"
Copy-Item tracksplit.toml.example "$env:USERPROFILE\Documents\TrackSplit\config.toml"
```

Then open the file and uncomment the keys for the tools you need to configure. You only need to set the keys where your paths differ from the default.

## What goes in the config file

The config file has one section: `[tools]`. Each key is a tool name, and its value is the full path to that tool's executable.

**Linux / macOS:**

```toml
[tools]
ffmpeg     = "/usr/local/bin/ffmpeg"
ffprobe    = "/usr/local/bin/ffprobe"
mkvextract = "/usr/bin/mkvextract"
mkvmerge   = "/usr/bin/mkvmerge"
```

**Windows:**

```toml
[tools]
ffmpeg     = "C:/ffmpeg/bin/ffmpeg.exe"
ffprobe    = "C:/ffmpeg/bin/ffprobe.exe"
mkvextract = "C:/Program Files/MKVToolNix/mkvextract.exe"
mkvmerge   = "C:/Program Files/MKVToolNix/mkvmerge.exe"
```

You do not need to set all four keys. Any key you leave out falls back to looking for that tool by name on your `PATH`. For example, if only `ffmpeg` is in a non-standard location, set just the `ffmpeg` key and leave the rest out.

## Where to put the config file

TrackSplit reads its config from one fixed location per platform:

| Platform | Config file location |
|---|---|
| Linux | `~/TrackSplit/config.toml` |
| macOS | `~/TrackSplit/config.toml` |
| Windows | `Documents\TrackSplit\config.toml` |

This location is always checked, regardless of which directory you run TrackSplit from. You do not need to keep a config file in your current directory.

## Verify your config

After saving your config file, run:

```bash
tracksplit --check
```

TrackSplit prints each tool's resolved version. A green `✓` means the path is correct. A red `✗` or yellow `!` means something is wrong with the path you set, and the output will include the path it tried.

## Common problems

**Config file is not being picked up:**

Check that the file is at the correct location for your platform (shown in the table above). Run `tracksplit --check` to see the resolved path TrackSplit found, or to confirm it is using the settings you expect.

**Path set but tool still not found:**

On Windows, use forward slashes (`C:/ffmpeg/bin/ffmpeg.exe`) or escaped backslashes (`C:\\ffmpeg\\bin\\ffmpeg.exe`) in the TOML file. Unescaped backslashes are invalid in TOML strings.

**Only some tools are configured:**

That is fine. TrackSplit merges the config with its defaults. Any tool not listed in the config file is looked up on your `PATH` as normal.

## Cache and log directories

Caches (update-check) and logs live in standard platform directories separate from your config file:

| Purpose | Linux | macOS | Windows |
|---|---|---|---|
| Cache | `~/.cache/TrackSplit/` | `~/Library/Caches/TrackSplit/` | `$env:LOCALAPPDATA\TrackSplit\Cache\` |
| Logs | `~/.local/state/TrackSplit/log/` | `~/Library/Logs/TrackSplit/` | `$env:LOCALAPPDATA\TrackSplit\Logs\` |

These paths are managed by [platformdirs](https://pypi.org/project/platformdirs/) and are not affected by your config file location. On Linux, if you need to relocate them, set the standard `XDG_CACHE_HOME` or `XDG_STATE_HOME` environment variables. Note that these apply system-wide to all XDG-aware applications, and platformdirs appends `TrackSplit/` automatically, so `XDG_CACHE_HOME=/data/cache` results in `/data/cache/TrackSplit/`.
