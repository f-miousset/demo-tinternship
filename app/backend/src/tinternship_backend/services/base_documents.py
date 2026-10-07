"""The .docx documents the candidate writes themselves — two kinds, one file per language.

These are not "sources that contribute facts to a profile". They are the
documents an employer receives. An applying run opens the file for the chosen
language, fills the blanks the candidate left in it, and saves it back — see
[docx_template.py](docx_template.py) for how, and `documentation/applying.md`
for why that replaced generating a document from scratch.

Two kinds live here, and they work the same way on purpose:

* the **résumé** (`RESUME`), since 2026-08-28;
* the **cover letter** (`COVER_LETTER`), since 2026-09-09. Until then the letter
  was written from scratch into a renderer's own layout, which had every problem
  the generated résumé had: the document was never the candidate's, and a model
  asked for eight hundred words of prose drifts out of the language it was asked
  for. Their letterhead, their address block, their sign-off and their two
  languages are now the file, and a run fills the paragraphs.

Consequences worth stating once, because the rest of the codebase leans on them:

* **All four are mandatory.** `services/onboarding.py` will not call the account
  set up without them, exactly like the profile, the brief and the playbook — an
  applying run in French with no French base document has nothing to produce.
* **One row per (kind, language), replaced not accumulated.** Uploading a new
  French CV removes the old row and deletes the old file. Every other
  `ProfileSource` kind accumulates, because those are evidence being merged;
  there is only ever one current French résumé.
* **`.docx` only.** Not a convenience limit: the whole design is editing the
  candidate's own file in place, and a PDF cannot be edited in place without
  becoming a different document — which is the thing this replaced.
* **The page is measured, not assumed, and in both directions.** `plan()`
  prices the blanks against the room left on the candidate's own page
  (`page_fit`), because "never more than one page" is their rule and a CV that
  already fills the page has nowhere to put a job title. A letter has more room
  than a CV, so its blanks are priced with a larger ceiling and a larger share
  of the page — three paragraphs, not four words — and since 2026-09-10 the
  page also has a `target`, because a letter that used half of it was refused by
  nothing.
* **The résumé seeds the master profile too.** The same upload is extracted like
  any other import, so the Matcher, the Interrogator and the Interview Coach
  still have structured facts to work from. The letter is *not*: it is a
  letterhead and three blanks, and everything else in it — the availability
  sentence, the sign-off — is already in the profile from the CV. Extracting it
  would spend a model call to learn nothing.
* **Some blanks are not the model's.** A letter's date and the employer's name
  are a fact about the clock and a column on the posting's row; Python fills
  them and the agent is never shown them. See
  [letter_fields.py](letter_fields.py).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlmodel import select

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import ProfileSource, ProfileSourceKind
from . import docx_template, language_check, page_fit
from .languages import SUPPORTED_LANGUAGES, normalise_language

logger = logging.getLogger(__name__)

# A .docx is a ZIP; anything else is rejected before python-docx is asked to
# guess. `PK\x03\x04` is the local file header every ZIP starts with.
_ZIP_MAGIC = b"PK\x03\x04"

# The two kinds, spelled the way `ArtifactKind` spells them, so one string names
# the base document, the artifact a run produces from it and the track that
# produced it. One vocabulary rather than three.
RESUME = "resume"
COVER_LETTER = "cover_letter"


class BaseDocumentError(ValueError):
    """The uploaded file cannot serve as a base document, and why."""


@dataclass(frozen=True)
class Kind:
    """What differs between the résumé and the cover letter. Nothing else does."""

    key: str
    source_kind: ProfileSourceKind
    # For every message the candidate and the agent read.
    noun: str
    # The stored filename's prefix, so the uploads directory says what each file is.
    prefix: str
    # The most characters one blank may be filled with, whatever the room says.
    # A CV blank is a title or a list; a letter blank is a paragraph.
    ceiling: int
    # How many equal shares of the free page one blank may take. Higher where
    # more of the document's blanks hand their share back unused — see
    # `page_fit.LETTER_SHARE_FACTOR`.
    share: int
    # Whether the upload is also read by the profile extractor.
    extracted: bool
    # What the candidate should leave blanks for, in the upload box's words.
    blanks_hint: str


KINDS: dict[str, Kind] = {
    RESUME: Kind(
        key=RESUME,
        source_kind=ProfileSourceKind.BASE_RESUME,
        noun="résumé",
        prefix="base-resume",
        ceiling=page_fit.SLOT_CEILING,
        share=page_fit.SHARE_FACTOR,
        extracted=True,
        blanks_hint=(
            "Leave blanks for the things that change per application — the role, the "
            "employer, the coursework, the skills — and write the rest yourself."
        ),
    ),
    COVER_LETTER: Kind(
        key=COVER_LETTER,
        source_kind=ProfileSourceKind.BASE_COVER_LETTER,
        noun="cover letter",
        prefix="base-letter",
        ceiling=page_fit.LETTER_SLOT_CEILING,
        share=page_fit.LETTER_SHARE_FACTOR,
        extracted=False,
        blanks_hint=(
            "Leave blanks for the paragraphs and for the address block — the opening, "
            "the middle and the closing paragraph, the employer, the team, the date — "
            "and write your letterhead, your salutation and your sign-off yourself."
        ),
    ),
}


def kind_of(kind: str) -> Kind:
    """The descriptor for one kind, or a `ValueError` naming the two that exist."""
    try:
        return KINDS[kind]
    except KeyError:
        raise ValueError(
            f"Unknown base document kind {kind!r}. Expected one of {', '.join(KINDS)}."
        ) from None


def is_base_document(filename: str) -> bool:
    return filename.lower().endswith(".docx")


def validate(kind: str, data: bytes) -> list[docx_template.Block]:
    """Open the upload as a Word document and return its blocks, or explain why not.

    Everything that would make the document unusable is caught here rather than
    at generation time, months later, in the middle of a stream: the candidate is
    standing in front of the upload box now.

    What it does **not** refuse is a document with no room left on its page. That
    is measured (`page_fit`) and reported back with the upload so the candidate
    can decide, because the measurement is an estimate and they are holding the
    file: refusing their CV outright on the strength of a width table would be
    claiming more than this can know. `plan()` is where a document with no room
    stops a run.
    """
    descriptor = kind_of(kind)
    if not data.startswith(_ZIP_MAGIC):
        raise BaseDocumentError(
            "That is not a Word .docx file. If it is a .doc or a PDF, open it in Word or "
            f"LibreOffice and save it as .docx — the {descriptor.noun} has to be editable "
            "in place."
        )
    try:
        blocks = docx_template.read_blocks(data)
    except Exception as exc:  # python-docx raises a variety of things
        logger.warning("Could not read an uploaded base %s", descriptor.noun, exc_info=True)
        raise BaseDocumentError(f"That .docx could not be opened: {exc}") from exc

    if not any(block.text.strip() for block in blocks):
        raise BaseDocumentError(
            f"That document has no text in it. If your {descriptor.noun} is one big image or "
            "a text box, there are no blanks to fill — export a version with real text."
        )
    if len(blocks) > docx_template.MAX_BLOCKS:
        raise BaseDocumentError(
            f"That document has {len(blocks)} paragraphs and the limit is "
            f"{docx_template.MAX_BLOCKS}. A {descriptor.noun} of that size is not what this "
            "is for."
        )
    placeholders = sum(len(block.placeholders) for block in blocks)
    if placeholders > docx_template.MAX_SLOTS:
        raise BaseDocumentError(
            f"That document has {placeholders} placeholders and the limit is "
            f"{docx_template.MAX_SLOTS}. {descriptor.blanks_hint}"
        )
    return blocks


def _slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", folded).strip("-_.")[:60] or "document"


def stored_path(kind: str, language: str, filename: str):
    """Where a base document lives on disk: one predictable name per kind and language."""
    settings = get_settings()
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    prefix = kind_of(kind).prefix
    return settings.uploads_path / f"{prefix}-{normalise_language(language)}-{_slug(filename)}"


def get(kind: str, language: str) -> ProfileSource | None:
    """The current base document row for one kind and language, if there is one."""
    wanted = normalise_language(language)
    source_kind = kind_of(kind).source_kind
    with session_scope() as session:
        row = session.exec(
            select(ProfileSource)
            .where(ProfileSource.kind == source_kind)
            .where(ProfileSource.language == wanted)
            .order_by(ProfileSource.created_at.desc())
        ).first()
        if row is not None:
            session.expunge(row)
        return row


def read(kind: str, language: str) -> bytes:
    """The base document's bytes, or a message saying which upload is missing."""
    descriptor = kind_of(kind)
    row = get(kind, language)
    language = normalise_language(language)
    if row is None:
        raise BaseDocumentError(
            f"There is no base {descriptor.noun} for {language} yet. Upload your own Word "
            f"{descriptor.noun} in that language in the Profile section of the Account page — "
            "it is the document that gets filled in and sent."
        )
    path = resolved_path(row)
    if path is None:
        raise BaseDocumentError(
            f"The {language} base {descriptor.noun} is recorded but its file is gone from "
            f"disk ({row.file_path}). Upload it again."
        )
    return path.read_bytes()


