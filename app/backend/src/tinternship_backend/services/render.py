"""Rendering an application artifact: the preview, and the .docx that is sent.

**This module no longer produces either document that gets sent.** It renders
the ones produced before it stopped, and it names the files.

A *filled* résumé or cover letter is not built here at all. The candidate
uploads their own Word CV and their own Word letter, one of each per language,
and an applying run returns the text for the blanks they left;
`services/docx_template.py` writes those into a copy of their file and that file
— theirs, with its own fonts, tab stops and spacing — is what is exported. This
module only supplies the filename it travels under.

A *legacy* artifact is one generated before that changed: a résumé written into
the fixed Harvard OCS template (until 2026-08-28), or a cover letter written
into this module's own letter layout (until 2026-09-09). Those rows are never
migrated, so `legacy_resume_to_html` and `legacy_cover_letter_to_html` still
render them for the preview and the version history. They are readers, not
producers: the estimator, the one-page trimming ladder and the Harvard .docx
writer that used to live here went with the design that needed them, because
nothing can overflow a page the model is no longer laying out.

**Everything exports as .docx.** The PDF path and its WeasyPrint dependency were
removed with the same change: the deliverable is a Word file the candidate can
open and adjust before sending, a PDF made from someone else's HTML never was
their document, and dropping it took Pango, Cairo, the Carlito font package and
the `DYLD_FALLBACK_LIBRARY_PATH` dance out of the image and the Makefile with
it.
"""

from __future__ import annotations

import html
import io
import logging
import re
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import docx_template
from .docx_template import DOCX_MIME
from .job_titles import clean_job_title, strip_gender_indicators
from .languages import DEFAULT_LANGUAGE, normalise_language

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The template's geometry, in the units the source .docx uses (inches/points)
# ---------------------------------------------------------------------------

PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
MARGIN_TOP_IN = 0.89
MARGIN_SIDE_IN = 0.42
MARGIN_BOTTOM_IN = 0.19

CONTENT_WIDTH_IN = PAGE_WIDTH_IN - 2 * MARGIN_SIDE_IN
CONTENT_HEIGHT_PT = (PAGE_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN) * 72

BASE_FONT_PT = 11.0
BULLET_INDENT_IN = 0.583  # w:ind left=839 twips
BULLET_HANG_IN = 0.25  # w:ind hanging=360 twips

# Calibri's average advance width is a shade under half an em; this is only used
# to guess how many lines a paragraph wraps to, so being a few percent out just
# makes the fit estimate slightly conservative.
_AVG_CHAR_EM = 0.475

# Metric-compatible fallbacks, so a machine without Calibri still paginates the
# same way. Carlito is Calibri's open clone and ships with LibreOffice.
_FONT_STACK = '"Calibri", "Carlito", "Segoe UI", "Helvetica Neue", Arial, sans-serif'

# ---------------------------------------------------------------------------
# Section headings, per language
# ---------------------------------------------------------------------------

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "education": "Education",
        "experience": "Experience",
        "projects": "Projects",
        "leadership": "Leadership & Activities",
        "skills": "Skills & Interests",
        "coursework": "Relevant Coursework",
        "resume": "Résumé",
    },
    "fr": {
        "education": "Formation",
        "experience": "Expérience professionnelle",
        "projects": "Projets",
        "leadership": "Engagements & Activités",
        "skills": "Compétences & Centres d'intérêt",
        "coursework": "Cours suivis",
        "resume": "CV",
    },
}


def labels_for(language: str) -> dict[str, str]:
    return _LABELS[normalise_language(language)]


def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


def _join(parts: list[str], separator: str = " · ") -> str:
    return separator.join(str(p) for p in parts if p)


# ---------------------------------------------------------------------------
# Normalising what the agent produced into template rows
# ---------------------------------------------------------------------------


_MONTHS: dict[str, tuple[str, ...]] = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"),
    "fr": ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
           "sept.", "oct.", "nov.", "déc."),
}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$")


