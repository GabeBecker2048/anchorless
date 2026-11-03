#!/usr/bin/env bash
# Cut a release of the version in pyproject.toml: check everything, then push an
# annotated tag vX.Y.Z. GitHub Actions (.github/workflows/release.yml) does the rest:
# PyPI, the container image on ghcr.io and the GitHub release, with the CHANGELOG
# entry as its notes. No tokens are needed here.
#
# Before running: in a pull request, bump `version` in pyproject.toml, run `uv lock`,
# and add a "## X.Y.Z — YYYY-MM-DD" section (one sentence) to the top of
# CHANGELOG.md. Merge it, then run this from an up-to-date main.
set -euo pipefail
cd "$(dirname "$0")/.."

die() { echo "error: $*" >&2; exit 1; }

version=$(grep -E '^version *= *' pyproject.toml | head -1 | sed -E 's/version *= *"(.*)".*/\1/')
tag="v${version}"

[[ "$(git branch --show-current)" == main ]] || die "not on main"
[[ -z "$(git status --porcelain)" ]] || die "uncommitted changes"
git fetch --quiet --tags origin
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || die "main isn't the same as origin/main (push or pull first)"
git rev-parse -q --verify "refs/tags/${tag}" >/dev/null && die "${tag} already exists"
grep -qE "^## ${version//./\\.}( |$)" CHANGELOG.md || die "no '## ${version}' section in CHANGELOG.md"
uv lock --check >/dev/null || die "uv.lock is out of date (run uv lock)"

echo "checking anchorless ${version}..."
uv run ruff check .
uv run pytest -q

read -r -p "tag and release anchorless ${version}? [y/N] " ok
[[ "$ok" == [yY] ]] || die "cancelled"

git tag -a "$tag" -m "anchorless ${version}"
git push origin "$tag"
echo "pushed ${tag}: the release builds at https://github.com/GabeBecker2048/anchorless/actions"