def resolved_path(source: ProfileSource):
    """The stored file, checked to be inside the uploads directory before it is read.

    Same reasoning as `api/profile.py::_stored_file`: the path comes from one of
    our own rows, but a row is data, and reading whatever path it happens to
    name would turn this into a file-read primitive.
    """
    if not source.file_path:
        return None
    path = Path(source.file_path).resolve()
    if not path.is_relative_to(get_settings().uploads_path.resolve()) or not path.is_file():
        return None
    return path


def blocks(kind: str, language: str) -> list[docx_template.Block]:
    return docx_template.read_blocks(read(kind, language))


@dataclass(frozen=True)
class Plan:
    """One base document, read once, with everything a run needs to fill it.

    Read once and passed down on purpose: the flow reads the file, hands the
    same `Plan` to the agent, the gate, the Critic and the export, and so a run
    cannot straddle two versions of a document the candidate happens to replace
    while it is going.

    `auto` is the part of the answer that was never a question. A cover letter's
    date and the employer's name are the clock and a column on the posting's
    row, so Python fills them before the agent is asked anything — see
    [letter_fields.py](letter_fields.py). They are ordinary fills from every
    other angle: they are checked, applied and stored exactly like the model's,
    which is what keeps the export a pure function of the artifact and the file.
    """

    kind: str
    language: str
    data: bytes
    blocks: list[docx_template.Block]
    # Every blank in the document, in reading order. The ones the model is asked
    # for carry a budget; the ones Python already answered do not need one.
    slots: list[docx_template.Slot]
    # The document with `auto` applied, which is what the room was measured on.
    estimate: page_fit.Estimate
    auto: dict[str, str] = field(default_factory=dict)

    @property
    def noun(self) -> str:
        return kind_of(self.kind).noun

    @property
    def open(self) -> list[docx_template.Slot]:
        """The blanks the model is asked to fill — every one Python did not."""
        return [slot for slot in self.slots if slot.key not in self.auto]

    @property
    def room(self) -> int:
        """Characters of free space on the page, beyond the blanks themselves."""
        return self.estimate.slack_chars

    @property
    def target(self) -> int:
        """Characters the fills are expected to use of it — `room` is the cap.

        Both are told to the model and both are checked afterwards. A cap on its
        own is read as a cliff: the first letter filled this way used half its
        page. See `page_fit.FILL_TARGET`.
        """
        return page_fit.total_target(self.estimate, self.open)

    @property
    def needed(self) -> int:
        """The least free space this document's open blanks could be filled with."""
        return page_fit.required_room(self.open)

    @property
    def usable(self) -> bool:
        return not self.open or self.room >= self.needed

    @property
    def complaint(self) -> str:
        """Why this document cannot be filled in, in words for the candidate."""
        if self.usable:
            return ""
        return (
            f"Your {self.language.upper()} {self.noun} already fills about "
            f"{self.estimate.fraction:.0%} of its page, which leaves room for about "
            f"{self.room} more characters — and its {len(self.open)} blank(s) need at least "
            f"{self.needed} to be filled with anything meaningful. A tailored document has to "
            "stay on one page, so free up a line or two in the Profile section and upload it "
            "again."
        )


