"""Filling the blanks in the candidate's own .docx, and nothing else.

This replaced "generate a résumé into a fixed template" on 2026-08-28, narrowed
again on 2026-08-29, and took over the cover letter on 2026-09-09. The candidate
supplies four finished Word documents — a résumé and a letter, each in French
and in English — and those *are* the documents an employer receives. A run does
not rebuild them and, since the narrowing, does not re-word them either: it
fills the placeholders they deliberately left behind (`[job_title]`,
`[list_of_relevant_skills]`, `[cover_letter_opening_paragraph]`) and touches
nothing outside those brackets.

Nothing in this module knows which of the two kinds it is holding. A résumé and
a letter differ in what their blanks are worth (`services/page_fit.py`) and in
who answers them (`services/letter_fields.py`), never in how one is filled.

## Why filling beats re-wording

The first version let the model return `{index, text}` for any line, with a
character budget to keep it honest. It worked, and it was still the wrong shape:
"you may re-word any line, but only a little" is a rule that has to be measured,
argued about with a critic, and re-checked every run — and every one of those
checks is a place the candidate's own sentence can come back subtly different.

Filling a placeholder is not a smaller version of that. It is a different
operation with nothing to police: the text outside the brackets is copied
byte-for-byte because the code slices around the placeholder span, so
"the layout did not change" and "my sentences are still mine" stop being
properties anyone has to verify. What the model chooses is what goes *in the
blank the candidate cut for it*.

## The block model

The document is flattened into an ordered list of `Block`s — one per paragraph,
body paragraphs and table cells alike, blank ones included. Blocks are what the
preview, the critic and the language check read. They are no longer a handle an
agent can address: the only thing an agent may name is a `Slot`.

## The slot model

Every placeholder occurrence in the document is a `Slot` with a stable key
(`s0`, `s1`, …), the token it stands for, the block it lives in and its exact
character span. `filled_lines()` rebuilds each affected line by slicing the
original around those spans, so nothing but the blanks can move. An agent
returns `{slot, text}` pairs; there is no vocabulary for anything else.

## Formatting survives a fill

A paragraph is usually several runs — `**Acme Corp**` then a tab then
`Paris, France` — and writing the whole new line into the first run would make
the location bold too. So the new line is diffed against the original
(`difflib`) and only the characters that actually changed are written, into the
run that owned them. A placeholder that sat in an italic run comes back italic,
because the run it goes into is the run it came out of.

Tabs and line breaks survive the round trip: python-docx's `Run.text` setter
re-encodes `\t` as `w:tab` and `\n` as `w:br`. Runs inside a hyperlink are
flattened into the same span list, because `Paragraph.text` includes them while
`Paragraph.runs` does not — indexing off `runs` alone would put every fill after
a link at the wrong offset.

A paragraph holding a drawing, a picture or a field is reported as not editable,
and a placeholder inside one is refused, because `Run.text` would drop the
drawing.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .job_titles import field_name, format_sentence_elisions_and_redundancies

logger = logging.getLogger(__name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# The most paragraphs one base résumé may have. A one- or two-page CV lands
# around 40–120 including blank lines; 300 is headroom, not a target. It is a
# hard ceiling because `read_blocks` is what the preview and the language check
# read, and a document this cannot hold is one nothing downstream can show.
MAX_BLOCKS = 300

# The most placeholders one base résumé may have. This *is* a target: the slot
# key is a `Literal` enum in the agent's output schema (`agents/schemas.py`), so
# a slot the model has no name for is a blank that never gets filled. Forty is
# already an odd résumé — the candidate's own carry four.
MAX_SLOTS = 40

# Slot keys, in document order. Strings rather than integers, and a `Literal`
# rather than a bounded int, for the reason recorded on `ScoredPosting.index`:
# under constrained decoding every further digit of an integer is still a valid
# integer, so nothing in the grammar ever tells the model to stop, and a corrupt
# join key loses the fill.
SLOT_KEYS = tuple(f"s{number}" for number in range(MAX_SLOTS))


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------

# `[Target role]`, `{{company}}`, `<job title>`, `______`. Every form requires a
# letter inside, so a bracketed year (`[2024]`) or a footnote marker is not
# mistaken for something the agent must fill.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\[[^\[\]\n]*[^\W\d_][^\[\]\n]*\]"),
    re.compile(r"\{\{[^{}\n]*[^\W\d_][^{}\n]*\}\}"),
    # No space just inside the angles, or `a < b and c > d` reads as a
    # placeholder. `<target role>` still does.
    re.compile(r"<[^<>\s](?:[^<>\n]*[^<>\s])?>"),
    re.compile(r"_{3,}"),
)


def placeholder_spans(text: str) -> list[tuple[int, int, str]]:
    """Every placeholder in one line as `(start, end, token)`, in reading order.

    Overlaps are dropped rather than merged. `[<role>]` matches two patterns and
    is one blank; keeping both would fill it twice and leave a stray bracket on
    the candidate's page.
    """
    found: list[tuple[int, int, str]] = []
    for pattern in _PLACEHOLDER_PATTERNS:
        found.extend((match.start(), match.end(), match.group(0)) for match in pattern.finditer(text))
    spans: list[tuple[int, int, str]] = []
    for start, end, token in sorted(found, key=lambda item: (item[0], -item[1])):
        if spans and start < spans[-1][1]:
            continue
        spans.append((start, end, token))
    return spans


def find_placeholders(text: str) -> list[str]:
    """Every placeholder token in one line, in the order they appear."""
    return [token for _, _, token in placeholder_spans(text)]


# ---------------------------------------------------------------------------
# The block model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """One paragraph of the base document, as the agent sees it."""

    index: int
    text: str
    # "body" or "cell" — only so the preview can lay a table row out as one.
    kind: str = "body"
    style: str = ""
    # Centred / right-aligned headings are the shape of the document, so the
    # preview reproduces them; nothing else reads this.
    alignment: str = ""
    bold: bool = False
    # A paragraph holding a picture or a field: readable, never rewritten.
    editable: bool = True
    # Why not, when it is not: "picture" or "empty". They need different words —
    # a blank spacing line and a line holding a logo are refused for different
    # reasons, and an agent told the wrong one fixes the wrong thing.
    editable_reason: str = ""
    placeholders: tuple[str, ...] = ()

    @property
    def blank(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True)
class Slot:
    """One placeholder occurrence — the only thing an agent is allowed to name.

    `start` and `end` are offsets into the block's **original** text, which is
    what makes the guarantee mechanical: `filled_lines` slices the line around
    them, so every character outside the span is copied rather than regenerated.
    """

    key: str
    token: str
    block: int
    start: int
    end: int
    line: str = ""
    # Characters this fill may run to. Computed from the room left on the page
    # by `services/page_fit.slot_budgets`, not stored in the document.
    budget: int = 0

    @property
    def name(self) -> str:
        """How the slot is written in a prompt and in an error message."""
        return f"{self.key} ({self.token})"


def find_slots(blocks: list[Block]) -> list[Slot]:
    """Every placeholder in the document, in reading order, keyed `s0`, `s1`, …

    Truncated at `MAX_SLOTS` rather than raising: `base_documents.validate` refuses
    a document with more than that at upload, so reaching the cap here means an
    older upload, and filling forty blanks beats failing the run outright.
    """
    slots: list[Slot] = []
    for block in blocks:
        if not block.placeholders:
            continue
        for start, end, token in placeholder_spans(block.text):
            if len(slots) >= MAX_SLOTS:
                logger.warning("Base résumé has more than %s placeholders", MAX_SLOTS)
                return slots
            slots.append(
                Slot(
                    key=SLOT_KEYS[len(slots)],
                    token=token,
                    block=block.index,
                    start=start,
                    end=end,
                    line=block.text,
                )
            )
    return slots


def slots_payload(slots: list[Slot]) -> list[dict[str, Any]]:
    """The slots as plain JSON, to travel with the saved artifact."""
    return [
        {
            "key": slot.key,
            "token": slot.token,
            "block": slot.block,
            "start": slot.start,
            "end": slot.end,
            "line": slot.line,
            "budget": slot.budget,
        }
        for slot in slots
    ]


def slots_from_payload(payload: Any) -> list[Slot]:
    """The inverse, tolerant of anything an older artifact happens to hold."""
    slots: list[Slot] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        try:
            slots.append(
                Slot(
                    key=str(item.get("key") or ""),
                    token=str(item.get("token") or ""),
                    block=int(item.get("block", 0)),
                    start=int(item.get("start", 0)),
                    end=int(item.get("end", 0)),
                    line=str(item.get("line") or ""),
                    budget=int(item.get("budget", 0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return slots


def with_budgets(slots: list[Slot], budgets: Mapping[str, int]) -> list[Slot]:
    """The same slots carrying the character budgets `page_fit` worked out."""
    return [
        Slot(**{**slot.__dict__, "budget": int(budgets.get(slot.key, slot.budget))})
        for slot in slots
    ]


@dataclass
class Span:
    """One run of a paragraph, and the character range of the paragraph it owns."""

    run: Any
    start: int
    end: int
    text: str = ""


@dataclass
class ApplyReport:
    """What `apply_lines` actually did, for the caller to log or refuse."""

    applied: list[int] = field(default_factory=list)
    skipped: dict[int, str] = field(default_factory=dict)


def _iter_paragraphs(container) -> Iterator[Any]:
    """Every paragraph under one container, in document order, tables included.

    `Document.paragraphs` skips everything inside a table, and a résumé that
    lays its header out as a two-cell table would hand the agent a document with
    its name missing. Walking the body's own children keeps the reading order
    the document has.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    # `_element` rather than `.element`: a `Document` exposes both, a table
    # cell only the former.
    element = getattr(container, "_element", None)
    if element is None:
        element = container.element
    body = getattr(element, "body", element)
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, container)
        elif child.tag.endswith("}tbl"):
            table = Table(child, container)
            for row in table.rows:
                for cell in row.cells:
                    yield from _iter_paragraphs(cell)


