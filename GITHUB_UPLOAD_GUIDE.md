# Upload MusicHarbor to GitHub

## What is prepared

Use the clean MusicHarbor folder inside github-upload, or extract MusicHarbor-source.zip. That folder contains the source, tests and sample fixture, dependency lists, launchers, documentation, Git ignore/line-ending rules, issue and pull-request templates, and a manual GitHub Actions workflow. UPLOAD_MANIFEST.txt lists every included file and its SHA-256 checksum (excluding the manifest itself).

The upload copy excludes virtual environments, generated app bundles, old releases, build output, generated spec files, caches, logs, the local usability screenshot, and macOS metadata. No user database, saved credentials, or music files are needed. Keep working from one chosen source copy after publishing to avoid editing the old folder by mistake.

No repository has been created, no commit or upload has been made, and no license has been selected. No app, test, linter, or build was run during this preparation. Only file inspection, editing, copying, archive creation, and archive checks were performed.

## Recommended: GitHub Desktop

1. Install GitHub Desktop from https://desktop.github.com/ and sign in to your own GitHub account.
2. Put the clean MusicHarbor source folder in a stable development location, preferably outside a cloud-synchronized folder. Do not use the folder containing old app builds. Extract the source ZIP first if using the archive.
3. In GitHub Desktop, choose File → Add local repository and select the clean MusicHarbor folder. If prompted that it is not a repository, choose the option to create a repository there. Verify the resulting local path is the existing MusicHarbor folder, not another nested MusicHarbor folder. Do not generate another README, ignore file, or license.
4. Review the Changes list. It should contain source, documentation, tests, and .github configuration. It must not include .venv, dist, build, .sqlite3 files, credentials, logs, personal exports, or music. If the creation dialog already made the initial commit, review that commit in History instead.
5. If changes are still uncommitted, enter the summary “Prepare MusicHarbor source” and click Commit to main. If your branch is named master, rename it to main using the Branch menu.
6. Click Publish repository. Name it MusicHarbor. Suggested description: “A local desktop workspace for matching playlists, planning music purchases, managing owned music, and exporting playlists.” Choose visibility deliberately; private is a conservative starting point. Leave “Keep this code private” checked for a private repository.
7. Click Publish repository. Open the repository on GitHub and confirm README.md, static, tests, and .github/workflows/checks.yml are present.

The source ZIP is a transport copy. Do not upload the ZIP as the only repository file; upload/commit its extracted contents.

## Alternative: Terminal and an empty GitHub repository

Create a new repository on GitHub named MusicHarbor. Choose visibility. Leave README, .gitignore, and license initialization unchecked because the source folder already contains the first two and the license is undecided.

Open Terminal in the clean source folder, then run these commands yourself:

```sh
git init -b main
git add .
git status --short
git diff --cached --stat
```

Review the staged file list before continuing. If Git asks for your identity, configure your chosen name and GitHub-associated email (or GitHub's private noreply address) locally using git config user.name and git config user.email. Do not put credentials into files or remote URLs.

```sh
git commit -m "Prepare MusicHarbor source"
git remote add origin https://github.com/YOUR-USERNAME/MusicHarbor.git
git push -u origin main
```

Replace YOUR-USERNAME with your account or organization. Authenticate using GitHub Desktop/Git Credential Manager, GitHub CLI, or SSH as appropriate; your account password is not a Git HTTPS credential. If the remote already contains commits, do not force-push over them—use an empty repository or reconcile the histories first.

## After upload

- The workflow is manual, so upload alone does not execute tests or builds. When ready, open Actions → Test and package → Run workflow on main. This performs tests and packaging on GitHub, including dependency downloads. Review failures before calling the release verified.
- After a successful run, workflow artifacts are available on its run page. They are not automatically published as Releases.
- Consider enabling private vulnerability reporting and available secret scanning/push protection in repository settings. Availability depends on the repository/account.
- Choose a license before offering reuse rights. None has been selected or added. Keep third-party dependency notices when distributing bundled software.

## Optional: publish a downloadable desktop app

Keep app binaries out of source commits. In GitHub, open Releases → Draft a new release, choose a tag such as v1.3.0 and the intended commit, add release notes, and attach the separately packaged MusicHarbor.zip. Save a draft while reviewing. Because current runtime checks have not been performed, describe that limitation and use a pre-release if publishing this build before validation.

The previously packaged macOS ZIP was built before this repository-preparation pass. Use it only with that disclosure, or build a fresh matching package after validation. It is locally ad-hoc signed, not demonstrated to be Developer ID signed or notarized; do not advertise a notarized installer. Windows and Linux packages have not been produced locally.

GitHub's automatic “Source code” archives are source snapshots, not ready-to-run apps. Upload the desktop ZIP as a separate release asset, not as a replacement for source files.

## References

- https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop
- https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