def plan(
    kind: str,
    language: str,
    *,
    known: Callable[[list[docx_template.Slot]], Mapping[str, str]] | None = None,
) -> Plan:
    """Everything one applying run needs to know about the base document.

    `known` is the hook the cover letter uses: given the blanks, it answers the
    ones that are records rather than writing — today's date, the employer's
    name as the row spells it. Those are applied to the document *before* it is
    measured, so the room the model is offered is the room actually left after
    them, and the listing it reads shows the employer's real name where the
    placeholder was.
    """
    descriptor = kind_of(kind)
    data = read(kind, language)
    document = docx_template.read_blocks(data)
    slots = docx_template.find_slots(document)
    auto = dict(known(slots)) if known else {}

    measured = data
    if auto:
        try:
            measured, _ = docx_template.apply_fills(data, document, slots, auto)
        except Exception:  # pragma: no cover - a document python-docx cannot rewrite
            logger.warning("Could not apply the known fills before measuring", exc_info=True)
    estimate = page_fit.measure(measured)

    budgets = page_fit.slot_budgets(
        estimate,
        [slot for slot in slots if slot.key not in auto],
        ceiling=descriptor.ceiling,
        share_factor=descriptor.share,
    )
    return Plan(
        kind=descriptor.key,
        language=normalise_language(language),
        data=data,
        blocks=document,
        slots=docx_template.with_budgets(slots, budgets),
        estimate=estimate,
        auto=auto,
    )


