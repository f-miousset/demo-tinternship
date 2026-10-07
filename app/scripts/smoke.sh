#!/usr/bin/env bash
#
# Prove a built image actually serves, before anything is deployed from it.
#
#   scripts/smoke.sh api <image>
#   scripts/smoke.sh web <image>
#
# `make lint` and `make test` check the source; this checks the *artifact*. They
# are not the same claim, and the gap between them is where a whole class of
# dependency bump lives: a Renovate PR on `node:24-alpine`, `nginx:1.31-alpine`,
# `python:3.14-slim-bookworm` or the uv base image changes nothing pytest or tsc
# can see, and `docker compose up -d --build` is what publishes it. Two things
# in particular cannot be covered anywhere else:
#
#   * Chromium. The test suite is forbidden from launching a browser
#     (`BROWSER_VERIFY=false` in conftest.py), so nothing else notices when a
#     Playwright bump ships a browser build the image's libraries cannot run —
#     and link verification silently reports every protected board "unchecked".
#   * nginx. The cache and security headers in deploy/nginx.conf are one `map`
#     and four `location` blocks that no unit test can reach. A manifest served
#     as the wrong type is an app that cannot be installed, with no error
#     anywhere.
#
# CI runs this on both images (.github/workflows/ci.yml), and `make smoke` runs
# the identical thing locally, so both get the same answer.
set -euo pipefail

KIND=${1:-}
IMAGE=${2:-}
CONTAINER="smoke-${KIND}-$$"

if [[ -z $KIND || -z $IMAGE ]]; then
  echo "usage: scripts/smoke.sh <api|web> <image>" >&2
  exit 2
fi

FAILED=0
BODY=$(mktemp)
HEADERS=$(mktemp)

pass() { printf '  ok   %s\n' "$1"; }
fail() { FAILED=1; printf '  FAIL %s\n' "$1" >&2; exit 1; }

cleanup() {
  # The logs are the only evidence of a container that died on boot, and they
  # are gone the moment it is removed.
  if [[ $FAILED == 1 ]]; then
    echo "--- $CONTAINER logs ---" >&2
    docker logs "$CONTAINER" 2>&1 | tail -40 >&2 || true
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -f "$BODY" "$HEADERS"
}
trap 'FAILED=1' ERR
trap cleanup EXIT

# Wait for the image's own HEALTHCHECK rather than for a URL of our choosing:
# that instruction is what Traefik reads to decide whether to route to the
# container at all, so a healthcheck that never passes is an outage even when
# the app is fine.
wait_for_health() {
  local status
  for _ in $(seq 1 60); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)
    case $status in
      healthy) pass "the image's own HEALTHCHECK reports healthy"; return 0 ;;
      unhealthy) fail "HEALTHCHECK went unhealthy" ;;
    esac
    if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null) != true ]]; then
      fail "the container exited before it became healthy"
    fi
    sleep 2
  done
  fail "still not healthy after 120s (last status: ${status:-unknown})"
}

# `curl -w` writes the fields we assert on; the body goes to a file so a failure
# can show what actually came back.
probe() {  # probe <url> -> sets CODE, TYPE, CACHE, BODY
  local out
  out=$(curl -sS -o "$BODY" -D "$HEADERS" -w '%{http_code}' "$1" || true)
  CODE=$out
  TYPE=$(tr -d '\r' < "$HEADERS" | awk 'tolower($1) == "content-type:" { print $2 }')
  CACHE=$(tr -d '\r' < "$HEADERS" | awk 'tolower($1) == "cache-control:" { $1 = ""; sub(/^ /, ""); print }')
}

expect_code() {  # expect_code <what> <expected>
  [[ $CODE == "$2" ]] || fail "$1: HTTP $CODE, expected $2 — $(head -c 200 "$BODY")"
  pass "$1 answers $2"
}

case $KIND in
api)
  echo "smoke: $IMAGE (api)"
  # No volume and no key: the app must boot on nothing but its own defaults,
  # which is also what a fresh deploy on a new machine gets.
  docker run -d --name "$CONTAINER" -p 127.0.0.1:0:8000 "$IMAGE" >/dev/null
  wait_for_health
  PORT=$(docker port "$CONTAINER" 8000/tcp | sed -n '1s/.*://p')
  BASE="http://127.0.0.1:$PORT"

  probe "$BASE/api/health"
  expect_code "/api/health" 200
  grep -q '"status"' "$BODY" || fail "/api/health did not answer with a status"

  # The endpoint that touches the most of the app at once: the model registry,
  # the Ollama probe, the platform list, the onboarding state and the base-document
  # check. An import that a dependency bump broke shows up here as a 500 rather
  # than as a page that half-loads in production.
  probe "$BASE/api/config"
  expect_code "/api/config" 200
  for key in models progress job_sources results base_resumes base_cover_letters; do
    grep -q "\"$key\"" "$BODY" || fail "/api/config has no \"$key\" — the shape the SPA reads changed"
  done
  pass "/api/config still carries the fields the SPA reads"

  # The whole deliverable — the résumé and, since 2026-09-09, the cover letter —
  # is one round trip through python-docx inside *this image*: read a Word
  # document into numbered blocks, find its blanks, fill one, save, and read it
  # back unchanged in shape — and measure the page, which is the rule that
  # decides whether a run is allowed to ship. A lock bump that breaks any of it
  # breaks every application package, and no unit test looks at the built image.
  docker exec "$CONTAINER" python -c "
