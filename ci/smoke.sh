#!/usr/bin/env bash
#
# Build the image a deployment runs, start it, and prove it serves — the one
# check that ever looks at the base images (node, nginx) Renovate bumps.
# Called by CI's image job, by `make smoke`, and by the host's nightly redeploy;
# one script, so they cannot drift apart.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

IMAGE=${IMAGE:-demo-tinternship:smoke}
NAME=${NAME:-demo-tinternship-smoke}
# Not 8080: a busy host has something there, and a collision reads as "the
# SPA did not serve".
PORT=${PORT:-18975}
BASE="http://127.0.0.1:$PORT"

fail() { echo "ERROR: $*" >&2; exit 1; }

# This script BUILDS $IMAGE, so it owns it: the container and the image both go
# on exit, or every run leaves an image behind on a persistent host.
# Never point IMAGE at a deployed tag — this deletes it.
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker image rm -f "$IMAGE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
echo "--- building $IMAGE"
docker build -t "$IMAGE" . || fail "docker build failed"

echo "--- starting $NAME on :$PORT"
docker run -d --name "$NAME" -p "$PORT:80" "$IMAGE" >/dev/null || fail "docker run failed"

echo "--- waiting for the container's own HEALTHCHECK"
healthy=0
for i in $(seq 1 60); do
  status=$(docker inspect --format='{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo starting)
  echo "attempt $i: $status"
  [ "$status" = "healthy" ] && { healthy=1; break; }
  [ "$status" = "unhealthy" ] && break
  sleep 2
done
if [ "$healthy" -ne 1 ]; then
  docker logs "$NAME" 2>&1 | tail -n 30
  fail "the container never became healthy"
fi

echo "--- probing the SPA"
curl -sf "$BASE/" | grep -q '<div id="root">' || fail "/ did not serve the SPA shell"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/applications/1")
[ "$code" = "200" ] || fail "deep-link fallback returned $code"

headers=$(curl -sI "$BASE/")
echo "$headers" | grep -qi "^content-security-policy: .*script-src 'self'" || fail "the CSP header is missing from the shell"
echo "$headers" | grep -qi "connect-src 'self'" || fail "the CSP no longer pins connect-src to this origin"
echo "$headers" | grep -qi "frame-ancestors 'none'" || fail "the shell may be framed by other sites"
curl -s "$BASE/theme-boot.js" | grep -q 'data-theme' || fail "/theme-boot.js did not serve the boot script"
curl -sI "$BASE/manifest.webmanifest" | grep -qi "content-type: application/manifest+json" \
  || fail "the manifest is not served as application/manifest+json"
# Read whole, then searched: `curl | grep -q` on a large body fails under
# pipefail, because grep exits at its first match and curl dies of SIGPIPE.
seed=$(curl -sf "$BASE/demo-data/seed.json") || fail "the seed is not served"
grep -q '"epoch"' <<<"$seed" || fail "the seed is not the seed"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/assets/missing.js")
[ "$code" = "404" ] || fail "a missing asset returned $code instead of 404"

echo "--- probing the prebuilt documents"
preview=$(curl -sI "$BASE/api/applications/artifacts/1000/preview")
echo "$preview" | grep -qi "content-type: text/html" || fail "a preview is not served as HTML"
echo "$preview" | grep -qi "frame-ancestors 'self'" || fail "a preview cannot be framed by the app"
download=$(curl -sI "$BASE/api/applications/artifacts/1000/export")
echo "$download" | grep -qi "content-type: application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  || fail "a download is not served as .docx"
echo "$download" | grep -qi '^content-disposition: attachment; filename="Resume_Alex_Martin' || fail "a download has no filename"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/config")
[ "$code" = "404" ] || fail "/api/config returned $code — the server must not answer API calls"
echo "shell, CSP, boot script, manifest, seed, previews and downloads all served as themselves"

# "Every visitor's data stays in their browser" is only true while the server
# cannot accept any. Send it some.
echo "--- proving the container has no write path"
for verb in POST PUT PATCH DELETE; do
  for path in / /api/applications /api/jobs/search; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -X "$verb" -d x=1 "$BASE$path")
    case "$code" in 404|405) ;; *) fail "$verb $path returned $code, expected 404 or 405" ;; esac
  done
done
# As the worker user: root can write anywhere, so a root-run check proves nothing.
docker exec "$NAME" su -s /bin/sh nginx -c 'test -w /usr/share/nginx/html' \
  && fail "the nginx user can write the docroot"
[ -z "$(docker inspect -f '{{.Mounts}}' "$NAME" | tr -d '[]')" ] \
  || fail "the container has a mount; it should hold no state"
echo "writes rejected, docroot read-only to the worker, no mounts"

echo "--- smoke passed"