def replace(kind: str, language: str, *, label: str, file_path: str) -> ProfileSource:
    """Record a new base document, retiring the previous one for that kind and language.

    The old file is deleted rather than orphaned: it is a copy of the
    candidate's own document, and the Account page lists exactly what is on disk.

    The two paths are compared **resolved**, and that is load-bearing rather
    than tidy. `stored_path` builds a path under the uploads directory as
    configured, while `resolved_path` calls `.resolve()`; on macOS the data
    directory usually sits under `/var`, which is a symlink to `/private/var`,
    so the same file has two spellings. Comparing the strings as given deleted
    the replacement that had just been written whenever the new upload happened
    to carry the same filename as the old one.
    """
    wanted = normalise_language(language)
    source_kind = kind_of(kind).source_kind
    incoming = Path(file_path).resolve()
    with session_scope() as session:
        previous = session.exec(
            select(ProfileSource)
            .where(ProfileSource.kind == source_kind)
            .where(ProfileSource.language == wanted)
        ).all()
        for row in previous:
            old = resolved_path(row)
            if old is not None and old != incoming:
                try:
                    old.unlink()
                except OSError:
                    logger.warning("Could not delete the replaced base document %s", old)
            session.delete(row)

        source = ProfileSource(
            kind=source_kind,
            language=wanted,
            label=label,
            file_path=file_path,
            status="pending",
        )
        session.add(source)
        session.flush()
        session.refresh(source)
        session.expunge(source)
        return source


def status(kind: str) -> dict[str, Any]:
    """Which languages have this document, for `/api/config` and the Account page."""
    present: dict[str, Any] = {}
    for language in SUPPORTED_LANGUAGES:
        row = get(kind, language)
        present[language] = (
            None
            if row is None
            else {
                "id": row.id,
                "label": row.label,
                "status": row.status,
                "error": row.error,
                "on_disk": resolved_path(row) is not None,
                "created_at": row.created_at.isoformat(),
                **_fit(kind, row),
            }
        )
    return present


def _fit(kind: str, row: ProfileSource) -> dict[str, Any]:
    """How full the page is and how many blanks it has, for the Account page.

    Best-effort: a document that has become unreadable since it was uploaded
    still has to show up in the list, with its other details, rather than taking
    the whole Account page down with it.

    Measured on the document as uploaded, blanks and all — the fills that will
    land in them belong to a posting nobody has chosen yet, so the honest figure
    here is the one about the file the candidate is holding.
    """
    empty = {"placeholders": 0, "page": "", "room": 0, "crowded": False, "language_warning": ""}
    path = resolved_path(row)
    if path is None:
        return empty
    try:
        data = path.read_bytes()
        document = docx_template.read_blocks(data)
        slots = docx_template.find_slots(document)
        estimate = page_fit.measure(data)
    except Exception:
        logger.warning("Could not measure the base document %s", path, exc_info=True)
        return empty
    return {
        "placeholders": len(slots),
        "page": page_fit.describe(estimate, noun=kind_of(kind).noun),
        "room": estimate.slack_chars,
        "crowded": bool(slots) and estimate.slack_chars < page_fit.required_room(slots),
        "language_warning": language_warning(kind, document, row.language),
    }


def language_warning(kind: str, document: list[docx_template.Block], language: str) -> str:
    """Whether the candidate uploaded, say, their English CV under French.

    Reported to *them*, never used to fail a run. The tailoring only writes into
    the blanks, so the language of the rest of the page is not something any
    agent can fix — refusing every French application because their French CV
    carries an English sentence would be punishing the agent for the candidate's
    own file. Here, next to the upload box, it is one sentence and one drag of a
    different document.
    """
    text = "\n".join(block.text for block in document)
    if not language_check.wrong_language(text, language):
        return ""
    noun = kind_of(kind).noun
    other = "English" if normalise_language(language) == "fr" else "French"
    name = "French" if normalise_language(language) == "fr" else "English"
    return (
        f"This document reads as {other} but it is filed as the {name} {noun}. Check you "
        f"uploaded the right file — the blanks in it will be filled in {name}."
    )


def complete(kind: str) -> bool:
    """Both documents of one kind uploaded and still on disk. The gate `onboarding` reads."""
    state = status(kind)
    return all(
        (entry := state.get(language)) is not None and entry["on_disk"]
        for language in SUPPORTED_LANGUAGES
    )


def missing_languages(kind: str) -> list[str]:
    state = status(kind)
    return [
        language
        for language in SUPPORTED_LANGUAGES
        if state.get(language) is None or not state[language]["on_disk"]
    ]