def _spans(paragraph) -> list[Span]:
    """The paragraph's runs with their character offsets, hyperlinks flattened.

    `Paragraph.text` includes the text of runs inside a `w:hyperlink` while
    `Paragraph.runs` does not, so offsets taken from `runs` drift the moment the
    document has a link in it — which a résumé always does.
    """
    from docx.text.hyperlink import Hyperlink
    from docx.text.run import Run

    spans: list[Span] = []
    cursor = 0
    for item in paragraph.iter_inner_content():
        runs = [item] if isinstance(item, Run) else (item.runs if isinstance(item, Hyperlink) else [])
        for run in runs:
            text = run.text
            spans.append(Span(run=run, start=cursor, end=cursor + len(text), text=text))
            cursor += len(text)
    return spans


def _paragraph_text(paragraph) -> str:
    return "".join(span.text for span in _spans(paragraph))


def _editable_reason(paragraph) -> str:
    """Why a paragraph may not be rewritten, or `""` when it may.

    `Run.text = …` replaces every child of the run, so a run holding a drawing
    loses the drawing. A paragraph with no runs at all cannot be edited either
    without inventing one, and inventing a run in a blank line is exactly the
    structural change this module exists to prevent.
    """
    xml = paragraph._p.xml
    if any(tag in xml for tag in ("<w:drawing", "<w:pict", "<w:fldChar", "<w:object")):
        return "picture"
    return "" if _spans(paragraph) else "empty"