def display_date(value: Any, language: str = DEFAULT_LANGUAGE) -> str:
    """`2025-09` → `Sept 2025` / `sept. 2025`; anything else is left alone.

    The master profile stores whatever the source résumé used, and the Resume
    agent copies dates through verbatim however firmly it is asked not to — so
    the conversion belongs here, where it is a guarantee rather than a request.
    Text the model already wrote in words ("June 2025", "Présent") passes
    through untouched, as does a bare year.
    """
    text = str(value or "").strip()
    match = _ISO_DATE.match(text)
    if not match:
        return text
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return text
    return f"{_MONTHS[normalise_language(language)][month - 1]} {year}"


def _dates(entry: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> str:
    return _join(
        [
            display_date(entry.get("start_date", ""), language),
            display_date(entry.get("end_date", ""), language),
        ],
        " – ",
    )


def _bullets(entry: dict[str, Any]) -> list[str]:
    out = []
    for bullet in entry.get("bullets") or []:
        text = bullet.get("text") if isinstance(bullet, dict) else bullet
        if text:
            out.append(str(text))
    return out


def _entry_rows(entry: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> list[tuple[str, str]]:
    """The template's `bold left … right` rows for one experience-shaped entry.

    Two rows when we have both an organisation and a title (the template's
    Organization/City then Position Title/Dates); one row otherwise, which is
    what projects and one-line activities collapse to.
    """
    organisation = str(entry.get("organisation") or "").strip()
    title = str(entry.get("title") or entry.get("name") or "").strip()
    location = str(entry.get("location") or "").strip()
    dates = _dates(entry, language)

    if organisation and title:
        return [(organisation, location), (title, dates)]
    return [(organisation or title, _join([location, dates]))]


def _education_rows(item: Any, language: str = DEFAULT_LANGUAGE) -> tuple[list[tuple[str, str]], str]:
    """Rows plus the optional coursework line for one education entry.

    Accepts the structured `ResumeEducation` shape and, for artifacts generated
    before that schema existed, a bare string.
    """
    if not isinstance(item, dict):
        return [(str(item), "")], ""

    institution = str(item.get("institution") or "").strip()
    degree = str(item.get("degree") or "").strip()
    location = str(item.get("location") or "").strip()
    dates = _dates(item, language) or display_date(item.get("graduation_date"), language)
    details = str(item.get("details") or "").strip()

    second = _join([degree, details], ". ")
    rows: list[tuple[str, str]] = []
    if institution and second:
        rows = [(institution, location), (second, dates)]
    else:
        rows = [(institution or second, _join([location, dates]))]

    coursework = item.get("coursework") or []
    coursework_line = ", ".join(str(c) for c in coursework if c)
    return rows, coursework_line


def _skill_rows(resume: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for group in resume.get("skills") or []:
        if not isinstance(group, dict):
            rows.append(("", str(group)))
            continue
        heading = str(group.get("heading") or "").strip().rstrip(":")
        entries = ", ".join(str(e) for e in group.get("entries") or [] if e)
        if heading or entries:
            rows.append((f"{heading}:" if heading else "", entries))
    return rows


def _entry_sections(resume: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[dict]]]:
    """The template's experience-shaped sections, in template order."""
    return [
        (labels["experience"], list(resume.get("experiences") or [])),
        (labels["projects"], list(resume.get("projects") or [])),
        (labels["leadership"], list(resume.get("leadership") or [])),
    ]


# ---------------------------------------------------------------------------
# One-page fitting
# ---------------------------------------------------------------------------


def _resume_css() -> str:
    font = BASE_FONT_PT
    return f"""
@page {{
  size: {PAGE_WIDTH_IN}in {PAGE_HEIGHT_IN}in;
  margin: {MARGIN_TOP_IN}in {MARGIN_SIDE_IN}in {MARGIN_BOTTOM_IN}in;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: {_FONT_STACK};
  font-size: {font:.2f}pt;
  line-height: 1.18;
  color: #000;
  margin: 0;
}}
.name {{ text-align: center; font-weight: 700; }}
.contact {{ text-align: center; margin-bottom: 6pt; }}
/* Each item is unbreakable and carries its own separator, so a long contact
   line wraps between items instead of through the middle of a URL. */
.contact span {{ white-space: nowrap; }}
.contact span:not(:last-child)::after {{ content: " \\2022"; }}
h2 {{
  font-size: 1em; font-weight: 700; text-align: center;
  margin: 5pt 0 2pt;
  page-break-after: avoid;
}}
.entry {{ margin-bottom: 4pt; page-break-inside: avoid; }}
.row {{ display: flex; justify-content: space-between; gap: 12pt; }}
.row .left {{ font-weight: 700; }}
.row .right {{ white-space: nowrap; }}
.coursework {{ margin-bottom: 3pt; }}
ul {{ margin: 0; padding: 0; list-style: none; }}
li {{ padding-left: {BULLET_INDENT_IN}in; }}
li::before {{
  content: "\\2022";
  display: inline-block;
  width: {BULLET_HANG_IN}in;
  margin-left: -{BULLET_HANG_IN}in;
}}
""".strip()


def _row_html(left: str, right: str) -> str:
    if not left and not right:
        return ""
    return (
        "<div class='row'>"
        f"<div class='left'>{_esc(left)}</div>"
        f"<div class='right'>{_esc(right)}</div>"
        "</div>"
    )


def legacy_resume_to_html(resume: dict[str, Any]) -> str:
    """A pre-2026-08-28 generated résumé, in the Harvard template it was written for.

    Read-only history. Nothing produces this shape any more — see the module
    docstring — but `ApplicationArtifact` rows are never migrated, so opening an
    application from before the change still has to show what was generated for
    it. Rendered exactly as stored: there is no trimming step behind it any
    more, so a long one simply runs onto a second page, which is the honest
    rendering of an artifact nobody is going to send.
    """
    language = normalise_language(resume.get("language"))
    labels = labels_for(language)
    sections: list[str] = []

    education = list(resume.get("education") or [])
    if education:
        blocks = []
        for item in education:
            rows, coursework = _education_rows(item, language)
            block = "".join(_row_html(left, right) for left, right in rows)
            if coursework:
                block += f"<div class='coursework'>{_esc(labels['coursework'])}: {_esc(coursework)}</div>"
            blocks.append(f"<div class='entry'>{block}</div>")
        sections.append(f"<h2>{_esc(labels['education'])}</h2>{''.join(blocks)}")

    for heading, entries in _entry_sections(resume, labels):
        if not entries:
            continue
        blocks = []
        for entry in entries:
            block = "".join(_row_html(left, right) for left, right in _entry_rows(entry, language))
            bullets = "".join(f"<li>{_esc(text)}</li>" for text in _bullets(entry))
            if bullets:
                block += f"<ul>{bullets}</ul>"
            blocks.append(f"<div class='entry'>{block}</div>")
        sections.append(f"<h2>{_esc(heading)}</h2>{''.join(blocks)}")

    skills = _skill_rows(resume)
    if skills:
        rows = "".join(
            f"<div><b>{_esc(heading)}</b> {_esc(entries)}</div>" for heading, entries in skills
        )
        sections.append(f"<h2>{_esc(labels['skills'])}</h2>{rows}")

    for extra in resume.get("extra_sections") or []:
        items = "".join(f"<li>{_esc(line)}</li>" for line in extra.get("entries") or [] if line)
        if items:
            sections.append(f"<h2>{_esc(extra.get('heading'))}</h2><ul>{items}</ul>")

    contact = " ".join(f"<span>{_esc(item)}</span>" for item in resume.get("contact") or [] if item)
    name = _esc(resume.get("full_name"))

    return f"""<!doctype html>
<html lang="{language}"><head><meta charset="utf-8">
<title>{name or _esc(labels['resume'])} — {_esc(labels['resume'])}</title>
<style>{_resume_css()}</style></head>
<body>
<div class="name">{name}</div>
<div class="contact">{contact}</div>
{''.join(sections)}
</body></html>"""


_LETTER_CSS = f"""
@page {{ size: {PAGE_WIDTH_IN}in {PAGE_HEIGHT_IN}in; margin: 1in 1in; }}
body {{
  font-family: {_FONT_STACK};
  font-size: {BASE_FONT_PT}pt; line-height: 1.35; color: #000; margin: 0;
}}
p {{ margin: 0 0 10pt; }}
.meta {{ margin-bottom: 16pt; }}
""".strip()


# The nine fields a pre-2026-09-09 letter was written in, in reading order, and
# the five of them that are its body. Nothing produces this shape any more, so
# the lists cannot grow — but three functions render it (HTML, .docx, text) and
# a fourth copy of the same order is a fourth chance to get it wrong.
_LEGACY_LETTER_BODY = ("hook", "fit", "evidence", "motivation", "close")
_LEGACY_LETTER_ORDER = ("recipient", "subject", "greeting", *_LEGACY_LETTER_BODY, "signature")


def legacy_cover_letter_to_html(letter: dict[str, Any]) -> str:
    """A pre-2026-09-09 generated letter, in the layout this module gave it.

    Read-only history, exactly like `legacy_resume_to_html`. Nothing produces
    this nine-field shape any more — the letter is the candidate's own .docx
    with its blanks filled — but `ApplicationArtifact` rows are never migrated,
    so opening an application from before the change still shows what was
    generated for it.
    """
    paragraphs = [letter.get(key) for key in _LEGACY_LETTER_BODY]
    body = "".join(f"<p>{_esc(p)}</p>" for p in paragraphs if p)
    meta_bits = [letter.get("recipient"), letter.get("subject")]
    meta = "<br>".join(_esc(bit) for bit in meta_bits if bit)
    return f"""<!doctype html>
<html lang="{normalise_language(letter.get('language'))}"><head><meta charset="utf-8">
<title>Cover letter</title>
<style>{_LETTER_CSS}</style></head>
<body class="letter">
{f"<div class='meta'>{meta}</div>" if meta else ""}
{f"<p>{_esc(letter.get('greeting'))}</p>" if letter.get("greeting") else ""}
{body}
{f"<p>{_esc(letter.get('signature'))}</p>" if letter.get("signature") else ""}
</body></html>"""


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _docx_document():
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Inches, Pt

    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(PAGE_WIDTH_IN)
    section.page_height = Inches(PAGE_HEIGHT_IN)
    section.top_margin = Inches(MARGIN_TOP_IN)
    section.bottom_margin = Inches(MARGIN_BOTTOM_IN)
    section.left_margin = Inches(MARGIN_SIDE_IN)
    section.right_margin = Inches(MARGIN_SIDE_IN)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(BASE_FONT_PT)
    # python-docx's default template puts 8pt after every paragraph, which the
    # template does not have and which alone costs most of a page.
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    return document


def _docx_row(document, left: str, right: str, *, bold_left: bool = True):
    """One `bold left … right` row, the right half on a flush-right tab stop."""
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Inches

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(CONTENT_WIDTH_IN), WD_TAB_ALIGNMENT.RIGHT
    )
    if left:
        paragraph.add_run(left).bold = bold_left
    if right:
        paragraph.add_run("\t" + right)
    return paragraph


def _docx_heading(document, text: str):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(5)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.add_run(text).bold = True
    return paragraph


def _docx_bullet(document, text: str):
    from docx.shared import Inches

    try:
        paragraph = document.add_paragraph(text, style="List Bullet")
    except KeyError:  # a template without the built-in style
        paragraph = document.add_paragraph(f"• {text}")
    paragraph.paragraph_format.left_indent = Inches(BULLET_INDENT_IN)
    paragraph.paragraph_format.first_line_indent = Inches(-BULLET_HANG_IN)
    return paragraph


def legacy_resume_to_docx(resume: dict[str, Any]) -> bytes:
    """A pre-2026-08-28 generated résumé, as .docx.

    The counterpart of `legacy_resume_to_html`, so the Download button on an old
    artifact still hands back a document rather than an error. Nothing produces
    this shape any more, and there is no trimming behind it: a long one runs to
    a second page, which is the honest rendering of a document nobody is going
    to send.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    language = normalise_language(resume.get("language"))
    labels = labels_for(language)
    document = _docx_document()

    name = document.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.add_run(str(resume.get("full_name") or "")).bold = True

    contact = document.add_paragraph()
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact.paragraph_format.space_after = Pt(6)
    contact.add_run(" • ".join(str(item) for item in resume.get("contact") or [] if item))

    education = list(resume.get("education") or [])
    if education:
        _docx_heading(document, labels["education"])
        for item in education:
            rows, coursework = _education_rows(item, language)
            for index, (left, right) in enumerate(rows):
                _docx_row(document, left, right, bold_left=index == 0)
            if coursework:
                document.add_paragraph(f"{labels['coursework']}: {coursework}")

    for heading, entries in _entry_sections(resume, labels):
        if not entries:
            continue
        _docx_heading(document, heading)
        for entry in entries:
            for left, right in _entry_rows(entry, language):
                _docx_row(document, left, right)
            for bullet in _bullets(entry):
                _docx_bullet(document, bullet)

    skills = _skill_rows(resume)
    if skills:
        _docx_heading(document, labels["skills"])
        for heading, entries in skills:
            paragraph = document.add_paragraph()
            if heading:
                paragraph.add_run(f"{heading} ").bold = True
            paragraph.add_run(entries)

    for extra in resume.get("extra_sections") or []:
        entries = [str(line) for line in extra.get("entries") or [] if line]
        if not entries:
            continue
        _docx_heading(document, str(extra.get("heading") or ""))
        for line in entries:
            _docx_bullet(document, line)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()




def legacy_cover_letter_to_docx(letter: dict[str, Any]) -> bytes:
    """The same, as .docx, so the Download button on an old letter still works."""
    from docx import Document
    from docx.shared import Inches, Pt

    document = Document()
    section = document.sections[0]
    section.page_width = Inches(PAGE_WIDTH_IN)
    section.page_height = Inches(PAGE_HEIGHT_IN)
    for attribute in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attribute, Inches(1))
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(BASE_FONT_PT)

    for value in (letter.get("recipient"), letter.get("subject"), letter.get("greeting")):
        if value:
            document.add_paragraph(str(value))
    for key in _LEGACY_LETTER_BODY:
        if letter.get(key):
            document.add_paragraph(str(letter[key]))
    if letter.get("signature"):
        document.add_paragraph(str(letter["signature"]))

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_filled(content: dict[str, Any]) -> bool:
    """Whether an artifact is the candidate's own document filled in, or a legacy one.

    `blocks` is the tell rather than `fills`: a document with no blanks in it
    produces no fills at all, and a legacy artifact never carried the base
    document with it. True for a résumé written after 2026-08-28 and a cover
    letter written after 2026-09-09; false for everything generated before.
    """
    return isinstance(content.get("blocks"), list)


# What the preview calls the document it is showing, per artifact kind.
_NOUNS = {"resume": "résumé", "cover_letter": "cover letter"}


def _filled_lines(content: dict[str, Any]) -> tuple[list[docx_template.Block], dict[int, str]]:
    """A filled document's blocks, and the lines its fills rewrite."""
    blocks = docx_template.blocks_from_payload(content.get("blocks"))
    return blocks, docx_template.filled_lines(
        blocks,
        docx_template.slots_from_payload(content.get("slots")),
        docx_template.fill_map(content),
    )


def render_artifact(kind: str, content: dict[str, Any]) -> str:
    """HTML for the in-app preview."""
    if kind in _NOUNS and is_filled(content):
        blocks, lines = _filled_lines(content)
        return docx_template.preview_html(
            blocks,
            lines,
            title=str(content.get("document_title") or ""),
            noun=_NOUNS[kind],
        )
    if kind == "resume":
        return legacy_resume_to_html(content)
    if kind == "cover_letter":
        return legacy_cover_letter_to_html(content)
    raise ValueError(f"No HTML renderer for artifact kind {kind!r}")


_GREETING_PATTERN = re.compile(
    r"^(?:"
    r"dear\b|"
    r"to\s+whom\s+it\s+may\s+concern\b|"
    r"to\s+the\s+(?:hiring|recruiting|recruitment|talent)\b|"
    r"madame\b|"
    r"monsieur\b|"
    r"mesdames\b|"
    r"messieurs\b|"
    r"cher\b|"
    r"chère\b|"
    r"chers\b|"
    r"chères\b|"
    r"bonjour\b|"
    r"hello\b|"
    r"hi\b|"
    r"hey\b|"
    r"greetings\b"
    r")",
    re.IGNORECASE,
)

_SUBJECT_PATTERN = re.compile(
    r"^(?:objet\b|subject\b|re\b|job\s+reference\b)",
    re.IGNORECASE,
)

_GOODBYE_PATTERN = re.compile(
    r"(?:"
    r"\bveuillez\s+agréer\b|"
    r"\bje\s+vous\s+prie\s+d['’]agréer\b|"
    r"\bveuillez\s+recevoir\b|"
    r"\bje\s+vous\s+prie\s+de\s+recevoir\b|"
    r"\bveuillez\s+croire\b|"
    r"\bagréer[,\s]+(?:madame|monsieur)\b|"
    r"\b(?:bien\s+)?cordialement\b|"
    r"\b(?:salutations\s+distinguées|sincères\s+salutations|meilleures\s+salutations)\b|"
    r"\b(?:avec\s+mes\s+)?salutations\b|"
    r"\bbien\s+à\s+vous\b|"
    r"\bsincèrement\b|"
    r"\bsincerely(?:\s+yours)?\b|"
    r"\byours\s+(?:sincerely|faithfully|truly)\b|"
    r"\b(?:warm(?:est)?|kind(?:est)?|best|with(?: warm| kind| best)?)\s+regards\b|"
    r"^\s*regards[,\s]*$|"
    r"^\s*(?:all\s+the\s+)?best[,\s]*$|"
    r"^\s*warmly[,\s]*$|"
    r"^\s*yours[,\s]*$|"
    r"\brespectfully(?:\s+yours)?\b"
    r")",
    re.IGNORECASE,
)


def _resolve_candidate_name(content: dict[str, Any], candidate_name: str | None = None) -> str:
    if candidate_name and candidate_name.strip():
        return candidate_name.strip()
    if content.get("full_name"):
        return str(content["full_name"]).strip()
    try:
        from .profile_store import profile_as_dict

        name = profile_as_dict().get("full_name")
        if name and str(name).strip():
            return str(name).strip()
    except Exception:
        pass
    return ""


def extract_cover_letter_text(full_text: str, candidate_name: str = "") -> str:
    """Extract the letter's actual body from salutation to sign-off, plus candidate name.

    Application forms (e.g. Workday, Lever, Greenhouse) have a "motivation" or
    "cover letter" textarea expecting the letter itself — starting at the
    greeting ("Cher Monsieur, ...", "Dear Recruiter", "Madame, Monsieur,") down
    to the goodbye ("Sincerely...", "Dans cette perspective, veuillez agréer...").
    Letterhead, contact details, date, recipient address and subject lines belong
    on a document file, not pasted into a form.
    """
    all_lines = full_text.splitlines()

    start_idx: int | None = None
    for idx, line in enumerate(all_lines):
        if _GREETING_PATTERN.search(line.strip()):
            start_idx = idx
            break

    if start_idx is None:
        for idx, line in enumerate(all_lines):
            if _SUBJECT_PATTERN.search(line.strip()):
                for next_idx in range(idx + 1, len(all_lines)):
                    if all_lines[next_idx].strip():
                        start_idx = next_idx
                        break
                break

    if start_idx is None:
        start_idx = 0

    end_idx = len(all_lines)
    for idx in range(len(all_lines) - 1, start_idx - 1, -1):
        if _GOODBYE_PATTERN.search(all_lines[idx].strip()):
            end_idx = idx + 1
            break

    if start_idx >= end_idx:
        start_idx = 0
        end_idx = len(all_lines)

    sliced = [line.rstrip() for line in all_lines[start_idx:end_idx]]
    body = "\n".join(sliced).strip()

    if candidate_name:
        non_empty = [line.strip() for line in body.splitlines() if line.strip()]
        if not (non_empty and non_empty[-1] == candidate_name):
            body = f"{body}\n\n{candidate_name}"

    return body


def artifact_text(
    kind: str,
    content: dict[str, Any],
    *,
    candidate_name: str | None = None,
) -> str:
    """The document as plain text, blanks filled — what the Copy button copies.

    Not the preview's HTML with the tags stripped, and not something the
    frontend assembles from `blocks` and `fills` on its own: which characters a
    filled document ends up with is decided by one slicing rule in
    `docx_template.filled_lines`, whose two awkward cases (a missing fill keeps
    its token, an *empty* fill writes nothing) are exactly the ones a second
    implementation would get wrong.

    For a **cover letter**, the Copy button copies only the actual content —
    from the greeting ("Cher Monsieur, ...", "Dear Recruiter", "Madame, Monsieur,")
    until the goodbye ("Sincerely...", "Dans cette perspective, veuillez agréer..."),
    with the candidate's name appended at the end. Letterhead, date, recipient
    address, and subject line are omitted so the text is immediately pasteable
    into application textareas.

    A **legacy résumé** has no text form here on purpose: only the letter is
    ever pasted into a form, and the pre-2026-08-28 résumé shape is a tree of
    sections and entries whose flattening would be a layout decision with no
    reader to check it against.
    """
    resolved_candidate = _resolve_candidate_name(content, candidate_name)
    if kind in _NOUNS and is_filled(content):
        blocks, lines = _filled_lines(content)
        raw_text = docx_template.tailored_text(blocks, lines)
        if kind == "cover_letter":
            return extract_cover_letter_text(raw_text, resolved_candidate)
        return raw_text
    if kind == "cover_letter":
        keys = ("greeting", *_LEGACY_LETTER_BODY)
        paragraphs = [
            text
            for key in keys
            if (text := str(content.get(key) or "").strip())
        ]
        sig = str(content.get("signature") or "").strip() or resolved_candidate
        if sig:
            paragraphs.append(sig)
        return "\n\n".join(paragraphs)
    raise ValueError(f"No text form for artifact kind {kind!r}")


# What each artifact kind is called at the top of its filename, per language.
# English for an English package, French for a French one — the recruiter who
# opens the attachment reads the filename before the document.
DOCUMENT_NAMES = {
    "en": {"resume": "Resume", "cover_letter": "Cover_Letter", "follow_up": "Follow_Up"},
    "fr": {"resume": "CV", "cover_letter": "Lettre_de_Motivation", "follow_up": "Relance"},
}

# The filename budget, and how it is spent.
#
# `export_artifact` truncates the whole stem at 80 characters and `flows` then
# appends `_v<n>` for the on-disk copy, so the stem itself has to come in under
# that on its own — a cut applied to the join would eat the version suffix and
# let two versions overwrite each other. Each part therefore gets its own cap
# and the total is trimmed by shortening the *least* identifying part first: the
# role, then the employer. The candidate's name is never trimmed to fit, because
# it is the only part the recruiter needs to have.
MAX_STEM = 68
_MAX_PART = {"name": 34, "company": 28, "title": 36}


def _name_part(value: Any, limit: int) -> str:
    """One `Snake_Cased` segment of a filename.

    Accents and non-Latin letters survive (`isalnum()` is Unicode-aware, and
    "Martin" is not the interesting case — "Müller" is); punctuation, slashes
    and gender indicators like `(H/F)` or `(F/H)` a posting puts in its title do not.
    Trimmed on a word boundary so a cut never lands mid-word, and never left empty
    when the very first word is already over the limit — a hard cut beats no name at all.
    """
    raw_str = strip_gender_indicators(str(value or ""))
    cleaned = "".join(c if c.isalnum() else " " for c in raw_str)
    words: list[str] = []
    length = 0
    for word in cleaned.split():
        # +1 for the underscore that joins it to what came before.
        cost = len(word) + (1 if words else 0)
        if words and length + cost > limit:
            break
        words.append(word)
        length += cost
    if not words:
        return ""
    joined = "_".join(words)
    return joined if len(joined) <= limit else joined[:limit]


def document_stem(
    kind: str,
    *,
    candidate: str,
    company: str,
    title: str,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """The filename a recruiter should see: `Resume_Alex_Martin_Acme_Data_Intern`.

    This is not cosmetic. Many ATS show the screener the filename before they
    show them anything else, and several file the attachment under it — so
    `resume-app12-v3.pdf`, which is what this used to produce, arrives as an
    anonymous document in a folder of hundreds. The candidate's own name is the
    part that has to be there; the employer and the role are what make it
    findable again three weeks later on both sides.

    Every part is optional in practice — a posting with no company name still
    has to export — so empty segments are dropped rather than leaving `__`.
    """
    kind_label = DOCUMENT_NAMES.get(normalise_language(language), DOCUMENT_NAMES["en"]).get(
        kind, _name_part(kind.replace("_", " ").title(), 24)
    )
    name = _name_part(candidate, _MAX_PART["name"])
    company_part = _name_part(company, _MAX_PART["company"])
    cleaned_title = clean_job_title(title, language=language)
    title_part = _name_part(cleaned_title, _MAX_PART["title"])

    def joined() -> str:
        return "_".join(part for part in (kind_label, name, company_part, title_part) if part)

    # Shorten the role first, then the employer. Both can vanish entirely; the
    # kind and the candidate's name cannot.
    while len(joined()) > MAX_STEM and title_part:
        title_part = _name_part(title_part, max(0, len(title_part) - 8))
    while len(joined()) > MAX_STEM and company_part:
        company_part = _name_part(company_part, max(0, len(company_part) - 8))
    return joined()[:MAX_STEM]


def artifact_path(stem: str) -> Path:
    """Where an export lands, with the stem sanitised to something a disk accepts."""
    safe = "".join(c for c in stem if c.isalnum() or c in "-_ ").strip().replace(" ", "-")[:80]
    return get_settings().artifacts_path / f"{safe}.docx"


def export_artifact(kind: str, content: dict[str, Any], *, stem: str) -> tuple[Path, str]:
    """Write a **legacy** artifact to disk as .docx. Returns (path, mime_type).

    A filled document is not written here — it is the candidate's own file with
    their blanks completed, which needs the file, so `flows.export_artifact_file`
    handles it. This covers only the artifacts generated before each kind moved
    to that design, both of which are laid out from their stored JSON.

    Everything is .docx now. Until 2026-08-28 this produced a PDF when WeasyPrint
    could load and silently fell back to .docx when it could not, which meant the
    format of the document an employer received depended on whether Pango
    happened to be installed on the machine that ran the export.
    """
    if kind == "resume":
        data = legacy_resume_to_docx(content)
    else:
        data = legacy_cover_letter_to_docx(content)
    path = artifact_path(stem)
    path.write_bytes(data)
    return path, DOCX_MIME
