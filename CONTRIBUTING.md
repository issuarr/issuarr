# Contributing to Issuarr

## Branches
- `dev` is where development happens. Every change lands there first, and each push builds the `ghcr.io/issuarr/issuarr:dev` image.
- `main` holds releases. A release is a pull request from `dev` into `main`, merged with a merge commit (not squash or rebase) so the two branches keep the same history. Each push to `main` builds `ghcr.io/issuarr/issuarr:latest`, and a `vX.Y.Z` tag on `main` also builds `X.Y.Z` and `X.Y` image tags.
- Hotfixes that cannot wait for a release go to `main` and are then merged back into `dev`.

## Changelog
[CHANGELOG.md](CHANGELOG.md) lists every change in plain English, newest first, each line ending with the commit id that made it. It is also a page on the website, which is published from `main`, so it updates when a release is merged.

Each pull request adds its own line under **Unreleased (on dev)**, ending with the id of the commit that made the change (commit the change first, then add the line in a second commit). Issuarr reads this file to show a "What's new" window once after an update, on `dev` as well as on releases, so a change without a line here never shows up there. Write for someone using Issuarr, not for a developer: say what they will notice, not how the code changed or what the PR was called.

When preparing a release, on `dev` run `python3 .github/changelog.py` to list the commits since the last release that the changelog doesn't mention yet. Rewrite each line so a user understands it, merge related lines, and add them under **Unreleased (on dev)**. In the release PR, rename that heading to the version and date (for example `## 1.0.0 (2026-11-01)`) and start a new empty **Unreleased (on dev)** section above it.

## Pull Requests
- Make pull requests against the `dev` branch.
- You're probably going to get some comments or questions from us.  They will be to ensure consistency and maintainability
- Each PR should come from its own feature branch not the `dev` or `main` branch in your fork, with a meaningful name (what is being added/fixed).
- Make meaningful commits, squash them if necessary.
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) to format your commit messages - applications like [commitizen](https://commitizen-tools.github.io/commitizen/) can help you get in that habit.
- Try to keep it to one feature/bug fix per pull request to keep things clean and easy to understand.
- To try a change in Docker before it's merged, build the image yourself with `docker build -t issuarr:test .` Only `main` (`latest`), `dev` (`dev`) and version tags publish images.
- Test your changes on a real Issuarr instance on real data.
- Rebase before submitting PRs.  If the `dev` branch has moved on since you started writing, don't expect reviewers to handle merging your code in case it conflicts.

## Publisher imprints
`data/imprints.json` maps publishers to their imprints and each imprint's publication run (`YYYY.MM - YYYY.MM`, end left blank if still running). Issuarr uses it to file imprint series under their parent publisher and to fill `$Imprint` in folder names. Installs fetch it from `main` once a day, so raise `version` whenever you change it.

## AI-written code
All pull requests are welcome, including ones written partly or fully by AI. Just be honest about it.

- **Say how much.** In the PR, say whether it was fully written by AI or AI-assisted, and name the AI model you used (for example "Claude Opus 4.8" or "GPT-5").
- **Keep code comments to a minimum.** Only add one where the code needs it, and keep it to a single line where you can.
- **Own it.** You are responsible for every line you submit. Read it, understand why it works, and be ready to answer questions about it.
- **Test it for real.** Run the change on a real Issuarr instance with real data, and say in the PR what you tested.

This section is for outside contributors. It doesn't apply to the project's own developers and members.
