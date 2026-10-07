"""Estimating how much of a page a .docx takes, so "one page" can be enforced.

The candidate's rule is blunt: **the document that gets sent — the tailored
résumé, and since 2026-09-09 the filled cover letter too — must never run over
one page.** Nothing in this stack can paginate a Word document — python-docx reads
the XML, it does not lay it out, and the two things that could (LibreOffice, a
headless Word) are a hundred megabytes of image for one boolean. So this module
measures the document the way Word would: it resolves each paragraph's font
size, indent and spacing, wraps its text against the usable column width using
real Calibri advance widths, and adds it all up.

## It is an estimate, and it is used where an estimate is honest

Three uses, all deliberately chosen so that being a few percent out is survivable:

* **A budget told to the model.** `slot_budgets()` turns the space left on the
  page into a character allowance per placeholder, which goes into the prompt,
  and `total_target()` says how much of it to actually use. A model given "about
  90 characters" aims; a model given "keep it short" guesses.
* **A gate applied afterwards.** `page_problems()` re-measures the document with
  the fills in it and refuses the run if it spills. The refusal names how many
  lines over it is, because "make it shorter" is not actionable and "you are
  about two lines over" is.
* **The same gate, the other way up.** `short_problems()` refuses a document
  that left most of its page empty. Enforcing only the ceiling taught the model
  to sit far below it — a cover letter arriving at 84% of a page, a coursework
  list stopping three items early — and a blank half-used is a qualification the
  employer never sees. See `FILL_TARGET`.

The error is biased toward refusing rather than allowing: widths are measured
with a bold factor applied wherever the run is bold, a tab is counted as the
full width of the text on both sides of it (the right-tab layout every CV header
uses), and the page capacity carries a margin (`SAFETY`). An estimator that
occasionally says "too long" about a document that would have fitted costs one
revision loop. One that says "fits" about a document that spills costs the
candidate the job.

## Why the widths are a table and not a ratio

The obvious shortcut — average character width ≈ 0.5 em — is wrong by 20% on
real text, and wrong in the direction that matters: résumé lines are full of
`i`, `l`, `t` and spaces (narrow) and of capitals and digits (wide), in
proportions that vary line by line. `_WIDTHS` holds Calibri's own advance
widths, in thousandths of an em. Calibri because it is what the candidate's
documents use and what Word has defaulted to for fifteen years; anything else
falls back to the same table, which is within a few percent for Aptos, Carlito
and Arial, and openly wrong for a monospace or a display face — which is why
`measure()` reports its numbers rather than hiding them, and why the Account
page shows the candidate the percentage it computed for their own file.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .docx_template import Block, Slot

logger = logging.getLogger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Calibri Regular advance widths, thousandths of an em. Anything not listed —
# an accented letter, a dash, a symbol — falls back to `_DEFAULT_WIDTH`, which
# is the width of a digit and slightly generous for most of what turns up.
_DEFAULT_WIDTH = 500
_WIDTHS: dict[str, int] = {
    " ": 229, "!": 247, '"': 271, "#": 500, "$": 500, "%": 659, "&": 695,
    "'": 139, "(": 295, ")": 295, "*": 392, "+": 564, ",": 242, "-": 313,
    ".": 242, "/": 373, ":": 265, ";": 265, "<": 564, "=": 564, ">": 564,
    "?": 375, "@": 880, "[": 295, "\\": 373, "]": 295, "_": 500, "|": 236,
    "A": 579, "B": 544, "C": 544, "D": 602, "E": 488, "F": 470, "G": 627,
    "H": 626, "I": 274, "J": 319, "K": 540, "L": 453, "M": 884, "N": 684,
    "O": 664, "P": 520, "Q": 675, "R": 551, "S": 487, "T": 508, "U": 637,
    "V": 577, "W": 902, "X": 539, "Y": 505, "Z": 502,
    "a": 498, "b": 523, "c": 436, "d": 523, "e": 500, "f": 315, "g": 472,
    "h": 523, "i": 234, "j": 234, "k": 472, "l": 234, "m": 792, "n": 523,
    "o": 519, "p": 523, "q": 523, "r": 338, "s": 407, "t": 329, "u": 523,
    "v": 466, "w": 705, "x": 444, "y": 466, "z": 394,
    "—": 1000, "–": 500, "’": 139, "“": 271, "”": 271, "…": 750, "•": 350,
}
for _digit in "0123456789":
    _WIDTHS[_digit] = 500

# Bold Calibri is a little wider than regular. Applied per run, not per line.
_BOLD_FACTOR = 1.05

# Word's single line spacing for Calibri: (ascent + descent + line gap) / em.
LINE_FACTOR = 1.22

# Word's built-in default when neither the run, the style chain nor the
# document defaults name a size. It is 10pt, not 11pt — 11 is what the *Normal
# style template* usually sets, and a document that sets nothing at all falls
# past that to the format's own default.
_FALLBACK_SIZE = 10.0

# How much of the page this refuses to plan on using. Three points is a quarter
# of a line: enough to absorb the estimator being slightly optimistic about one
# paragraph, small enough not to throw away usable space on a CV that is
# genuinely full.
SAFETY = 3.0

_TWIPS = 20.0  # twips per point
_EMU = 12700.0  # EMU per point


# ---------------------------------------------------------------------------
# Measuring one line
# ---------------------------------------------------------------------------


def text_width(text: str, size: float, *, bold: bool = False) -> float:
    """The width of a string in points, at one font size."""
    em = sum(_WIDTHS.get(char, _DEFAULT_WIDTH) for char in text) / 1000.0
    return em * size * (_BOLD_FACTOR if bold else 1.0)


def wrapped_lines(pieces: list[tuple[str, float, bool]], width: float) -> int:
    """How many lines a run of formatted pieces takes in a column that wide.

    Greedy word wrapping, which is what Word does for Latin script. Each piece
    carries its own size and weight, because a heading line is regularly
    `**Employer**` at one size followed by a location at another, and measuring
    the whole line at the larger of the two is how an estimate ends up 14% out.

    A tab is treated as a segment boundary whose two sides both have to fit on
    the line, which is the right reading of the right-tab header every CV uses:
    `Employer<TAB>City` is one line exactly when the two pieces fit side by side.
    """
    if width <= 0:
        return 1
    lines = 1
    used = 0.0
    pending = ""  # the word being built, which may span several runs
    pending_width = 0.0

    def place(advance: float) -> None:
        """Put one word on the line, breaking it across lines if it cannot fit.

        The second half is not a detail. Word breaks a word wider than the
        column rather than letting it overhang, and a wrapper that does not
        counts a 40,000-character run as **one line** — which is exactly what a
        runaway fill looks like, and exactly the case the page gate exists to
        refuse. Caught by `scripts/smoke.sh`, which sends one.
        """
        nonlocal used, lines
        if used and used + advance > width:
            lines += 1
            used = 0.0
        if advance > width:
            spans = int(advance // width)
            lines += spans
            used = advance - spans * width
        else:
            used += advance

    for text, size, bold in pieces:
        for char in text:
            if char in " \t\n":
                if pending:
                    place(pending_width)
                    pending, pending_width = "", 0.0
                if char == "\n":
                    lines += 1
                    used = 0.0
                elif char == "\t":
                    used += 0.0  # the tab itself takes no guaranteed width
                else:
                    used += text_width(" ", size, bold=bold)
                continue
            pending += char
            pending_width += text_width(char, size, bold=bold)
    if pending:
        place(pending_width)
    return max(1, lines)


# ---------------------------------------------------------------------------
# Reading the document's geometry
# ---------------------------------------------------------------------------


def _half_points(element, path: str) -> float | None:
    node = element.find(path) if element is not None else None
    if node is None:
        return None
    value = node.get(f"{W}val")
    try:
        return float(value) / 2.0
    except (TypeError, ValueError):
        return None


def _style_size(style) -> float | None:
    """A style's font size, following the chain to its base style."""
    seen = 0
    while style is not None and seen < 12:
        if style.font.size is not None:
            return style.font.size.pt
        style = style.base_style
        seen += 1
    return None


