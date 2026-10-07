"""Turning a fetched job page into something a model can read.

A pasted link is only useful if the posting behind it can be read, and what
comes back from a job board is 200–600 KB of HTML that is mostly navigation,
cookie banners, tracking scripts and a React bundle. Handing that to a model
wastes most of the prompt on markup and buries the six facts that matter.

Two extractions, in order of how much they can be trusted:

1. **The schema.org `JobPosting`.** Every major ATS and every board that wants
   its postings in Google's job results embeds one — `title`,
   `hiringOrganization`, `datePosted`, `validThrough`, `employmentType`,
   `jobLocation`, and the full `description`. It is the employer's own
   structured answer, so where it exists there is nothing to infer.
   `services/recency.py` already mines the same block for `datePosted`; this
   reads the rest of it.
2. **The visible text**, for the pages that carry no JSON-LD at all — plenty of
   company career sites, and every board that renders server-side without
   caring about Google. Tags stripped, block boundaries kept as newlines so a
   requirements list does not arrive as one run-on sentence.

Both go into the prompt, structured facts first, because the two disagree
often enough to matter: the visible text is what a human reads, and the JSON-LD
is sometimes a stale copy the site forgot to update. The Reader is told which
is which and told to prefer the page's own words for prose.

Deliberately regex-based rather than a parser dependency. The output is read by
a model, not a DOM: a stray tag survives, and a broken page still yields its
text instead of raising.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# How much extracted text one posting is worth in a prompt. A long posting runs
# to about 8 000 characters; past this it is the page's "related jobs" rail and
# its footer, which cost tokens and add nothing.
TEXT_LIMIT = 24_000
# The JSON-LD `description` is the whole posting again, in HTML. Worth having —
# it is the one field the visible text sometimes truncates behind a "read more"
# — but not worth twice the budget.
DESCRIPTION_LIMIT = 8_000

# Whole elements whose contents are never page text.
_INVISIBLE = re.compile(
    r"<(script|style|noscript|svg|template|iframe)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_LD_JSON = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
# Tags that end a line for a reader. Without this a `<ul>` of requirements comes
# out as one sentence and the model has to guess where each item ended.
_BLOCK = re.compile(
    r"</?(p|br|div|li|ul|ol|tr|h[1-6]|section|article|header|footer|nav|table)\b[^>]*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")
_TRAILING = re.compile(r"[ \t]+\n")

# The fields of a schema.org JobPosting worth putting in front of a model.
# Anything else it carries — `@context`, `identifier`, `hiringOrganization.logo`
# — is plumbing.
_KEPT_FIELDS = (
    "title",
    "datePosted",
    "validThrough",
    "employmentType",
    "workHours",
    "jobLocationType",
    "industry",
    "occupationalCategory",
    "educationRequirements",
    "experienceRequirements",
    "qualifications",
    "responsibilities",
    "skills",
    "directApply",
)


def _unescape(text: str) -> str:
    return html_module.unescape(text or "")


def readable(markup: str, *, limit: int = TEXT_LIMIT) -> str:
    """The visible text of an HTML page, block structure kept as newlines."""
    if not markup:
        return ""
    text = _INVISIBLE.sub(" ", markup)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = _unescape(text)
    # Collapse runs of spaces *within* a line, not across lines: the newlines
    # are the only structure that survived the tags.
    text = "\n".join(re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines())
    text = _TRAILING.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text[:limit]


def _walk(node: Any) -> Any:
    """The first `JobPosting` anywhere in a JSON-LD document.

    Sites nest it every way the spec allows: bare, in a list, under `@graph`,
    and occasionally inside a `mainEntity`. `@type` itself is a string on most
    sites and a list on a few.
    """
    if isinstance(node, list):
        for item in node:
            found = _walk(item)
            if found is not None:
                return found
        return None
    if not isinstance(node, dict):
        return None
    types = node.get("@type") or node.get("type") or ""
    types = types if isinstance(types, list) else [types]
    if any(str(kind).lower() == "jobposting" for kind in types):
        return node
    for key in ("@graph", "mainEntity", "itemListElement", "item"):
        if key in node:
            found = _walk(node[key])
            if found is not None:
                return found
    return None


def json_ld_posting(markup: str) -> dict[str, Any] | None:
    """The schema.org `JobPosting` a page publishes about itself, if it has one."""
    for match in _LD_JSON.finditer(markup or ""):
        raw = _unescape(match.group(1)).strip()
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # A page with one malformed block often has a valid one after it.
            logger.debug("Unparseable JSON-LD block, skipping")
            continue
        found = _walk(document)
        if isinstance(found, dict):
            return found
    return None


def _flatten(value: Any, depth: int = 0) -> str:
    """A JSON-LD value as one readable string.

    `jobLocation` is three levels of nested `PostalAddress`, `salaryCurrency`
    hides under `baseSalary.value.minValue`, and `hiringOrganization` is an
    object whose only interesting field is `name`. Flattening beats teaching a
    model each shape.
    """
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if depth >= 4:
        return ""
    if isinstance(value, list):
        parts = [_flatten(item, depth + 1) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        if "name" in value and isinstance(value["name"], str):
            return value["name"].strip()
        parts = [
            _flatten(item, depth + 1)
            for key, item in value.items()
            if not str(key).startswith("@")
        ]
        return ", ".join(part for part in parts if part)
    return ""


def structured_facts(posting: dict[str, Any] | None) -> str:
    """The JSON-LD posting as labelled lines, or `""` when the page carried none."""
    if not posting:
        return ""
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        rendered = _flatten(value)
        if rendered:
            lines.append(f"- {label}: {rendered}")

    add("title", posting.get("title"))
    add("company", posting.get("hiringOrganization"))
    add("location", posting.get("jobLocation"))
    add("remote", posting.get("applicantLocationRequirements"))
    add("compensation", posting.get("baseSalary"))
    for field in _KEPT_FIELDS:
        if field != "title" and field in posting:
            add(field, posting[field])

    if not lines:
        return ""

    description = readable(str(posting.get("description") or ""), limit=DESCRIPTION_LIMIT)
    body = "\n".join(lines)
    if description:
        body += f"\n\n### The posting's own description\n\n{description}"
    return body


def for_reader(markup: str, *, limit: int = TEXT_LIMIT) -> str:
    """Everything worth handing a model about one fetched job page.

    Returns `""` when the page yielded nothing readable at all — which is what a
    bot-protection interstitial or an empty single-page-app shell looks like,
    and the caller's cue to open it in a real browser instead.
    """
    facts = structured_facts(json_ld_posting(markup))
    text = readable(markup, limit=limit)
    if not facts and not text:
        return ""

    sections = []
    if facts:
        sections.append(
            "## What the page publishes about itself (schema.org JobPosting)\n\n"
            "Structured data the employer or the board filled in. Trust it for\n"
            "dates and names; it is occasionally a stale copy, so prefer the\n"
            "visible text below wherever the two disagree about prose.\n\n" + facts
        )
    if text:
        sections.append("## The visible text of the page\n\n" + text)
    return "\n\n".join(sections)