def _is_editable(paragraph) -> bool:
    return not _editable_reason(paragraph)


_ALIGNMENTS = {0: "left", 1: "center", 2: "right", 3: "justify"}


def _all_bold(spans: list[Span]) -> bool:
    """Whether every run carrying text is bold — the shape of a heading line."""
    inked = [span for span in spans if span.text.strip()]
    return bool(inked) and all(span.run.bold for span in inked)


def read_blocks(data: bytes) -> list[Block]:
    """Flatten a .docx into the indexed list of paragraphs an agent works on."""
    from docx import Document

    document = Document(io.BytesIO(data))
    blocks: list[Block] = []
    for paragraph in _iter_paragraphs(document):
        spans = _spans(paragraph)
        text = "".join(span.text for span in spans)
        alignment = paragraph.paragraph_format.alignment
        blocks.append(
            Block(
                index=len(blocks),
                text=text,
                kind="cell" if paragraph._p.getparent().tag.endswith("}tc") else "body",
                style=(paragraph.style.name if paragraph.style is not None else ""),
                alignment=_ALIGNMENTS.get(int(alignment), "") if alignment is not None else "",
                bold=_all_bold(spans),
                editable=not (reason := _editable_reason(paragraph)),
                editable_reason=reason,
                placeholders=tuple(find_placeholders(text)),
            )
        )
    return blocks


