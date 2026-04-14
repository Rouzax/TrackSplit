# Configuration

**You probably do not need a config file.** If you installed FFmpeg and MKVToolNix through a standard package manager and they are on your `PATH`, TrackSplit finds them automatically and works out of the box.

You only need a config file if:
- your tools are installed somewhere non-standard (a custom path, a portable build, a Windows install not on `PATH`), or
- `tracksplit --check` shows a red `✗` or yellow `!` for a tool you know is installed.

## How to create a config file

Copy the example file from the TrackSplit directory:

```bash
cp tracksplit.toml.example tracksplit.toml
```

Then open `tracksplit.toml` and uncomment the keys for the tools you need to configure. You only need to set the keys where your paths differ from the default.

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

TrackSplit checks these locations in order and uses the first file it finds:

1. `tracksplit.toml` in your current directory
2. `config.toml` in your current directory
3. Your user config directory:

   | Platform | Path |
   |---|---|
   | Linux / macOS | `~/.config/tracksplit/config.toml` |
   | Windows | `C:\Users\YourName\AppData\Roaming\tracksplit\config.toml` |

   On Windows, run `$env:APPDATA` in PowerShell to see your AppData path.

4. Your home directory:

   | Platform | Path |
   |---|---|
   | Linux / macOS | `~/tracksplit.toml` or `~/.tracksplit.toml` |
   | Windows | `$env:USERPROFILE\tracksplit.toml` or `$env:USERPROFILE\.tracksplit.toml` |

**Which location to use:** If you run TrackSplit from the same directory every time, placing `tracksplit.toml` there is simplest. If you run it from different directories, use the user config directory (option 3) so the config is always found regardless of where you run the command from.

## Verify your config

After saving your config file, run:

```bash
tracksplit --check
```

TrackSplit prints each tool's resolved version. A green `✓` means the path is correct. A red `✗` or yellow `!` means something is wrong with the path you set, and the output will include the path it tried.

## Common problems

**Config file is not being picked up:**

TrackSplit uses the first file it finds in the search order above. If you placed the file in option 3 (user config directory) but also have a `tracksplit.toml` in your current directory, the current-directory file wins. Check all locations.

**Path set but tool still not found:**

On Windows, use forward slashes (`C:/ffmpeg/bin/ffmpeg.exe`) or escaped backslashes (`C:\\ffmpeg\\bin\\ffmpeg.exe`) in the TOML file. Unescaped backslashes are invalid in TOML strings.

**Only some tools are configured:**

That is fine. TrackSplit merges the config with its defaults. Any tool not listed in the config file is looked up on your `PATH` as normal.
