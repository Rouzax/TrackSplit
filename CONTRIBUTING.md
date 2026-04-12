# Contributing to TrackSplit

Thanks for your interest. TrackSplit is a small, focused CLI and we aim to keep it that way. Bug reports, small focused PRs, and documentation improvements are all welcome.

## Reporting issues

- **Bugs**: use the [Bug Report](https://github.com/Rouzax/TrackSplit/issues/new?template=bug_report.yml) template. Include the output of `tracksplit --check` and, where relevant, a `--debug` log.
- **Feature requests**: use the [Feature Request](https://github.com/Rouzax/TrackSplit/issues/new?template=feature_request.yml) template. Describe the use case, not just the mechanism.

## Development setup

Requires Python 3.11+, `ffmpeg`, and `ffprobe`. Optionally `mkvextract` for the MKV cover-extraction path.

```bash
git clone https://github.com/Rouzax/TrackSplit.git
cd TrackSplit
pip install -e ".[dev]"
tracksplit --check
pytest --ignore=tests/test_integration.py
```

To run the integration tests you need a real video fixture:

```bash
TRACKSPLIT_TEST_VIDEO=/path/to/some.mkv pytest tests/test_integration.py -v
```

## Pull requests

- Keep changes focused. One logical change per PR is easier to review and revert.
- Add or update tests for any behavior change. The unit suite should pass on 3.11, 3.12, and 3.13 (CI verifies this).
- Keep the scope of commits clean: `feat(...)`, `fix(...)`, `docs(...)`, `refactor(...)`, `test(...)`, `ci(...)`, `chore(...)` prefixes are appreciated but not required.
- No em dashes in user-facing text or commit messages.
- Do not add `Co-Authored-By` lines to commit messages.

## Running the docs locally

```bash
pip install mkdocs-material
mkdocs serve
```

Then visit http://127.0.0.1:8000/.

## Style

- Follow the existing code style; no formatter is enforced but stick to PEP 8.
- Trust framework guarantees. Do not add defensive checks for things that cannot happen.
- Comments explain *why*, not *what*. Well-named identifiers describe *what* already.

## License

By contributing, you agree that your contributions will be licensed under the [GPL-3.0 License](LICENSE) that covers the project.
