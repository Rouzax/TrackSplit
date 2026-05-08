# Structured Debug Logging Migration

Migrate TrackSplit from a single rotating log file with freeform messages to
per-command log files with structured `prefix.event: key=value` events,
matching the pattern established in CrateDigger v0.17.

## Goals

1. Per-run log files so each invocation is self-contained and easy to share.
2. Structured events that are grepable and machine-parseable.
3. Reduce noise: remove repeated per-file messages that add no diagnostic value.
4. Add missing debug events for currently-invisible decisions.

## Non-goals

- Changing user-visible console output (INFO/WARNING stays readable prose).
- Adding log aggregation, structured JSON output, or remote shipping.

---

## 1. Infrastructure: `src/tracksplit/log.py`

New module extracted from `cli.py._setup_logging`. Responsibilities:

- `setup_logging(verbose, debug, console, command) -> Path | None`
- Per-command file naming: `{command}-{YYYY-MM-DDTHH-MM-SS}-{4-hex}.log` in
  `paths.log_dir()`.
- `MemoryHandler(capacity=50, flushLevel=WARNING, flushOnClose=True)` wrapping
  a `FileHandler(delay=True)`. Avoids creating empty files for `--version`
  or `--help`.
- `_cleanup_old_logs(log_dir, max_age_days=7)` called during setup.
- Close/clear existing handlers before adding new ones (test isolation).
- Returns the log file path on success, `None` on OS error (demoted to a
  console WARNING).

Console handler setup stays the same: `RichHandler` at the level dictated by
`--verbose`/`--debug`, `NullHighlighter`, no markup.

## 2. `paths.py` changes

- Remove `log_file() -> Path`.
- Add `log_dir() -> Path` returning `platformdirs.user_log_dir("TrackSplit")`.
- Single call site in `cli.py` (and now `log.py`) is the only consumer.

## 3. Subprocess logging: failures only

Current state logs every subprocess call twice (before + after). For a
26-track album that is 52 lines of full paths.

New policy in `subprocess_utils.py`:

- `subprocess.exit: code=N cmd="<cmd>" tail="<stderr tail>"` (non-zero only)
- `subprocess.timeout: cmd="<cmd>"`
- `subprocess.cancel: cmd="<cmd>"`

Successful invocations produce no log output.

## 4. Noise reduction

### `cratedigger.py`

- Log `cratedigger.config: data_dir=<path>` once at module/config load time.
- Remove per-call `CrateDigger candidate dirs` logging.
- Festival alias resolution: log each unique alias once per run
  (`cratedigger.festival_alias: raw="X" short="Y" edition="Z"`), not per file.

### `extract.py`

- Do not log codec decision for files that will be skipped.
- Log `extract.codec` only when extraction actually proceeds.

## 5. Structured event format

Convention: `prefix.event_name: key=value key=value`

Rules:
- Keys are `snake_case`, unquoted.
- String values with spaces get double quotes.
- Numeric values unquoted.
- Paths use filename only unless disambiguation is needed.
- Lists use pipe-separated format: `tags=artist|title|album`.
- Prefixes match module names.

## 6. Event catalog

### pipeline.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `pipeline.skip` | INFO | `file=, reason=unchanged` | File skipped, output current |
| `pipeline.regenerate` | DEBUG | `file=, reason=<reason> [field= old= new=]` | Decision to regenerate |
| `pipeline.process_start` | DEBUG | `file=, tracks=N, codec=` | About to process a file |
| `pipeline.process_done` | INFO | `file=, dir=` | Processing complete |
| `pipeline.orphan_prune` | INFO | `dir=, count=N` | Orphan tracks removed |
| `pipeline.cover_refresh` | INFO | `artist=` | Artist cover refreshed |
| `pipeline.intro_adjust` | DEBUG | `file=, first_start=N.Ns` | Track 1 start moved (gap too small for intro) |
| `pipeline.cover_rebuild` | DEBUG | `file=, reason=` | Cover-only rebuild triggered |

