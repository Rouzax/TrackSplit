# Security Policy

## Supported versions

Only the latest minor release receives security updates. See the [Releases](https://github.com/Rouzax/TrackSplit/releases) page for the current version.

## Reporting a vulnerability

If you believe you have found a security issue in TrackSplit, please **do not** open a public issue.

Use GitHub's private vulnerability reporting instead: go to the [Security tab](https://github.com/Rouzax/TrackSplit/security/advisories/new) and open a draft advisory. We will confirm receipt within a few days, investigate, and coordinate a fix and disclosure timeline with you.

## Scope

TrackSplit is a local CLI tool. It does not accept network input and does not run as a service. Relevant threat surfaces are:

- Subprocess invocations of `ffmpeg`, `ffprobe`, and `mkvextract`. TrackSplit constructs argument lists directly; it does not shell out with string concatenation.
- Filesystem writes under a user-supplied `--output` directory.
- Parsing of `tracksplit.toml` config files (TOML only, no code execution).

If you spot a path-traversal, unsanitized argument, or any other concern in one of those areas, please report it privately as above.