def _numbering_indent(document, num_id: str, level: str) -> float:
    """The left indent a numbering definition applies, in points.

    A bulleted paragraph usually carries no `w:ind` of its own — the indent
    lives in `numbering.xml`, and ignoring it measures every bullet against a
    column 18pt wider than the one it is actually in.
    """
    try:
        numbering = document.part.numbering_part.element
    except (AttributeError, NotImplementedError, KeyError):
        return 0.0
    num = numbering.find(f'{W}num[@{W}numId="{num_id}"]')
    if num is None:
        return 0.0
    abstract = num.find(f"{W}abstractNumId")
    if abstract is None:
        return 0.0
    definition = numbering.find(
        f'{W}abstractNum[@{W}abstractNumId="{abstract.get(f"{W}val")}"]'
    )
    if definition is None:
        return 0.0
    lvl = definition.find(f'{W}lvl[@{W}ilvl="{level}"]')
    if lvl is None:
        return 0.0
    ind = lvl.find(f"{W}pPr/{W}ind")
    if ind is None:
        return 0.0
    try:
        return float(ind.get(f"{W}left") or 0) / _TWIPS
    except (TypeError, ValueError):
        return 0.0


def _border_height(paragraph) -> float:
    """What a paragraph's rules add to its height, in points.

    Only the stroke itself (`w:sz` is in eighths of a point). `w:space`, the gap
    Word puts between the text and the rule, is deliberately **not** added: on
    the documents this was calibrated against it is smaller than the paragraph's
    own space-after, and counting both put the estimate a percent over a
    document Word itself records as one page. Treating the gap as absorbed by
    the space-after is the reading that reconciles the two.

    Small either way, and worth having at all only because a CV's section rules
    come five to a page.
    """
    borders = paragraph._p.find(f"{W}pPr/{W}pBdr")
    if borders is None:
        return 0.0
    height = 0.0
    for edge in borders:
        if not edge.tag.endswith(("}top", "}bottom")):
            continue
        try:
            height += float(edge.get(f"{W}sz") or 0) / 8.0
        except (TypeError, ValueError):
            continue
    return height