def blocks_payload(blocks: list[Block]) -> list[dict[str, Any]]:
    """The blocks as plain JSON, to travel with the saved artifact.

    Stored on the artifact so the preview, the audit and a re-read months later
    still work when the base document has been replaced or deleted. Exporting
    still needs the file itself — this is the text, not the formatting.
    """
    return [
        {
            "index": block.index,
            "text": block.text,
            "kind": block.kind,
            "style": block.style,
            "alignment": block.alignment,
            "bold": block.bold,
            "editable": block.editable,
            "editable_reason": block.editable_reason,
        }
        for block in blocks
    ]


def blocks_from_payload(payload: Any) -> list[Block]:
    """The inverse, tolerant of anything an older artifact happens to hold."""
    blocks: list[Block] = []
    for index, item in enumerate(payload or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        blocks.append(
            Block(
                index=int(item.get("index", index)),
                text=text,
                kind=str(item.get("kind") or "body"),
                style=str(item.get("style") or ""),
                alignment=str(item.get("alignment") or ""),
                bold=bool(item.get("bold")),
                editable=bool(item.get("editable", True)),
                editable_reason=str(item.get("editable_reason") or ""),
                placeholders=tuple(find_placeholders(text)),
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------


def fill_map(artifact: Mapping[str, Any]) -> dict[str, str]:
    """The artifact's fills as `{slot key: text}`, tolerantly.

    A local model reached through LiteLLM is bound by no schema at all, so
    anything unparseable is dropped here rather than raising inside the gate. A
    dropped fill shows up as an unfilled placeholder, which is feedback the
    agent can act on; a traceback is not.
    """
    fills: dict[str, str] = {}
    for item in artifact.get("fills") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("slot") or "").strip()
        if key:
            fills[key] = str(item.get("text") or "")
    return fills


def filled_lines(
    blocks: list[Block], slots: list[Slot], fills: Mapping[str, str]
) -> dict[int, str]:
    """The lines that change, as `{block index: new text}`.

    Built by slicing each original line around its placeholder spans, so every
    character the candidate wrote is copied rather than re-emitted.

    A slot with **no fill at all** keeps its token — `check_fills` is what
    refuses that; leaving it visible means the preview shows the blank that was
    missed instead of a line that silently lost a word. A slot filled with the
    **empty string** is a different answer and is written as one: that is how a
    cover letter's address block says "the posting does not give a street", and
    falling back to the token there would print `[address_company]` on a
    document going to an employer — the worst outcome this system has.
    """
    by_block: dict[int, list[Slot]] = {}
    for slot in slots:
        by_block.setdefault(slot.block, []).append(slot)

    lines: dict[int, str] = {}
    for block in blocks:
        group = by_block.get(block.index)
        if not group:
            continue
        pieces: list[str] = []
        cursor = 0
        for slot in sorted(group, key=lambda item: item.start):
            preceding = block.text[cursor : slot.start]
            raw_text = fills.get(slot.key)
            if raw_text is not None:
                token_name = field_name(slot.token)
                preceding, text = format_sentence_elisions_and_redundancies(
                    preceding, raw_text, token_name
                )
                if re.search(r"\bstagiaire\b", text, re.IGNORECASE):
                    pieces = [
                        re.sub(
                            r"stage\s+de\s+fin\s+d['’]études",
                            "projet de fin d'études",
                            p,
                            flags=re.IGNORECASE,
                        )
                        for p in pieces
                    ]
                pieces.append(preceding)
                pieces.append(text)
            else:
                pieces.append(preceding)
                pieces.append(slot.token)
            cursor = slot.end
        pieces.append(block.text[cursor:])
        lines[block.index] = "".join(pieces)
    return lines


def check_fills(
    blocks: list[Block],
    slots: list[Slot],
    fills: Mapping[str, str],
    *,
    optional: Collection[str] = (),
) -> list[str]:
    """Everything wrong with a proposed set of fills, in words the agent can act on.

    Deterministic and complete: this is the gate, so nothing here is a matter of
    taste. It is a much shorter list than the one the re-wording design needed,
    which is the point — most of what that gate policed is now unreachable.

    1. a slot key that is not in the document;
    2. a blank left unfilled;
    3. a fill that is empty, or that is still a placeholder;
    4. a fill carrying a tab or a line break — either one moves the layout, and
       a tab in these templates is a column stop;
    5. a fill over its character budget;
    6. a blank inside a paragraph that holds a picture or a field, which cannot
       be written to without losing the picture.

    `optional` is the exception to rule 3, and it exists for exactly one shape of
    blank: a cover letter's street address and postal code, which the posting
    states or nobody knows. An empty line in an address block is normal; an
    invented street is a fabricated fact on a document going to an employer. It
    is never "this blank does not matter" — the key still has to be answered,
    and every other rule still applies to it. `services/letter_fields.py` decides
    which blanks qualify.

    The page itself is checked by `services/page_fit.page_problems`, which needs
    the file rather than the text.
    """
    problems: list[str] = []
    by_key = {slot.key: slot for slot in slots}
    by_block = {block.index: block for block in blocks}

    for key in sorted(set(fills) - set(by_key)):
        problems.append(
            f"There is no slot {key!r} in this document. The slots are: "
            + (", ".join(slot.key for slot in slots) or "(none)")
            + "."
        )

    for slot in slots:
        block = by_block.get(slot.block)
        if block is not None and block.editable_reason == "picture":
            problems.append(
                f"{slot.name} sits in a paragraph holding a picture or a field, which cannot be "
                "written to. Tell the candidate to move that placeholder into ordinary text."
            )
            continue
        text = fills.get(slot.key)
        if text is None:
            problems.append(
                f"{slot.name} was left unfilled. Every blank in the document must come back as "
                f"real text — this one is on the line: {slot.line.strip()!r}"
            )
            continue
        if not text.strip():
            if slot.key in optional:
                continue
            problems.append(
                f"{slot.name} came back empty. Fill it with real text; an empty blank leaves the "
                "candidate's sentence missing a word."
            )
            continue
        if leftover := find_placeholders(text):
            problems.append(
                f"{slot.name} was filled with another placeholder ({', '.join(leftover)}). "
                "Write the actual text."
            )
        if "\t" in text:
            problems.append(
                f"{slot.name} contains a tab. Tabs are this template's column stops and a new one "
                "moves the layout — write plain text."
            )
        if "\n" in text or "\r" in text:
            problems.append(
                f"{slot.name} contains a line break. One line of the document is one line on the "
                "page; a break adds a line the candidate did not lay out."
            )
        if slot.budget and len(text) > slot.budget:
            problems.append(
                f"{slot.name} is {len(text)} characters against a budget of {slot.budget}. "
                "That is the room left on the page, measured on the candidate's own document — "
                "say it shorter, or say less of it."
            )
    return problems


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def _slot_for(spans: list[Span], position: int) -> int:
    """Which run owns a character position — the last one, for a position at the end."""
    for slot, span in enumerate(spans):
        if span.start <= position < span.end:
            return slot
    return len(spans) - 1


def _rewrite(paragraph, new_text: str) -> None:
    """Swap a paragraph's text, rewriting only the runs whose characters changed.

    The diff is what keeps the formatting: `**Acme Corp**\tParis` re-worded to
    `**Acme Corp**\tLyon` touches the second run only, so the employer stays bold
    without anything here knowing it was.
    """
    spans = _spans(paragraph)
    if not spans:
        return
    old = "".join(span.text for span in spans)
    if old == new_text:
        return

    buffers = ["" for _ in spans]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new_text, autojunk=False).get_opcodes():
        if tag == "equal":
            # Copied through, split back at the run boundaries it spans.
            for slot, span in enumerate(spans):
                low, high = max(i1, span.start), min(i2, span.end)
                if low < high:
                    buffers[slot] += old[low:high]
            continue
        if tag == "delete":
            continue
        # insert / replace — the new characters go to the run that owned the
        # position they start at, so they inherit its formatting.
        buffers[_slot_for(spans, i1)] += new_text[j1:j2]

    for span, buffer in zip(spans, buffers, strict=True):
        if span.text != buffer:
            span.run.text = buffer


def apply_lines(
    data: bytes, lines: Mapping[int, str], *, title: str = ""
) -> tuple[bytes, ApplyReport]:
    """The base document with those lines written into it. Returns the new .docx bytes.

    Mechanical: it takes whole lines and does not care where they came from.
    `apply_fills` is the entry point a run uses — it builds the lines by slicing
    around placeholder spans, which is what makes the rest of the page
    untouchable.

    `title` is written to the document's core properties — Word shows it in
    Info, some ATS read it, and it costs one line. It is not printed anywhere on
    the page, so it cannot disturb the layout.
    """
    from docx import Document

    document = Document(io.BytesIO(data))
    paragraphs = list(_iter_paragraphs(document))
    report = ApplyReport()

    for index, text in sorted(lines.items()):
        if not 0 <= index < len(paragraphs):
            report.skipped[index] = "no such block"
            continue
        paragraph = paragraphs[index]
        reason = _editable_reason(paragraph)
        if reason:
            report.skipped[index] = (
                "holds a picture or a field" if reason == "picture" else "is a blank line"
            )
            continue
        if _paragraph_text(paragraph) == text:
            continue
        _rewrite(paragraph, text)
        report.applied.append(index)

    if title:
        try:
            document.core_properties.title = title[:255]
        except Exception:  # pragma: no cover - a document with no core part
            logger.warning("Could not set the document title", exc_info=True)

    buffer = io.BytesIO()
    document.save(buffer)
    if report.skipped:
        logger.warning("Skipped %s line(s) of the base résumé: %s", len(report.skipped), report.skipped)
    return buffer.getvalue(), report


def apply_fills(
    data: bytes,
    blocks: list[Block],
    slots: list[Slot],
    fills: Mapping[str, str],
    *,
    title: str = "",
) -> tuple[bytes, ApplyReport]:
    """The candidate's document with its blanks filled in. The export path."""
    return apply_lines(data, filled_lines(blocks, slots, fills), title=title)


def tailored_text(blocks: list[Block], lines: Mapping[int, str]) -> str:
    """The document as it will read once the fills land — one line per block.

    This is what the language check and the Critic are shown, because a résumé
    is judged on the words it ends up with rather than on the diff that got
    there.
    """
    return "\n".join(lines.get(block.index, block.text) for block in blocks)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

_PREVIEW_CSS = """
:root { color-scheme: light; }
body {
  margin: 0;
  background: #f4f4f5;
  font-family: "Calibri", "Carlito", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: #18181b;
}
.sheet {
  width: 8.5in;
  min-height: 11in;
  margin: 0 auto;
  padding: 0.85in 0.75in;
  background: #fff;
  box-sizing: border-box;
}
.note {
  width: 8.5in;
  margin: 12px auto 8px;
  font-size: 11px;
  line-height: 1.5;
  color: #52525b;
}
.note b { color: #b45309; }
p { margin: 0; font-size: 11pt; line-height: 1.2; white-space: pre-wrap; }
p.blank { height: 11pt; }
p.center { text-align: center; }
p.right { text-align: right; }
p.justify { text-align: justify; }
p.bold { font-weight: 700; }
p.cell { padding-left: 0.1in; }
p.changed {
  background: #fef3c7;
  box-shadow: -3px 0 0 0 #f59e0b;
}
del { color: #b91c1c; text-decoration: line-through; opacity: 0.75; }
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\t", "&#9;&#9;&#9;")
    )


def preview_html(
    blocks: list[Block],
    lines: Mapping[int, str],
    *,
    title: str = "",
    noun: str = "résumé",
) -> str:
    """The filled document as text, with every changed line marked.

    Deliberately *not* a facsimile of the .docx. Reproducing an arbitrary Word
    document in HTML is a losing game, and pretending to would be worse than
    useless here: the whole point of this design is that the file the employer
    receives is the candidate's own document. So the preview answers the only
    question the candidate actually has — **which lines did it touch, and what
    do they say now** — and says plainly that the formatting comes from the
    file itself.
    """
    changed = {
        index: text
        for index, text in lines.items()
        if any(block.index == index and block.text != text for block in blocks)
    }
    rows: list[str] = []
    for block in blocks:
        text = lines.get(block.index, block.text)
        classes = ["cell" if block.kind == "cell" else "body"]
        if block.alignment in {"center", "right", "justify"}:
            classes.append(block.alignment)
        if block.bold:
            classes.append("bold")
        if not text.strip():
            classes.append("blank")
        if block.index in changed:
            classes.append("changed")
        body = _escape(text)
        if block.index in changed and block.text.strip():
            body += f'<del title="the original line"> ← {_escape(block.text)}</del>'
        rows.append(f'<p class="{" ".join(classes)}">{body}</p>')

    heading = _escape(title) if title else f"Tailored {noun}"
    note = (
        f"<b>{len(changed)} line(s) filled in.</b> This is the text of your own {noun} .docx "
        "with the filled blanks highlighted — the download keeps your fonts, spacing and layout "
        "exactly as you made them. Only the text inside your placeholders was written; every "
        "other character is yours."
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{heading}</title><style>{_PREVIEW_CSS}</style></head><body>"
        f"<div class='note'>{note}</div><div class='sheet'>{''.join(rows)}</div>"
        "</body></html>"
    )
