#!/usr/bin/env bash
#
# The Python version is written down in three places, and Renovate only ever
# edits one of them.
#
# A base-image bump ("python:3.14-slim-bookworm" → 3.15) changes what production
# runs. It does not touch backend/.python-version, which is what CI and a local
# `uv sync` resolve against — so the tests would keep passing on 3.14 while the
# container serves 3.15, and the PR would be green. That is precisely the class
# of "green but not true" this repo's gate exists to remove, so the divergence is
# an error here rather than a discovery later.
#
# Node needs no equivalent: .github/workflows/ci.yml reads its version out of
# deploy/Dockerfile.web, so there is only one place to change.
#
# Run by `make lint` and by the `static` job in CI.
set -euo pipefail

cd "$(dirname "$0")/.."

pinned=$(tr -d '[:space:]' < backend/.python-version)
[ -n "$pinned" ] || { echo "backend/.python-version is empty" >&2; exit 1; }

failed=0
check() {  # check <pattern> <what>
  if grep -q "$1" deploy/Dockerfile.api; then
    printf '  ok   %s pins %s\n' "$2" "$pinned"
  else
    printf '  FAIL %s does not pin %s — found: %s\n' \
      "$2" "$pinned" "$(grep -m1 "$3" deploy/Dockerfile.api)" >&2
    failed=1
  fi
}

# Both stages have to say it: the build stage's uv image is what creates the
# venv, and its scripts and .so files are pinned to that interpreter's minor
# version. A venv built on one and copied into another does not run.
check "^FROM ghcr.io/astral-sh/uv:python${pinned}-" "Dockerfile.api build stage" "^FROM ghcr.io/astral-sh/uv:"
check "^FROM python:${pinned}-" "Dockerfile.api runtime stage" "^FROM python:"

if [ "$failed" = 1 ]; then
  cat >&2 <<EOF

backend/.python-version says ${pinned}, and deploy/Dockerfile.api does not agree.
CI and \`uv sync\` resolve against the first; the container runs the second — so
this would be tested on one interpreter and served on another.

Fix: set all three to the same version. If a Renovate PR moved the image, edit
backend/.python-version in that PR.
EOF
  exit 1
fi

echo "runtime pins agree on Python ${pinned}"