import io
from docx import Document
from tinternship_backend.services import docx_template, page_fit

document = Document()
run = document.add_paragraph().add_run('Acme Corp')
run.bold = True
document.add_paragraph('Objectif : [Poste vise]')
buffer = io.BytesIO()
document.save(buffer)
source = buffer.getvalue()

blocks = docx_template.read_blocks(source)
assert [block.text for block in blocks] == ['Acme Corp', 'Objectif : [Poste vise]'], blocks
slots = docx_template.find_slots(blocks)
assert [(s.key, s.token) for s in slots] == [('s0', '[Poste vise]')], slots

tailored, report = docx_template.apply_fills(
    source, blocks, slots, {'s0': 'Stage Machine Learning'}
)
after = docx_template.read_blocks(tailored)
assert len(after) == len(blocks), 'filling a blank changed the number of paragraphs'
assert after[1].text == 'Objectif : Stage Machine Learning', after[1].text
assert after[0].text == 'Acme Corp', 'a line with no blank in it was rewritten'
assert after[0].bold, 'the untouched bold run lost its formatting'

estimate = page_fit.measure(tailored)
assert estimate.fits and 0 < estimate.fraction < 1, estimate.fraction
assert page_fit.page_problems(source, blocks, slots, {'s0': 'x' * 40000}), \
    'a fill that cannot fit on the page was not refused'

# A letter's date and employer are resolved in this image too, and a blank
# answered with nothing has to come out as nothing: falling back to the token
# would print [address_company] on a letter that is about to be sent.
from datetime import date
from tinternship_backend.services import letter_fields

document = Document()
document.add_paragraph('[current_month_letters] [current_date], 2026')
document.add_paragraph('[address_company]')
buffer = io.BytesIO()
document.save(buffer)
letter = buffer.getvalue()

blocks = docx_template.read_blocks(letter)
slots = docx_template.find_slots(blocks)
facts = letter_fields.LetterFacts(language='en', today=date(2026, 9, 9))
fills = {**letter_fields.known_fills(slots, facts), 's2': ''}
filled, _ = docx_template.apply_fills(letter, blocks, slots, fills)
after = docx_template.read_blocks(filled)
assert after[0].text == 'September 9, 2026', after[0].text
assert after[1].text == '', after[1].text
" >/dev/null || fail "python-docx cannot fill a document in this image — every export would fail"
  pass "the .docx blank-filling, date resolution and page measurement round-trip inside the image"

  # Chromium: installed, launchable, and able to render a page. Nothing in the
  # pytest suite may start a browser, so this is the only place a broken one is
  # ever noticed before a real run needs it.
  docker exec "$CONTAINER" python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--disable-dev-shm-usage'])
    page = browser.new_page()
    page.set_content('<title>smoke</title><h1>ok</h1>')
    assert page.title() == 'smoke', page.title()
    browser.close()
" >/dev/null || fail "Chromium did not launch — link verification would report every protected board unchecked"
  pass "Chromium launches and renders, so link verification still works"
  ;;

