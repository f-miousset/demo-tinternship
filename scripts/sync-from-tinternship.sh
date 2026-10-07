#!/usr/bin/env bash
#
# Refresh app/ — the real app's code — from a tag of the private repository.
#
#   scripts/sync-from-tinternship.sh <path-to-tinternship-checkout> [ref]   # ref defaults to v1
#
# Copies an explicit list of paths with `git archive`, so only committed files
# come across: never a local .env, a data/ directory or an editor's leftovers.
# The private repo's own docs, CI and agent files are deliberately NOT in the
# list — they describe the author's own infrastructure — and this repo carries
# its own (documentation/, .github/, CLAUDE.md).
#
# Then it rebuilds the seed against the new code and runs the privacy check,
# which is what decides whether the result may be committed. Nothing here
# pushes. The full procedure, including updating the mock for what changed, is
# documentation/syncing-from-v2.md.
set -euo pipefail
cd "$(dirname "$0")/.."

SOURCE=${1:?usage: $0 <path-to-tinternship-checkout> [ref]}
REF=${2:-v1}
PATHS=(backend frontend deploy scripts Makefile .env.example .dockerignore .gitignore)

git -C "$SOURCE" rev-parse --verify --quiet "$REF^{commit}" >/dev/null || { echo "no ref $REF in $SOURCE" >&2; exit 1; }

rm -rf app
mkdir app
git -C "$SOURCE" archive "$REF" "${PATHS[@]}" | tar -x -C app

commit=$(git -C "$SOURCE" rev-parse "$REF^{commit}")
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' app/frontend/package.json)
cat > snapshot.json <<JSON
{
  "source": "tinternship (private)",
  "ref": "$REF",
  "commit": "$commit",
  "version": "$version",
  "synced": "$(date -u +%Y-%m-%d)"
}
JSON

echo "--- rebuilding the seed against the new code"
make seed
echo "--- checking nothing private came across"
python3 ci/check-privacy.py
echo "synced app/ from $REF ($commit, version $version) — now: make verify, then follow documentation/syncing-from-v2.md"
