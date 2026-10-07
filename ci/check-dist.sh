#!/usr/bin/env bash
#
# Assertions about dist/, the artifact no linter and no unit test looks at. A
# config regression here drops files silently and the demo still "works" in a
# dev server — the preview pane goes blank, the seed 404s, the app loses its
# styles (which happened once: documentation/gotchas.md).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fail() { echo "::error::$*"; exit 1; }

for f in dist/index.html dist/sw.js dist/manifest.webmanifest dist/theme-boot.js \
         dist/demo-data/seed.json dist/demo-data/canned.json dist-nginx/export-names.conf; do
  [ -f "$f" ] || fail "$f is missing from the build"
done

grep -q 'viewport-fit=cover' dist/index.html || fail "the viewport lost viewport-fit=cover"
grep -q '<script src="/theme-boot.js"></script>' dist/index.html || fail "index.html no longer loads the boot script"
# The production CSP has no 'unsafe-inline' for scripts: an inline one is dead code.
if grep -E '<script>|<script type="module">[^<]' dist/index.html; then
  fail "index.html carries an inline script, which the CSP blocks"
fi

# Every document a demo run can write has its preview and its download.
expected=$(python3 -c 'import json; print(len(json.load(open("demo/static/export-names.json"))))')
previews=$(find dist/api/applications/artifacts -name preview.html | wc -l | tr -d ' ')
exports=$(find dist/api/applications/artifacts -name export.docx | wc -l | tr -d ' ')
[ "$previews" = "$expected" ] || fail "$previews previews built, $expected expected"
[ "$exports" = "$expected" ] || fail "$exports downloads built, $expected expected"
[ "$(grep -c 'attachment; filename=' dist-nginx/export-names.conf)" = "$expected" ] || fail "export-names.conf does not name every download"

# The app's styles: Tailwind only generates what it finds under the Vite root,
# and a root that misses app/frontend/src builds a 17 kB stylesheet and an
# unstyled app with no error. These classes exist only in the app's components.
css=$(cat dist/assets/*.css)
for class in rounded-t-sheet backdrop-blur-sm min-h-11; do
  grep -q -- "$class" <<<"$css" || fail "the CSS has no .$class — Tailwind did not scan the app's components"
done

# No model is called from the browser, and no key ships in it.
if grep -rlE 'generativelanguage\.googleapis|aiplatform\.googleapis|AIza[0-9A-Za-z_-]{30,}' dist; then
  fail "the build references a model API or carries something shaped like a Google API key"
fi

echo "dist/ carries the shell, the seed, $expected previews and downloads, the app's styles, and no model endpoint"
