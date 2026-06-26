# Contributing to TrackSplit

Thanks for your interest. TrackSplit is a small, focused CLI and we aim to keep it that way. Bug reports, small focused PRs, and documentation improvements are all welcome.

## Reporting issues

- **Bugs**: use the [Bug Report](https://github.com/Rouzax/TrackSplit/issues/new?template=bug_report.yml) template. Include the output of `tracksplit --check` and, where relevant, the per-run debug log file (its path is shown in the summary panel after each run and in `tracksplit --check`).
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

`pip install -e ".[dev]"` also installs ruff, mypy, basedpyright, vulture, pytest-cov, check-manifest, and pre-commit. Run the checks locally before pushing:

```bash
ruff check .          # lint
ruff format .         # format (use --check to verify without changing files)
mypy                  # type-check src/
basedpyright          # second type-check gate (pyright) on src/
vulture               # dead-code scan on src/ (high-confidence findings)
check-manifest        # verify sdist completeness
```

`pytest` measures coverage automatically (via `addopts` in `pyproject.toml`) and fails below the floor set by `--cov-fail-under`. The floor is a ratchet: it only ever goes up. When you add tests that raise overall coverage, bump the floor in `[tool.pytest.ini_options]` to lock the gain in.

Enable the git hooks once so they run automatically on every commit and push:

```bash
pre-commit install
```

To run the integration tests you need a real video fixture:

```bash
TRACKSPLIT_TEST_VIDEO=/path/to/some.mkv pytest tests/test_integration.py -v
```

## Quality bar and ratchet

The tool gates above are the standard and should not be removed. Quality levels
are ratcheted up gradually rather than in one big sweep, and never regress:

- **Coverage** , the `--cov-fail-under` floor only ever goes up (current 85, target 90). When you add tests that raise overall coverage, bump the floor in `[tool.pytest.ini_options]` to lock the gain in. Don't lower it.
- **Type checking** , mypy and basedpyright both stay. Strictness grows per-file: when you create or substantially edit a module under `src/`, add `# pyright: strict` at its top and resolve the findings. Strict is not enabled globally.
- **Dead code** , `vulture` gates high-confidence findings; dead functions are caught by per-file pyright strict and by the touched-files cleanup rule below, plus occasional manual sweeps.
- **New files** should land at the current bar: tests that hold the floor, and `# pyright: strict`.

This dovetails with the touched-files rule: tightening a file you're already
changing is expected; a repo-wide tightening pass is its own separate change.

## Pull requests

- Keep changes focused. One logical change per PR is easier to review and revert.
- Add or update tests for any behavior change. The unit suite must pass on 3.11, 3.12, and 3.13 (and hold coverage at or above the `--cov-fail-under` floor), and CI also runs a `lint` job that enforces `ruff check .`, `ruff format --check .`, `mypy`, `basedpyright`, `vulture`, and `check-manifest`.
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

- Code is formatted with `ruff format`, linted with `ruff check`, and type-checked with `mypy` and `basedpyright`. All are enforced by pre-commit hooks and the CI `lint` job. Run them locally before opening a PR (see Development setup above). mypy is the drift-resistant baseline; basedpyright (pyright) is a second gate that reads library source and catches precision issues mypy cannot. New strictness grows per-file via `# pyright: strict` on files you touch.
- Trust framework guarantees. Do not add defensive checks for things that cannot happen.
- Comments explain *why*, not *what*. Well-named identifiers describe *what* already.

## License

By contributing, you agree that your contributions will be licensed under the [GPL-3.0 License](LICENSE) that covers the project.