### extract.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `extract.codec` | INFO | `file=, input=, format=, output=, mode=` | Codec decision (only when extracting) |
| `extract.start` | DEBUG | `file=` | Audio extraction begins |
| `extract.done` | DEBUG | `file=` | Audio extraction complete |

### split.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `split.start` | DEBUG | `file=, tracks=N, codec_mode=` | Splitting begins |
| `split.track` | DEBUG | `num=N/M, title=, start=, end=, prefix=` | Per-track progress (replaces per-track subprocess lines) |
| `split.done` | DEBUG | `file=, tracks=N` | All tracks split |

### tagger.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `tagger.write` | DEBUG | `file=, added=N, removed=N, changed=N` | Tag delta per track |

### cover.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `cover.source` | INFO | `file=, method=` | Cover art extracted |
| `cover.source_fail` | DEBUG | `file=, method=, error=` | Extraction method failed |
| `cover.compose` | DEBUG | `file=, layout=, background=, dj_artwork=` | Composition choices |
| `cover.dj_lookup` | DEBUG | `artist=, found=, path=` | DJ artwork search |

### subprocess_utils.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `subprocess.exit` | DEBUG | `code=, cmd=, tail=` | Non-zero exit only |
| `subprocess.timeout` | WARNING | `cmd=` | Process timed out |
| `subprocess.cancel` | DEBUG | `cmd=` | Process cancelled |

### probe.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `probe.chapters` | DEBUG | `file=, count=N` | Chapters parsed |
| `probe.skip_zero` | WARNING | `file=, title=, start=` | Zero-duration chapter filtered |
| `probe.title_synthesized` | DEBUG | `file=, track=N` | Default "Track NN" assigned |
| `probe.opus_packet` | DEBUG | `file=, duration_ms=N` | Opus packet duration detected |
| `probe.opus_disagree` | DEBUG | `file=` | Packets disagree, triggers re-encode |

### metadata.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `metadata.source` | DEBUG | `file=, structured=, cratedigger=` | Tag path selection |
| `metadata.title_dedup` | DEBUG | `file=, count=N` | Duplicate titles deduplicated |
| `metadata.artist_canon` | DEBUG | `file=, track=N, original=, canonical=` | Artist casing normalized |

### manifest.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `manifest.schema_mismatch` | DEBUG | `file=, found=N, expected=N` | Old manifest rejected |

### update_check.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `update.suppressed` | DEBUG | `reason=` | Check skipped |
| `update.fetch` | DEBUG | `status=, version=` | Check result |
| `update.cache_error` | DEBUG | `error=` | Cache read failed |

### tools.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `tools.config` | DEBUG | `path=` | Config file location |
| `tools.resolve` | DEBUG | `tool=, path=` | Tool path resolved |
| `tools.missing` | WARNING | `tool=` | Required tool not found |

### cratedigger.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `cratedigger.config` | DEBUG | `data_dir=` | Config loaded (once) |
| `cratedigger.festival_alias` | DEBUG | `raw=, short=, edition=` | First occurrence per alias |
| `cratedigger.load` | DEBUG | `file=, path=` | Data file loaded |

### opus_patch.py

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `opus_patch.applied` | DEBUG | `file=, samples=N` | Pre-skip patched |

## 7. Cleanup

- Remove unused `logger = logging.getLogger(__name__)` from `split.py`,
  `tagger.py`, `manifest.py` (they will get real loggers with the new events).
- Remove `_setup_logging` from `cli.py`.
- Remove `log_file()` from `paths.py`.

## 8. CLI integration

- `cli.py` calls `log.setup_logging(...)`, stores returned path.
- `--check` output includes a "Log file" row showing the per-run path.
- Error messages can reference the specific log file for the failed run.

## 9. Tests

- `test_log.py`: handler setup, path return, old-log cleanup,
  MemoryHandler flush on WARNING, handler cleanup on repeated calls.
- Update tests that mock/patch `_setup_logging` or `paths.log_file`.
- No per-message format tests.

## 10. Docs

- `docs/troubleshooting.md`: reference per-command log directory, explain
  file naming, mention 7-day cleanup.
- `docs/faq.md`: update if it mentions the rotating log.
- `CHANGELOG.md`: note the change under appropriate section.
