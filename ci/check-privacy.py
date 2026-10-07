#!/usr/bin/env python3
"""Fail if anything private or identifying has reached this repository.

    python3 ci/check-privacy.py           # the check (CI and `make public`)
    python3 ci/check-privacy.py --hash w  # the hash to add a word to DENY

This repository is public. It holds a copy of an app that was built for one
real person's job search and runs on their own server, and nothing about either
may be recoverable from here. A sweep done once by hand rots on the next
commit — or on the next resync from the private repository — so this runs on
every commit and checks four things:

1. **No denylisted word, anywhere** — file contents, file paths, and the XML
   inside every .docx (a Word file is a zip, so a plain text scan would read
   nothing). Every file is split into words (accents folded, lower-cased) and
   each word is hashed. The denylist holds HASHES, not words: a check that
   spelled out what it protects would itself be the leak.
2. **No private infrastructure** — names of the serving host's internals and
   credential shapes. Plain text, so this file is exempt from this list only.
   Public products the app legitimately documents (a forward-auth proxy, a
   reverse proxy, a local model server) are *not* on it: the self-hosting
   guide has to be able to name them.
3. **One public hostname** — any host on the owner's domain other than the
   demo's own address fails.
4. **No personal e-mail in history** — every commit author and committer must
   be a GitHub noreply address; commit metadata is published with the repo.

It also asserts it actually read the tree: a discovering check that finds no
files passes vacuously, which is the worst way for a gate to be wrong.
Copied from the owner's other public demos and adapted — see
documentation/verification.md.
"""

import hashlib
import io
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = "ci/check-privacy.py"

# sha256(word)[:16]: the original candidate's identity and school, the owner's
# other private projects, and the storage the original deployment lives on.
DENY = {
    "b9987dcb78ee4d40", "a4003ff8e6f35e5f", "212837ef2804a9bb", "033129a9c84cc23b",
    "0bfb47062f870b21", "bf16dec0876b2b61", "d68d69650bc1ab5e",
}

INFRA = [
    "cloudflared", "orbstack", "/volumes/", "/users/", "~/docker", "~/dev/", "homelab",
    "gha-runner", "mac mini", "begin private key",
    "@gmail.com", "@icloud.com", "@me.com", "smtp.mail",
]

ALLOWED_HOST = "demo-tinternship.fmiousset.com"
NOREPLY = re.compile(r"^([\w.+\[\]-]+@users\.noreply\.github\.com|noreply@github\.com|noreply@anthropic\.com)$")
EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
ALLOWED_EMAIL = re.compile(r"@([a-z0-9-]+\.)*example\.(org|com)$|@users\.noreply\.github\.com$|^noreply@anthropic\.com$")
MIN_FILES = 300  # the tree has well over this; fewer means discovery broke
BINARY = (".png", ".ico", ".jpg", ".jpeg", ".webp", ".woff2")
# Lockfiles carry maintainers' addresses for every package; they are not ours.
NO_EMAIL_CHECK = ("package-lock.json", "uv.lock")


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def token_hash(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()[:16]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def read_text(name: str) -> str:
    path = ROOT / name
    if name.endswith(BINARY):
        return ""
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
            return "\n".join(
                archive.read(entry).decode("utf-8", errors="ignore")
                for entry in archive.namelist()
                if entry.endswith(".xml")
            )
    return path.read_bytes().decode("utf-8", errors="ignore")


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--hash":
        print(token_hash(fold(sys.argv[2])))
        return 0

    try:
        if git("rev-parse", "--is-inside-work-tree").strip() != "true":
            raise RuntimeError
    except Exception:
        print("::error::not a git working tree — nothing to check, which must not read as clean")
        return 1

    files = [f for f in git("ls-files", "--cached", "--others", "--exclude-standard").splitlines() if (ROOT / f).is_file()]
    if len(files) < MIN_FILES:
        print(f"::error::found only {len(files)} files (expected ≥ {MIN_FILES}) — discovery is broken")
        return 1

    problems = []
    for name in files:
        haystack = f"{fold(name)}\n{fold(read_text(name))}"
        for word in set(re.findall(r"[a-z0-9]+", haystack)):
            if token_hash(word) in DENY:
                problems.append(f"{name}: contains a denylisted word (hash {token_hash(word)})")
        if name == SELF:
            continue
        for needle in INFRA:
            if needle in haystack:
                problems.append(f"{name}: mentions private infrastructure ({needle!r})")
        for host in set(re.findall(r"[a-z0-9.-]*fmiousset\.com", haystack)):
            if host != ALLOWED_HOST:
                problems.append(f"{name}: names the host {host!r}; only {ALLOWED_HOST} may appear")
        if not name.endswith(NO_EMAIL_CHECK):
            for email in set(EMAIL.findall(haystack)):
                if not ALLOWED_EMAIL.search(email):
                    problems.append(f"{name}: an e-mail outside the reserved example domains ({email})")

    identities = set(git("log", "--all", "--format=%ae%n%ce").split()) if git("rev-list", "--all").strip() else set()
    for email in sorted(identities):
        if not NOREPLY.match(email):
            problems.append(f"git history: commit identity {email!r} is not a noreply address")

    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        print(f"{len(problems)} problem(s) — this repository is public")
        return 1

    print(f"privacy: {len(files)} files and {len(identities)} commit identities checked, nothing private found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
