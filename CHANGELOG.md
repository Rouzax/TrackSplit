# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-04-12

First release with a proper project presence: a hero README, a published docs site, an animated landing page, CI, and a rounded-out CLI UX.

### Added

- Pre-flight tool check on every run: `ffmpeg` and `ffprobe` are verified up front with OS-specific install hints.
- `tracksplit --check` subcommand that probes `ffmpeg`, `ffprobe`, and `mkvextract` and prints their versions.
- Single-file runs now print a final summary line naming the album directory and the number of tracks written.
- `tracksplit.toml.example` shipped at repo root with a commented `[tools]` section.
- MkDocs Material documentation site: Home, Getting Started, Usage, Configuration, Output Structure, Troubleshooting, FAQ.
- Custom animated landing page with hero, four-card feature grid, two-row poster gallery, three-step workflow, and install block.
- GitHub Actions: pytest matrix on Python 3.11 / 3.12 / 3.13; MkDocs + landing page deploy to Pages.
- Issue templates (bug + feature) and Dependabot for pip and github-actions.
- `LICENSE` (GPL-3.0) and `[project.urls]` metadata in `pyproject.toml`.

### Changed

- Error reporting across the pipeline: known failures (missing tools, disk full, FFmpeg subprocess errors) now surface as one-line reasons; full tracebacks are kept behind `--debug`.
- `--workers` help text expanded to explain the default and when to tune it.
- README rewritten with a hero banner, badges, poster gallery, Configuration section, and a pointer to the sibling [CrateDigger](https://github.com/Rouzax/CrateDigger) project.

### Fixed

- Documentation corrected to reflect the actual output folder layout (`Artist/Festival Year (Stage)/` for CrateDigger-tagged sources, `Artist/<filename-stem>/` for untagged sources).
- `test_cli_format_flag_in_help` made robust to Rich's line-wrapping in narrow CI terminals.

## [0.1.0] - initial

- Initial chapter splitting, codec-aware output, metadata tagging, cover art generation, and re-run detection.