web)
  echo "smoke: $IMAGE (web)"
  docker run -d --name "$CONTAINER" -p 127.0.0.1:0:80 "$IMAGE" >/dev/null
  wait_for_health
  PORT=$(docker port "$CONTAINER" 80/tcp | sed -n '1s/.*://p')
  BASE="http://127.0.0.1:$PORT"

  probe "$BASE/"
  expect_code "/" 200
  grep -q 'id="root"' "$BODY" || fail "/ is not the SPA shell"
  [[ $CACHE == *"no-store"* ]] || fail "/ is cacheable ($CACHE) — visitors would be pinned to an old build"
  pass "the shell is served uncacheable"

  # add_header does not accumulate across levels: one in a location block drops
  # every header the server declared. That is how the CSP once went missing from
  # the only response that needs it.
  for header in "content-security-policy" "x-content-type-options" "referrer-policy"; do
    grep -qi "^$header:" "$HEADERS" || fail "/ is missing the $header header"
  done
  pass "the shell carries its security headers"

  # React Router owns /tracker; nginx must answer it with the shell rather than
  # with a 404, or every deep link and every refresh breaks.
  probe "$BASE/tracker"
  expect_code "/tracker (a client route)" 200
  grep -q 'id="root"' "$BODY" || fail "/tracker did not fall through to index.html"
  pass "client routes fall through to the shell"

  # The worker must be served as itself. try_files rewriting it to index.html
  # would register the HTML shell as a service worker.
  probe "$BASE/sw.js"
  expect_code "/sw.js" 200
  if grep -q 'id="root"' "$BODY"; then fail "/sw.js was rewritten to the SPA shell"; fi
  [[ $CACHE == "no-cache" ]] || fail "/sw.js says '$CACHE', expected exactly 'no-cache'"
  pass "the service worker is itself, and revalidated rather than unstorable"

  # The same rewrite hazard as the worker, with a different symptom: the boot
  # script runs before the first paint and decides the theme of it, so a shell
  # served in its place is a syntax error and a frame of the wrong theme on
  # every cold load. It is a separate file precisely because the CSP above
  # forbids the inline version, so nothing in the source tree would notice.
  probe "$BASE/theme-boot.js"
  expect_code "/theme-boot.js" 200
  if grep -q 'id="root"' "$BODY"; then fail "/theme-boot.js was rewritten to the SPA shell"; fi
  grep -q 'data-theme\|dataset.theme' "$BODY" || fail "/theme-boot.js does not stamp data-theme"
  pass "the theme boot script is itself, and stamps the theme"

  # A manifest arriving as application/octet-stream is one the browser may
  # decline to read — an app that cannot be installed, with no error anywhere.
  probe "$BASE/manifest.webmanifest"
  expect_code "/manifest.webmanifest" 200
  [[ $TYPE == application/manifest+json* ]] || fail "the manifest is served as '$TYPE'"
  pass "the manifest is served as application/manifest+json"

  # The manifest and the icons sit at URLs that never change, so the only thing
  # standing between a rebrand and an installed app still showing the old mark
  # is that these revalidate. They were max-age=86400 until 2026-08-27, and
  # nothing here noticed — which is why the assertion exists now.
  [[ $CACHE == *"no-cache"* ]] || fail "/manifest.webmanifest says '$CACHE' — it must revalidate, or a rebrand takes a day to land"
  pass "the manifest revalidates rather than being held"

  # /favicon.ico is in this list on its own account: it has a `location` block
  # of its own, and it is what every bookmark list and link preview asks for
  # without ever reading the <link> tags in index.html.
  for ICON in /favicon.ico /favicon.svg /icon-192.png /icon-512.png /icon-maskable-512.png /apple-touch-icon.png; do
    probe "$BASE$ICON"
    expect_code "$ICON" 200
    [[ $CACHE == *"no-cache"* ]] || fail "$ICON says '$CACHE' — it must revalidate, or a rebrand takes a day to land"
  done
  pass "every icon the manifest and the shell name is served, and revalidates"

  # The manifest may only name icons that exist: a 404 here is an install that
  # silently falls back to a screenshot of the page, or to no icon at all.
  #
  # Collected into an array through a process substitution rather than read from
  # a pipe, because `fail` exits — and a `while read` on the right of a pipe is
  # a subshell, so its exit would kill the loop and let the script go on to
  # report success.
  curl -sS "$BASE/manifest.webmanifest" -o "$BODY"
  NAMED=()
  while read -r SRC; do
    [[ -n $SRC ]] && NAMED+=("$SRC")
  done < <(grep -o '"src": *"[^"]*"' "$BODY" | sed 's/.*"\(\/[^"]*\)"/\1/')
  (( ${#NAMED[@]} > 0 )) || fail "the manifest names no icons at all"
  for SRC in "${NAMED[@]}"; do
    probe "$BASE$SRC"
    expect_code "manifest icon $SRC" 200
  done
  pass "every icon the manifest names resolves (${#NAMED[@]} of them)"

  # The hashed bundle the shell actually names — proof the build's assets were
  # copied into the image, and that they are the immutable half of the cache map.
  # Re-probe the shell because the icon assertions above overwrote $BODY.
  # Process substitution rather than `grep | head -1`, which triggers SIGPIPE 141
  # under `set -o pipefail` when multiple asset links appear in the shell.
  probe "$BASE/"
  read -r ASSET < <(grep -o '/assets/[A-Za-z0-9._-]*\.js' "$BODY" || true) || true
  [[ -n $ASSET ]] || fail "index.html names no /assets/*.js bundle"
  probe "$BASE$ASSET"
  expect_code "$ASSET" 200
  [[ $CACHE == *immutable* ]] || fail "$ASSET says '$CACHE' — fingerprinted assets should be immutable"
  pass "the fingerprinted bundle is served and cached forever"
  ;;

*)
  echo "unknown target '$KIND' — expected api or web" >&2
  exit 2
  ;;
esac

echo "smoke: $IMAGE passed"