@dataclass(frozen=True)
class Paragraph:
    """One paragraph, measured."""

    index: int
    lines: int
    height: float
    size: float
    column: float
    chars: int
    ink: float


@dataclass(frozen=True)
class Estimate:
    """What one document comes to, and how much room is left on its first page."""

    height: float
    capacity: float
    paragraphs: tuple[Paragraph, ...]
    body_size: float
    body_width: float
    char_width: float
    page_break: bool = False
    # What Word itself recorded the last time it saved the file, when it did.
    # Ground truth where it exists, and absent from anything python-docx wrote.
    word_pages: int = 0

    @property
    def fits(self) -> bool:
        return not self.page_break and self.height <= self.capacity

    @property
    def fraction(self) -> float:
        """How much of one page the content fills. 1.04 is four percent over."""
        return self.height / self.capacity if self.capacity else 0.0

    @property
    def line_height(self) -> float:
        return self.body_size * LINE_FACTOR

    @property
    def slack_lines(self) -> float:
        """Body lines still free on the page. Negative when it has spilled."""
        return (self.ceiling - self.height) / self.line_height

    @property
    def ceiling(self) -> float:
        """The height this document is allowed to reach. See `allowance`."""
        return max(self.capacity, self.height) if self.word_pages == 1 else self.capacity

    @property
    def slack_chars(self) -> int:
        """Roughly how many more characters of body text the page can take."""
        if self.char_width <= 0:
            return 0
        return max(0, int(self.slack_lines * (self.body_width / self.char_width)))


