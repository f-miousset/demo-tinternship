"""Test fixtures.

Each test module gets its own temporary data directory so the real
`data/tinternship.db` is never touched and tests cannot see each other's rows.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir() -> Iterator[str]:
    directory = tempfile.mkdtemp(prefix="tinternship-tests-")
    os.environ["DATA_DIR"] = directory
    os.environ.setdefault("GOOGLE_API_KEY", "test-key-not-used")
    # No test may start Chromium or reach the network. The browser fallback in
    # `services/verification.py` fires on any link it could not settle, which a
    # fake HTTP layer produces constantly — tests that mean to exercise it stub
    # `browser_check.recheck` and turn this back on for themselves.
    os.environ["BROWSER_VERIFY"] = "false"

    # Settings and the engine are cached, so they must be built *after* the
    # environment is set.
    from tinternship_backend.config import get_settings

    get_settings.cache_clear()

    from tinternship_backend.db import engine as engine_module

    engine_module._engine = None
    engine_module.init_db()

    yield directory


@pytest.fixture(autouse=True)
def clean_tables(isolated_data_dir: str) -> Iterator[None]:
    from sqlmodel import SQLModel, delete

    from tinternship_backend.db.engine import get_engine, session_scope

    yield
    with session_scope() as session:
        for table in reversed(SQLModel.metadata.sorted_tables):
            session.exec(delete(table))
    get_engine()


# ---------------------------------------------------------------------------
# Base documents
# ---------------------------------------------------------------------------
#
# Since 2026-08-28 an applying run fills in the candidate's own .docx rather
# than generating one — the résumé then, the cover letter since 2026-09-09 — so
# a great many tests need real Word documents on disk. These build them: small,
# but genuinely .docx files, with the things the gate actually reasons about — a
# placeholder to fill, a bold run beside a tab that must survive an edit, and
# for the letter the two blanks Python answers before the agent is asked.


def build_docx(lines: list[str] | None = None) -> bytes:
    """A tiny but real .docx, in memory."""
    import io

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    document = Document()
    if lines is None:
        heading = document.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.add_run("Alex Martin").bold = True
        document.add_paragraph("alex@example.com • Paris")
        document.add_paragraph("")
        document.add_paragraph("Objectif : [Poste visé] chez [Entreprise]")
        entry = document.add_paragraph()
        entry.add_run("Acme").bold = True
        entry.add_run("\tParis, France")
        document.add_paragraph("Conception d'un pipeline de données pour l'équipe analytique")
        document.add_paragraph("Compétences : Python, SQL, Docker")
    else:
        for line in lines:
            document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# The shape of the candidate's own letter templates, cut down: a date line and
# an address block whose blanks are answered in three different ways (Python's,
# the agent's, and "may be left empty"), then the three paragraphs.
LETTER_LINES = [
    "Alex Martin",
    "alex@example.com • Paris",
    "",
    "[current_month_letters] [current_date], 2026",
    "",
    "[team_name] Team",
    "[company_name]",
    "[address_company]",
    "[city_company]",
    "",
    "Job reference: [job_posting_name]",
    "",
    "Dear Recruiter:",
    "",
    "[cover_letter_opening_paragraph]",
    "",
    "[cover_letter_middle_paragraph]",
    "",
    "[cover_letter_closing_paragraph]",
    "",
    "Sincerely,",
]


def build_letter_docx(lines: list[str] | None = None) -> bytes:
    """A tiny but real base cover letter, in memory."""
    return build_docx(lines if lines is not None else LETTER_LINES)


def build_plan(
    language: str = "fr",
    data: bytes | None = None,
    kind: str = "resume",
    known=None,
):
    """A `base_documents.Plan` from an in-memory document, without the database.

    What the applying team actually takes since 2026-08-29: the document, its
    blanks, and the room left on its page. Built here rather than in each test
    because getting it from `base_documents.plan()` would need a row on disk,
    and most of these tests are about an agent, not about storage.
    """
    from tinternship_backend.services import base_documents, docx_template, page_fit

    payload = data if data is not None else build_docx()
    blocks = docx_template.read_blocks(payload)
    slots = docx_template.find_slots(blocks)
    auto = dict(known(slots)) if known else {}
    measured = payload
    if auto:
        measured, _ = docx_template.apply_fills(payload, blocks, slots, auto)
    estimate = page_fit.measure(measured)
    descriptor = base_documents.kind_of(kind)
    budgets = page_fit.slot_budgets(
        estimate,
        [slot for slot in slots if slot.key not in auto],
        ceiling=descriptor.ceiling,
        share_factor=descriptor.share,
    )
    return base_documents.Plan(
        kind=kind,
        language=language,
        data=payload,
        blocks=blocks,
        slots=docx_template.with_budgets(slots, budgets),
        estimate=estimate,
        auto=auto,
    )


def build_letter_plan(language: str = "en", data: bytes | None = None, company: str = "Acme"):
    """The letter plan a run builds: blanks priced, date and employer already in."""
    from datetime import date

    from tinternship_backend.services import base_documents, letter_fields

    facts = letter_fields.LetterFacts(
        language=language, company=company, today=date(2026, 9, 9)
    )
    return build_plan(
        language=language,
        data=data if data is not None else build_letter_docx(),
        kind=base_documents.COVER_LETTER,
        known=letter_fields.resolver(facts),
    )


def install_base_document(
    kind: str = "resume", language: str = "en", data: bytes | None = None, filename: str = ""
) -> int:
    """Put a base document on disk and in the database, without running an agent.

    `flows.ingest_base_document` is the real path and it calls the extractor;
    everything that is not testing the extractor wants this instead.
    """
    from tinternship_backend.services import base_documents

    if data is None:
        data = build_docx() if kind == base_documents.RESUME else build_letter_docx()
    name = filename or f"{kind}-{language}.docx"
    path = base_documents.stored_path(kind, language, name)
    path.write_bytes(data)
    source = base_documents.replace(kind, language, label=name, file_path=str(path))
    return source.id


def install_base_resume(
    language: str = "en", data: bytes | None = None, filename: str = ""
) -> int:
    """The résumé half of `install_base_document`, which most tests want alone."""
    return install_base_document("resume", language, data, filename)


@pytest.fixture
def base_resumes() -> list[int]:
    """Both résumés installed. Not enough for `onboarding.complete` on its own."""
    return [install_base_resume(language) for language in ("en", "fr")]


@pytest.fixture
def base_documents_installed() -> list[int]:
    """All four documents, which is what an applying run and `onboarding` need."""
    return [
        install_base_document(kind, language)
        for kind in ("resume", "cover_letter")
        for language in ("en", "fr")
    ]


# ---------------------------------------------------------------------------
# Walking an applying team
# ---------------------------------------------------------------------------


def agents_by_name(team) -> dict[str, object]:
    """Every agent under one team, keyed by name, whatever the lanes look like.

    The applying team is not two loops any more: the letter's lane is a
    sequence — the Address Scout, then the writer's own critic loop — because an
    agent carrying `google_search` cannot carry an output schema. Tests that
    reached in by index broke on that shape change while nothing they were
    actually testing had moved, so they ask by name instead.
    """
    found: dict[str, object] = {}

    def walk(agent) -> None:
        found[agent.name] = agent
        for child in getattr(agent, "sub_agents", None) or []:
            walk(child)

    walk(team)
    return found


def applying_producers(team) -> dict[str, object]:
    """The two agents that produce an artifact, by name."""
    found = agents_by_name(team)
    return {name: found[name] for name in ("resume_agent", "cover_letter_agent")}


def applying_critics(team) -> dict[str, object]:
    """The two Critics, by the name of the producer each one reads."""
    found = agents_by_name(team)
    return {
        name: found[f"{name}_critic"] for name in ("resume_agent", "cover_letter_agent")
    }


def applying_gates(team) -> dict[str, object]:
    """The two gates, by the name of the producer each one disqualifies."""
    found = agents_by_name(team)
    return {name: found[f"{name}_gate"] for name in ("resume_agent", "cover_letter_agent")}
