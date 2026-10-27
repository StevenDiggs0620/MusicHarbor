# Contributing to MusicHarbor

MusicHarbor is a local desktop application. Run only one instance against a data directory. Keep credentials, playlist exports, music files, logs, and databases outside this repository.

## Development

Use Python 3.11 or newer. The release workflow uses Python 3.14 on macOS and 3.12 on Windows/Linux. Install requirements-dev.txt in a virtual environment; macOS release builds additionally require requirements-macos.lock. Browser tests use requirements-browser.txt and Playwright Chromium. See README.md for launch and packaging instructions.

Use MUSICHARBOR_DATA to select an isolated development data directory. Do not test migrations or destructive operations against your personal collection. The test fixture uses temporary databases; external service calls should be mocked.

When authorized to run checks:

```sh
python -m pytest -q
node --check static/ui.js
node --check static/workflows.js
node --check static/guided.js
node --check static/accessible.js
```

Browser setup and checks:

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install --with-deps chromium
python -m pytest tests/test_browser_workflows.py -q
```

The GitHub Actions workflow is manual: Actions → Test and package → Run workflow. It installs dependencies, runs tests and JavaScript syntax checks, packages three desktop variants, and performs packaged server checks. It has not been verified for the current revision. Artifacts are workflow downloads, not published GitHub Releases. GUI usability still requires a manual check.

## Changes and review

Describe the problem, behavior change, and actual validation performed. Preserve compatibility with old backup formats and data locations. Do not claim checks passed unless they ran on the revision submitted. Avoid screenshots containing personal music history or paths.

## Licensing

MusicHarbor is licensed under the GNU General Public License v3.0 or, at your option, any later version. Contributions should only be submitted when you have the right to license them under those terms. Third-party packages retain their respective licenses.
