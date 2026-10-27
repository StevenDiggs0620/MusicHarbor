# Keeping MusicHarbor current on GitHub

The published repository is `StevenDiggs0620/MusicHarbor`; its primary branch is `main`. Work from the repository folder (the one containing `.git`), review the changed files, and keep credentials, databases, music, personal exports, and generated app builds out of commits.

## Publish an ordinary source update

1. Start from the latest `main` and confirm the working tree is clean.
2. Make the change in `src/musicharbor/`, `scripts/`, `tools/`, `tests/`, `docs/`, or the relevant project configuration.
3. Run the checks appropriate to the change. For release-level validation, use the manual **Actions → Test and package → Run workflow** workflow and review every job.
4. Review the final diff and file list, stage only intended files, and commit the changes.
5. Push `main` and confirm GitHub shows the expected commit. A source push does not alter an existing release tag or downloadable app.

## Publish a new version

Choose a new semantic version: patch for compatible fixes (for example `1.3.1`), minor for compatible features (`1.4.0`), and major for incompatible changes (`2.0.0`). Never move or reuse an existing tag.

1. Update the version in `pyproject.toml`, `README.md`, `docs/REBRANDING.md`, and `tools/build.py`; update applicable release notes as well.
2. Run the full manual GitHub Actions workflow on the release commit. It runs Python and browser checks, builds packages on macOS, Windows, and Linux, and performs packaged startup checks.
3. Review the artifacts. Workflow artifacts are temporary downloads and are not automatically attached to a GitHub Release. Attach only the app builds that were produced for and checked against the release commit.
4. Commit and push the release changes. Tag that exact commit with a new version such as `v1.3.1`, push the tag, and create the GitHub Release with clear notes and desired platform assets.
5. Verify the release page, tag target, asset list, and release visibility. State any checks or platforms that were not validated.

The macOS build is ad-hoc signed by default and is not notarized. Windows and Linux packages also need to be tested on the intended systems before making platform-specific compatibility claims.

## Development install and checks

Python package metadata and dependency groups live in `pyproject.toml`:

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
```

For browser checks, install `python -m pip install -e ".[browser]"` and Playwright Chromium, then run `python -m pytest tests/test_browser_workflows.py -q`. The desktop bundle is built with `python tools/build.py` on its target operating system. macOS release builds use the captured lock at `requirements/macos-release.lock`.

See the [README](../README.md) for running the app and [Contributing](../CONTRIBUTING.md) for development practices. The project is licensed under the GNU GPL v3 or any later version; third-party dependencies retain their own licenses.
