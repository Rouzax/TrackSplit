# B2B Sets: Primary Artist Folder with Guest Annotation

## Context

Multi-artist (B2B) DJ sets currently get their own combined artist folder (e.g., `Martin Garrix & Alesso/`). This creates three problems:

1. **Fragmented browsing**: a DJ's sets are split across their solo folder and one or more combined folders.
2. **One-off folder clutter**: combined folders typically contain a single album, cluttering the top-level artist list.
3. **Missing folder.jpg**: `find_dj_artwork` looks up cached artwork by artist name. CrateDigger caches artwork per individual artist, so `"Martin Garrix & Alesso"` has no match and the artist folder gets no cover.

The fix: place multi-artist sets under the **first** listed artist's folder, and annotate the album folder name with `(with X & Y)` to indicate the guest artist(s).

## Design

### Folder structure

Before:

```
Martin Garrix & Alesso/
  Red Rocks Amphitheatre 2025/
    01 - Carry You vs I Wanna Know.flac
    ...
```

After:

```
Martin Garrix/
  folder.jpg
  Red Rocks Amphitheatre 2025 (with Alesso)/
    01 - Carry You vs I Wanna Know.flac
    ...
  Red Rocks 2025/                          <-- solo set, unaffected
    ...
```

### Rules

1. **Multi-artist detection**: `albumartists` list (from `CRATEDIGGER_1001TL_ARTISTS`) has 2+ entries.

2. **Primary artist**: `albumartists[0]`, the first artist from 1001TL/CrateDigger. This determines the artist folder.

3. **Guest annotation**: the album folder name gets a `with X` suffix listing all artists except the primary, joined with ` & `. The suffix is placed inside existing parentheses (comma-separated) or wrapped in new parentheses:
   - No existing parens: `Red Rocks Amphitheatre 2025` becomes `Red Rocks Amphitheatre 2025 (with Alesso)`
   - Existing parens (stage): `UMF Miami 2026 (Mainstage)` becomes `UMF Miami 2026 (Mainstage, with Alesso)`

4. **FLAC tags stay combined**: `AlbumMeta.artist` remains the full display name (`"Martin Garrix & Alesso"`). `AlbumMeta.album` stays clean (no annotation). The ALBUMARTIST and ALBUM tags in output FLACs continue to reflect the actual performance. Players already show the combined ALBUMARTIST alongside the album name, so repeating guest info in the ALBUM tag would be redundant. The `with X` annotation only appears in the folder name via the `album_folder` property.

5. **Solo/unenriched sets unchanged**: when `albumartists` has 0 or 1 entries, behavior is identical to today.

6. **Artist artwork**: `find_dj_artwork` receives `albumartists[0]` so it finds the primary artist's cached artwork for `folder.jpg`.

### Example mappings

| Current path | New path |
|---|---|
| `Martin Garrix & Alesso/Red Rocks Amphitheatre 2025/` | `Martin Garrix/Red Rocks Amphitheatre 2025 (with Alesso)/` |
| `Martin Garrix & Alesso/UMF Miami 2026 (Mainstage)/` | `Martin Garrix/UMF Miami 2026 (Mainstage, with Alesso)/` |
| `Armin van Buuren & Marlon Hoffstadt/UMF Miami 2026/` | `Armin van Buuren/UMF Miami 2026 (with Marlon Hoffstadt)/` |
| `AFROJACK & R3HAB/Tomorrowland Winter 2026 (Mainstage)/` | `AFROJACK/Tomorrowland Winter 2026 (Mainstage, with R3HAB)/` |
| `Armin van Buuren & KI/KI/AMF 2025 (Two Is One)/` | `Armin van Buuren/AMF 2025 (Two Is One, with KI/KI)/` |
| `Fred again.. & Thomas Bangalter/Alexandra Palace London 2026 (USB002)/` | `Fred again../Alexandra Palace London 2026 (USB002, with Thomas Bangalter)/` |
| `Agents Of Time & MORTEN/Tomorrowland Winter 2026 (Sunweb Stage)/` | `Agents Of Time/Tomorrowland Winter 2026 (Sunweb Stage, with MORTEN)/` |
| `AFROJACK & Shimza/Coachella 2026 (Quasar)/` | `AFROJACK/Coachella 2026 (Quasar, with Shimza)/` |
| `Armin van Buuren & Adam Beyer/Coachella 2026 (Quasar)/` | `Armin van Buuren/Coachella 2026 (Quasar, with Adam Beyer)/` |

### What does NOT change

- FLAC ALBUM tag content (stays clean, no annotation)
- FLAC ALBUMARTIST tag content (stays combined display name)
- FLAC ALBUMARTIST_MBIDS (stays all artists' MBIDs)
- Solo/unenriched set behavior
- Cover art extraction (album-level cover.jpg)
- Chapter/track metadata
- Group acts like "Everything Always" (single entry in `albumartists`, not multi-artist)

## Files to modify

### `src/tracksplit/models.py`
- `AlbumMeta.artist_folder` property (line 50): return `albumartists[0]` when `len(albumartists) > 1`, else current behavior.
- `AlbumMeta.album_folder` property (line 54): when `len(albumartists) > 1`, append the `with X & Y` annotation to `self.album`. If album already ends with `(...)`, insert `, with X & Y` before the closing paren. Otherwise append ` (with X & Y)`. When single artist, return `self.album` as today.

### `src/tracksplit/metadata.py`
- No album name changes needed. The `album` field stays clean. The annotation is handled entirely by the `album_folder` property in models.py.

### `src/tracksplit/pipeline.py`
- `find_dj_artwork` calls (lines 598, 660): pass `albumartists[0]` when available instead of `album.artist` for the artist lookup.

### `tests/test_metadata.py`
- Update existing B2B tests that assert on album folder names.

### `tests/test_models.py`
- Test `artist_folder` returns first artist when multi-artist, original artist when single.
- Test `album_folder` appends `(with X)` when multi-artist, no parens in album.
- Test `album_folder` inserts `, with X` before closing paren when album has stage parens.
- Test `album_folder` with 3+ artists: `(with B & C)`.
- Test `album_folder` unchanged for single artist.

## Migration

Existing B2B albums processed before this change will have a different `resolved_artist_folder` in their manifest. On next run, the manifest check (pipeline.py:404) detects the mismatch and regenerates into the new location. The old combined artist folder (now empty) is not auto-deleted. Users can remove it manually or a future cleanup step could handle it.

## Verification

1. Run existing test suite: `pytest tests/`
2. Process the Red Rocks B2B sample (`2025 - Martin Garrix & Alesso - Red Rocks`) and verify:
   - Output lands in `Martin Garrix/Red Rocks Amphitheatre 2025 (with Alesso)/`
   - `folder.jpg` is generated in `Martin Garrix/`
   - FLAC ALBUMARTIST tag reads `Martin Garrix & Alesso`
3. Process a solo Martin Garrix set at the same venue and verify no collision.
4. Process a set with stage parens (e.g., UMF Miami Mainstage B2B) and verify album name reads `UMF Miami 2026 (Mainstage, with Alesso)`.