def _pieces(paragraph, default_size: float) -> list[tuple[str, float, bool]]:
    """A paragraph's text as `(text, size, bold)` runs, hyperlinks included."""
    from docx.text.hyperlink import Hyperlink
    from docx.text.run import Run

    style_size = _style_size(paragraph.style) or default_size
    pieces: list[tuple[str, float, bool]] = []
    for item in paragraph.iter_inner_content():
        runs = [item] if isinstance(item, Run) else (item.runs if isinstance(item, Hyperlink) else [])
        for run in runs:
            if not run.text:
                continue
            size = run.font.size.pt if run.font.size is not None else style_size
            pieces.append((run.text, size, bool(run.bold)))
    return pieces


def _spacing(paragraph, size: float) -> tuple[float, float, float]:
    """Space before, space after, and the line height, all in points."""
    fmt = paragraph.paragraph_format
    before = fmt.space_before.pt if fmt.space_before is not None else 0.0
    after = fmt.space_after.pt if fmt.space_after is not None else 0.0
    line = size * LINE_FACTOR
    if fmt.line_spacing is not None:
        spacing = fmt.line_spacing
        # python-docx gives a float for a multiple and a Length for an exact
        # value; both are usable, the Length via `.pt`.
        line = spacing * size * LINE_FACTOR if isinstance(spacing, float) else spacing.pt
    return before, after, line


def _style_indent(style) -> tuple[float | None, float | None]:
    """A style's own left and right indent, following the chain to its base."""
    seen = 0
    left = right = None
    while style is not None and seen < 12:
        fmt = getattr(style, "paragraph_format", None)
        if fmt is not None:
            if left is None and fmt.left_indent is not None:
                left = fmt.left_indent.pt
            if right is None and fmt.right_indent is not None:
                right = fmt.right_indent.pt
        style = style.base_style
        seen += 1
    return left, right


def _indents(paragraph, document) -> float:
    """Total horizontal indent, in points, wherever the indent actually lives.

    Three places, in the order Word resolves them: the paragraph, its style
    chain, and the numbering definition. A bulleted paragraph usually carries no
    `w:ind` at all — the indent is in `numbering.xml`, referenced through a
    `numPr` that may itself sit on the style rather than the paragraph — and a
    reader that only looks at the paragraph measures every bullet against a
    column 18pt wider than the one it is in.
    """
    fmt = paragraph.paragraph_format
    style_left, style_right = _style_indent(paragraph.style)
    left = fmt.left_indent.pt if fmt.left_indent is not None else style_left
    right = fmt.right_indent.pt if fmt.right_indent is not None else style_right
    if left is None:
        num_pr = paragraph._p.find(f"{W}pPr/{W}numPr")
        if num_pr is None and paragraph.style is not None:
            num_pr = paragraph.style.element.find(f"{W}pPr/{W}numPr")
        if num_pr is not None:
            num_id = num_pr.find(f"{W}numId")
            ilvl = num_pr.find(f"{W}ilvl")
            left = _numbering_indent(
                document,
                (num_id.get(f"{W}val") if num_id is not None else "") or "",
                (ilvl.get(f"{W}val") if ilvl is not None else "0") or "0",
            )
        else:
            left = 0.0
    return max(0.0, left or 0.0) + max(0.0, right or 0.0)


def word_page_count(data: bytes) -> int:
    """The page count Word wrote into the file, or 0 if there is none.

    `docProps/app.xml` carries `<Pages>`, and Word recomputes it on every save.
    It is the only ground truth available here — python-docx cannot lay a page
    out — so it is used to *check* the estimate on the candidate's own upload
    rather than to replace it.

    Only ever read from the **base document**, and that restriction matters:
    python-docx neither computes nor clears these statistics, and its default
    template ships an `app.xml` claiming one page, so the number on anything
    this app saved is whatever the file it started from happened to say. On the
    candidate's own upload it is Word's, and current.
    """
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("docProps/app.xml").decode("utf-8", "replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return 0
    match = re.search(r"<Pages>(\d+)</Pages>", xml)
    return int(match.group(1)) if match else 0


def measure(data: bytes) -> Estimate:
    """Estimate the document's height, paragraph by paragraph.

    Measures the real file rather than a text substitution, which is why
    `page_problems` builds the filled .docx before calling this: a fill lands in
    a run whose size and weight are the candidate's, and the only way to be sure
    the measurement uses them is to measure the document that will be sent.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph as DocxParagraph

    document = Document(io.BytesIO(data))
    section = document.sections[0]
    capacity = (
        section.page_height - section.top_margin - section.bottom_margin
    ) / _EMU - SAFETY
    full_width = (section.page_width - section.left_margin - section.right_margin) / _EMU

    default_size = _FALLBACK_SIZE
    try:
        found = _half_points(
            document.styles.element, f"{W}docDefaults/{W}rPrDefault/{W}rPr/{W}sz"
        )
        default_size = found or (_style_size(document.styles["Normal"]) or _FALLBACK_SIZE)
    except Exception:  # pragma: no cover - a document with no styles part
        logger.debug("Could not read the document's default font size", exc_info=True)

    measured: list[Paragraph] = []
    counter = 0
    page_break = False

    def take(paragraph, width: float) -> float:
        nonlocal counter, page_break
        index = counter
        counter += 1
        pieces = _pieces(paragraph, default_size)
        text = "".join(piece[0] for piece in pieces)
        size = max((piece[1] for piece in pieces), default=default_size)
        before, after, line = _spacing(paragraph, size)
        column = max(1.0, width - _indents(paragraph, document))
        lines = wrapped_lines(pieces, column)
        height = before + after + _border_height(paragraph) + lines * line
        xml = paragraph._p.xml
        if f"{W}br" in xml.replace("w:br", f"{W}br") and 'w:type="page"' in xml:
            page_break = True
        measured.append(
            Paragraph(
                index=index,
                lines=lines,
                height=height,
                size=size,
                column=column,
                chars=len(text),
                ink=sum(text_width(t, s, bold=b) for t, s, b in pieces),
            )
        )
        return height

    def walk(container, width: float) -> float:
        element = getattr(container, "_element", None)
        if element is None:
            element = container.element
        body = getattr(element, "body", element)
        height = 0.0
        for child in body.iterchildren():
            if child.tag.endswith("}p"):
                height += take(DocxParagraph(child, container), width)
            elif child.tag.endswith("}tbl"):
                table = Table(child, container)
                for row in table.rows:
                    cells = list(row.cells)
                    share = width / max(1, len(cells))
                    height += max((walk(cell, share) for cell in cells), default=0.0)
        return height

    total = walk(document, full_width)

    body_size = _body_size(measured, default_size)
    body_width = max(
        (item.column for item in measured if abs(item.size - body_size) < 0.01),
        default=full_width,
    )
    body = [item for item in measured if item.chars and abs(item.size - body_size) < 0.01]
    char_width = (
        sum(item.ink for item in body) / sum(item.chars for item in body) if body else 5.0
    )
    return Estimate(
        height=total,
        capacity=capacity,
        paragraphs=tuple(measured),
        body_size=body_size,
        body_width=body_width,
        char_width=char_width,
        page_break=page_break,
        word_pages=word_page_count(data),
    )


def _body_size(measured: list[Paragraph], fallback: float) -> float:
    """The size most of the document's characters are set in."""
    weights: dict[float, int] = {}
    for item in measured:
        weights[item.size] = weights.get(item.size, 0) + item.chars
    if not weights:
        return fallback
    return max(weights.items(), key=lambda pair: pair[1])[0]




# ---------------------------------------------------------------------------
# Budgets and the gate
# ---------------------------------------------------------------------------

# Even on a page with no room left, a blank has to be fillable: `[job_title]`
# needs about this much to hold "Ingénieur Machine Learning".
SLOT_FLOOR = 40

# And no single blank on a résumé may become a paragraph, however much room the
# page has: a CV blank is a title, a keyword sentence or a list.
SLOT_CEILING = 400

# A cover letter's blanks *are* paragraphs, so the same ceiling would cap the
# letter at about 200 words — half of what one is. The candidate's own templates
# measure 69% (EN) and 73% (FR) of a page with the placeholders still in them,
# which leaves 2,513 and 2,174 characters for four open blanks: the team to
# address and the three paragraphs. 900 lets one paragraph run long without
# letting three of them fill the page — the total, and `page_problems` behind
# it, is still what actually holds.
LETTER_SLOT_CEILING = 900

# A blank may take a multiple of its equal share of the free space. The mix a
# real template asks for is lopsided — a job title is four words and a course
# list is three lines — so an equal split would starve the long ones while the
# short ones handed their allowance back unused. Taking more than the share
# leaves the *total* free-space figure, and the page check behind it, to do the
# real work.
#
# **How lopsided decides the number, and it differs by document.** On the CV two
# of the four blanks are long, so twice the share covers them. On the cover
# letter three of the eight are — the paragraphs — and the other five are a
# team name, a reference line and an address block that hand back almost all of
# what they are given; at twice the share the three paragraphs could legally
# hold 1,599 characters of a page asking for 1,706, and the target was
# unreachable on both of the candidate's own letters. Found on 2026-09-10 when
# the target became a rule; before that nothing measured the shortfall, so
# nothing could notice.
SHARE_FACTOR = 2
LETTER_SHARE_FACTOR = 3


def slot_budgets(
    estimate: Estimate,
    slots: list[Slot],
    *,
    ceiling: int = SLOT_CEILING,
    share_factor: int = SHARE_FACTOR,
) -> dict[str, int]:
    """The character cap for each blank, measured off the room left on the page.

    Deliberately generous per slot and firm in aggregate: `page_problems` is the
    rule that actually holds, and a per-slot cap exists so one runaway fill is
    reported against the blank that caused it rather than as a mysterious
    "your document is too long".

    `ceiling` and `share_factor` are what the two kinds of base document
    disagree about, and only those: `SLOT_CEILING` with `SHARE_FACTOR` for a
    résumé, `LETTER_SLOT_CEILING` with `LETTER_SHARE_FACTOR` for a cover letter.
    `services/base_documents.py` holds which is which. Both differ for the same
    underlying reason — a letter's blanks are three paragraphs among five short
    ones, a CV's are two lists among two short ones — so a number calibrated on
    one document is wrong on the other in both places.

    Pass only the blanks the *model* is being asked for. A letter's date and
    employer are filled by Python before this is called and are already in the
    document the estimate was taken on, so counting them here would divide the
    remaining room by blanks that have no more room to ask for.
    """
    if not slots:
        return {}
    share = share_factor * estimate.slack_chars / len(slots)
    allowance = int(max(SLOT_FLOOR, min(ceiling, share)))
    return {slot.key: len(slot.token) + allowance for slot in slots}


# How much of the room left on the page the fills are expected to actually use.
# Measured on the runs that prompted it: on 2026-09-10 the four most recent
# résumés had used 97%, 91%, 88% and 57% of their room, and the one cover letter
# produced since the letter started being filled the same way had used 52% — it
# stopped ten lines short of the bottom of the page. Three of those five were
# fine and two were not, and 0.8 is the line between them.
#
# The remaining 20% is not waste, it is the band the two gates need between
# them: `page_problems` refuses above the room, this refuses below 80% of it,
# and a model told to land in between has somewhere to land. On a CV that band
# is about 54 characters — one item off a list — and on a cover letter about
# 440, which is why the letter is where this bites and the CV is where the
# *other* gate does. Exactly the mirror of `SLOT_CEILING` and
# `LETTER_SLOT_CEILING`.
FILL_TARGET = 0.8

# ...and nothing is ever asked for on a page with less than this much left.
# "You left room unused" is noise on a document that has under a line of it, and
# a gate that fires there is a gate arguing with `page_problems` over a rounding
# error.
SHORT_FLOOR_LINES = 1.0


def total_target(estimate: Estimate, slots: list[Slot] | None = None) -> int:
    """How many characters all the fills together are expected to add.

    The counterpart to `Estimate.slack_chars`, which is the cap. Both go into
    the prompt, because a model given only a cap treats it as a cliff to stay
    well clear of — which is exactly what happened: letters arriving at 84% of a
    page with ten lines of white space under them, and coursework lists stopping
    at three items on a CV with room for five. The room on the page belongs to
    the candidate, and a blank left half-used is a qualification not shown.

    **Zero when this document's blanks could not fill this page even at their
    caps**, and that case is not a corner. `slot_budgets` caps a blank at
    `SLOT_CEILING` or `LETTER_SLOT_CEILING` however much room there is, because
    a CV blank is a title or a list and no amount of free page makes it a
    chapter. So a document with two short blanks on a mostly empty page has more
    page than it has anywhere to put — and asking it to fill that page would be
    asking for a 400-character job title, forever, in a loop with no winning
    move. The page is the candidate's to lay out; this only ever asks the model
    to use room the blanks it was given can genuinely take.

    Both of the candidate's own documents clear that easily — four blanks priced
    at 134 each against 268 characters of room, eight at 533 against 2,133 — so
    what is being guarded is other people's documents, and the shape of the
    test fixtures, which is where it was caught.
    """
    room = int(FILL_TARGET * estimate.slack_chars)
    if slots is None:
        return room
    allowed = sum(max(0, slot.budget - len(slot.token)) for slot in slots)
    return room if allowed >= room else 0


def added_chars(slots: list[Slot], fills: Mapping[str, str]) -> int:
    """Net characters these fills add to the page — the text in, the tokens out.

    Pass the same slots `slot_budgets` was given: the blanks Python answered are
    already in the document the room was measured on, so counting them here
    would credit the model with the employer's name.
    """
    return sum(len(fills.get(slot.key, "")) - len(slot.token) for slot in slots)


def required_room(slots: list[Slot]) -> int:
    """The characters a document must have free before it can be tailored at all.

    Every blank has to be able to hold `SLOT_FLOOR` characters — below that
    there is no room to write a job title, let alone a list of courses. A base
    résumé with less free space than this is refused at `POST …/generate` rather
    than sent into a revision loop it cannot win, and the candidate is told at
    upload so it never gets that far.
    """
    return sum(max(0, SLOT_FLOOR - len(slot.token)) for slot in slots)


def allowance(base: Estimate) -> float:
    """The height a filled document may reach, in points.

    Normally the page's own capacity. But when Word itself recorded the base
    document as one page and this module measured it at slightly more, Word is
    right and this is wrong — the widths here are a table, not a rasteriser —
    and holding the fills to a capacity the candidate's untouched file already
    "exceeds" would reject a no-op. So a Word-certified single page raises the
    ceiling to whatever the base measured, and the fills are then priced against
    the room left above it, which is the honest remainder: zero.
    """
    if base.word_pages == 1:
        return max(base.capacity, base.height)
    return base.capacity


def page_problems(
    data: bytes,
    blocks: list[Block],
    slots: list[Slot],
    fills: Mapping[str, str],
    *,
    noun: str = "résumé",
) -> list[str]:
    """Whether the filled document still fits on one page, and by how much it does not.

    Builds the document the candidate would actually send and measures *that*,
    rather than measuring a text substitution: a fill lands inside one of their
    runs and inherits its size and weight, and only the real file knows which.
    It costs one python-docx round trip per gate check, which is nothing next to
    the model call it is gating.

    Re-measuring is also why the per-slot budgets are not the rule: they are a
    per-blank cap, and the page is the sum. The message quotes lines rather than
    points — "about two lines too long" is something a model can act on, and
    "43.7 points over" is not.
    """
    from .docx_template import apply_fills

    try:
        filled, _ = apply_fills(data, blocks, slots, fills)
    except Exception:  # pragma: no cover - a document python-docx cannot rewrite
        logger.warning("Could not build the filled %s to measure it", noun, exc_info=True)
        return []
    ceiling = allowance(measure(data))
    estimate = measure(filled)
    if estimate.page_break:
        return [
            "The base document contains a manual page break, so it is more than one page "
            "however it is filled. That is a problem with the uploaded file, not with the fills."
        ]
    if estimate.height <= ceiling:
        return []

    over = (estimate.height - ceiling) / estimate.line_height
    longest = sorted(
        ((len(text), key) for key, text in fills.items() if text),
        reverse=True,
    )[:3]
    named = ", ".join(f"{key} ({length} characters)" for length, key in longest)
    return [
        f"The filled {noun} runs onto a second page — about {over:.1f} line(s) too long, and it "
        "must never be more than one page. Shorten the longest fills: "
        f"{named or '(none)'}. Cutting one item, or one sentence, is usually enough."
    ]


def short_problems(
    estimate: Estimate,
    slots: list[Slot],
    fills: Mapping[str, str],
    *,
    noun: str = "résumé",
    optional: set[str] | None = None,
) -> list[str]:
    """Whether the fills left most of the page empty, and by how much.

    The mirror of `page_problems`, and it exists because for a year only one
    half of "one page" was enforced. A gate that can only say *too long* teaches
    a model one lesson — stay well clear of the number — and it learns it: the
    cover letter that prompted this used 1,133 of the 2,174 characters it was
    offered and stopped ten lines above the bottom of the page, and a résumé the
    same day listed six skills where the budget had room for nine. Neither was
    refused by anything, because neither was wrong in the direction anyone was
    checking.

    Unlike `page_problems` this needs no python-docx round trip: it is
    arithmetic on the base estimate, which the `Plan` is already holding. The
    room the page has is `slack_chars`; the room the fills used is
    `added_chars`; the shortfall is the difference. Characters rather than the
    filled document's own height because a page's height moves in whole lines —
    the résumé above put 153 characters into lines that had space for them and
    came out at exactly the percentage it went in at, which is a real gain the
    line count cannot see.

    `optional` is the letter's address block, for the same reason
    `check_fills` takes it: a street nobody published is correctly left empty,
    and naming an empty blank as one to lengthen would ask for the one thing
    this system must never produce.
    """
    if estimate.slack_lines < SHORT_FLOOR_LINES or not slots:
        return []
    room = estimate.slack_chars
    target = total_target(estimate, slots)
    added = added_chars(slots, fills)
    # Nothing to ask for on a document whose blanks could not fill this page at
    # their caps — see `total_target`. Nor, obviously, on one already at target.
    if target <= 0 or added >= target:
        return []

    per_line = room / estimate.slack_lines if estimate.slack_lines else 0.0
    empty = (room - added) / per_line if per_line > 0 else 0.0
    skip = optional or set()
    longest = sorted(
        (
            (len(fills.get(slot.key, "")), slot.key, slot.budget)
            for slot in slots
            if slot.key not in skip and fills.get(slot.key)
        ),
        reverse=True,
    )[:3]
    named = ", ".join(f"{key} ({length} of {budget})" for length, key, budget in longest)
    return [
        f"The filled {noun} uses only {added} of the {room} characters this page has room for, "
        f"and leaves about {empty:.1f} line(s) of it empty. That room is the candidate's — they "
        "cut these blanks to use it — and an employer reads the whole page: aim for about "
        f"{target} characters across all the fills. Lengthen the longest ones, which are the "
        f"ones with something more to say: {named or '(none)'}. Say more with the room; do not "
        "pad what is already there."
    ]


def describe(estimate: Estimate, *, noun: str = "résumé") -> str:
    """One sentence about a base document, for the upload response and the Account page.

    The candidate is shown the number rather than a verdict, because the number
    is an estimate and they are holding the actual file: "about 96% of a page"
    is something they can agree or disagree with, where "it fits" is a claim
    this module is not entitled to make on its own.
    """
    if estimate.page_break:
        return "This document has a manual page break in it, so it is longer than one page."
    if estimate.word_pages > 1:
        return (
            f"Word recorded this document as {estimate.word_pages} pages. The filled {noun} "
            "has to be one page — shorten it and upload it again."
        )
    percent = f"{estimate.fraction:.0%}"
    if not estimate.fits:
        return (
            f"This document already fills about {percent} of a page before anything is added, so "
            "there is no room to fill the blanks. Free up a line or two and upload it again."
        )
    return (
        f"About {percent} of one page, with room for roughly {estimate.slack_chars} more "
        "characters once the blanks are filled."
    )
