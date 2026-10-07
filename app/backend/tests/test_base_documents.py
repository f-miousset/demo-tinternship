"""The four documents the whole application package is built from.

A résumé and a cover letter, each in French and in English. They are mandatory,
they are `.docx`, there is exactly one per kind and language, and the export
path has to produce *the candidate's own file* rather than a rendering of its
text. Each of those is a promise something else in the app now depends on, so
each has a test here.

The letter joined the résumé on 2026-09-09 and works the same way, with two
differences that have their own tests at the bottom: some of its blanks are
answered in Python before the agent is asked anything, and its address lines may
come back empty rather than invented.
"""

from __future__ import annotations

import io

import pytest
from conftest import (
    build_docx,
    build_letter_docx,
    install_base_document,
    install_base_resume,
)
from docx import Document
from fastapi.testclient import TestClient

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ArtifactKind,
    JobPosting,
)
from tinternship_backend.main import app
from tinternship_backend.services import base_documents, docx_template, flows, letter_fields
from tinternship_backend.services.base_documents import COVER_LETTER, RESUME, BaseDocumentError

DOCX_MIME = docx_template.DOCX_MIME


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestValidation:
    def test_a_real_docx_is_accepted(self):
        blocks = base_documents.validate(RESUME, build_docx())

        assert blocks
        assert any(block.placeholders for block in blocks)

    def test_a_pdf_is_refused_with_the_reason(self):
        """Not a convenience limit: a PDF cannot be edited in place without
        becoming a different document, which is the thing this replaced."""
        with pytest.raises(BaseDocumentError) as error:
            base_documents.validate(RESUME, b"%PDF-1.7\nnot a word document")

        assert "save it as .docx" in str(error.value)

    def test_a_document_with_no_text_is_refused(self):
        document = Document()
        buffer = io.BytesIO()
        document.save(buffer)

        with pytest.raises(BaseDocumentError) as error:
            base_documents.validate(RESUME, buffer.getvalue())

        assert "no text in it" in str(error.value)

    def test_a_document_over_the_block_ceiling_is_refused(self):
        """More paragraphs than there are index values means paragraphs the
        Tailor has no name for."""
        oversized = build_docx([f"line {index}" for index in range(docx_template.MAX_BLOCKS + 5)])

        with pytest.raises(BaseDocumentError) as error:
            base_documents.validate(RESUME, oversized)

        assert "the limit is" in str(error.value)


class TestOnePerLanguage:
    def test_uploading_again_replaces_rather_than_accumulates(self):
        first = install_base_resume("fr")
        second = install_base_resume("fr", build_docx(["un CV tout neuf"]))

        assert first != second
        assert base_documents.get(RESUME, "fr").id == second
        assert base_documents.blocks(RESUME, "fr")[0].text == "un CV tout neuf"

    def test_the_replaced_file_is_deleted_from_disk(self):
        install_base_resume("fr", filename="old.docx")
        first_path = base_documents.resolved_path(base_documents.get(RESUME, "fr"))

        install_base_resume("fr", build_docx(["autre"]), filename="new.docx")

        assert not first_path.exists()
        assert base_documents.resolved_path(base_documents.get(RESUME, "fr")).exists()

    def test_re_uploading_under_the_same_filename_keeps_the_new_file(self):
        """`/var` is a symlink to `/private/var` on macOS, so the outgoing and
        incoming paths have two spellings for the same file. Comparing them
        unresolved deleted the document that had just been written."""
        install_base_resume("fr")

        install_base_resume("fr", build_docx(["le remplacement"]))

        assert base_documents.blocks(RESUME, "fr")[0].text == "le remplacement"

    def test_the_two_languages_are_independent(self):
        install_base_resume("en", build_docx(["an English CV"]))
        install_base_resume("fr", build_docx(["un CV français"]))

        assert base_documents.blocks(RESUME, "en")[0].text == "an English CV"
        assert base_documents.blocks(RESUME, "fr")[0].text == "un CV français"


class TestCompleteness:
    def test_neither_uploaded_means_both_are_missing(self):
        assert base_documents.complete(RESUME) is False
        assert set(base_documents.missing_languages(RESUME)) == {"en", "fr"}

    def test_one_uploaded_is_still_incomplete(self):
        install_base_resume("fr")

        assert base_documents.complete(RESUME) is False
        assert base_documents.missing_languages(RESUME) == ["en"]

    def test_both_uploaded_completes_the_step(self, base_resumes):
        assert base_documents.complete(RESUME) is True
        assert base_documents.missing_languages(RESUME) == []

    def test_the_two_kinds_are_counted_apart(self, base_resumes):
        """Uploading both résumés says nothing about the letters, and the
        Account page has to show two separate blockers rather than one."""
        assert base_documents.complete(COVER_LETTER) is False
        assert set(base_documents.missing_languages(COVER_LETTER)) == {"en", "fr"}

    def test_a_row_whose_file_vanished_counts_as_missing(self):
        """The row is not the document. Reporting the step as done when the
        file is gone would fail the run instead of the upload."""
        install_base_resume("fr")
        base_documents.resolved_path(base_documents.get(RESUME, "fr")).unlink()

        assert base_documents.complete(RESUME) is False
        assert "fr" in base_documents.missing_languages(RESUME)

    def test_reading_a_missing_one_says_which_upload_is_needed(self):
        with pytest.raises(BaseDocumentError) as error:
            base_documents.read(RESUME, "fr")

        assert "no base résumé for fr" in str(error.value)


class TestTheApi:
    def test_upload_stores_the_document_and_reports_its_placeholders(
        self, client, monkeypatch
    ):
        async def no_extraction(**_kwargs):
            return {}, ""

        monkeypatch.setattr(flows, "_extract_document", no_extraction)

        response = client.post(
            "/api/profile/base-document/resume/fr",
            files={"file": ("cv.docx", build_docx(), DOCX_MIME)},
        )

        assert response.status_code == 200, response.text
        assert response.json()["placeholders"] == 2
        assert base_documents.get(RESUME, "fr") is not None

    def test_a_failed_extraction_does_not_lose_the_document(self, client, monkeypatch):
        """The file is the part that matters and it is already on disk. Losing
        the base résumé because Gemini was rate-limited is the worse trade."""

        async def broken(**_kwargs):
            raise RuntimeError("429 from the model")

        monkeypatch.setattr(flows, "_extract_document", broken)

        response = client.post(
            "/api/profile/base-document/resume/fr",
            files={"file": ("cv.docx", build_docx(), DOCX_MIME)},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "failed"
        assert "429" in response.json()["error"]
        assert base_documents.blocks(RESUME, "fr")

    def test_a_non_docx_upload_is_rejected_before_anything_is_stored(self, client):
        response = client.post(
            "/api/profile/base-document/resume/fr",
            files={"file": ("cv.pdf", b"%PDF-1.7", "application/pdf")},
        )

        assert response.status_code == 400
        assert ".docx" in response.json()["detail"]
        assert base_documents.get(RESUME, "fr") is None

    def test_an_unsupported_language_is_rejected(self, client):
        response = client.post(
            "/api/profile/base-document/resume/de",
            files={"file": ("cv.docx", build_docx(), DOCX_MIME)},
        )

        assert response.status_code == 400

    def test_the_profile_endpoint_reports_which_documents_exist(self, client):
        install_base_resume("fr")

        body = client.get("/api/profile").json()

        assert body["base_resumes"]["fr"] is not None
        assert body["base_resumes"]["en"] is None

    def test_base_resumes_are_not_listed_among_the_removable_sources(self, client):
        """Their own section owns them. Offering one in the 'imported sources'
        list would invite deleting the document the app cannot run without."""
        install_base_resume("fr")

        body = client.get("/api/profile").json()

        assert all(source["kind"] != "base_resume" for source in body["sources"])

    def test_delete_removes_the_row_and_the_file(self, client):
        install_base_resume("fr")
        path = base_documents.resolved_path(base_documents.get(RESUME, "fr"))

        response = client.delete("/api/profile/base-document/resume/fr")

        assert response.status_code == 200
        assert base_documents.get(RESUME, "fr") is None
        assert not path.exists()


class TestGenerateRefusesWithoutOne:
    @staticmethod
    def _application() -> int:
        with session_scope() as session:
            job = JobPosting(dedupe_key="k", title="ML Intern", company="Acme")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            return application.id

    def test_it_is_a_409_before_the_stream_opens(self, client):
        """Inside the stream this would be an `error` event on a page already
        showing progress, and would read as "the run failed" rather than "you
        have not uploaded that document yet"."""
        response = client.post(
            f"/api/applications/{self._application()}/generate", json={"language": "fr"}
        )

        assert response.status_code == 409
        assert "base résumé" in response.json()["detail"]

    def test_a_missing_cover_letter_stops_a_run_that_asked_for_one(self, client):
        """Getting as far as a stream and then failing on the second document is
        the outcome this check exists to avoid."""
        install_base_resume("fr")

        response = client.post(
            f"/api/applications/{self._application()}/generate",
            json={"language": "fr", "cover_letter": True},
        )

        assert response.status_code == 409
        assert "base cover letter" in response.json()["detail"]

    def test_a_missing_cover_letter_does_not_stop_a_résumé_only_run(self, client, monkeypatch):
        """The default run writes no letter, so the letter's base document is
        none of its business. Refusing here would make an unrelated missing file
        block every application the candidate makes."""
        install_base_resume("fr")

        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)

        response = client.post(
            f"/api/applications/{self._application()}/generate", json={"language": "fr"}
        )

        assert response.status_code == 200

    def test_the_missing_document_is_a_warning_on_the_config_endpoint(self, client):
        install_base_resume("fr")

        warnings = client.get("/api/config").json()["warnings"]

        assert any("No en base résumé" in warning for warning in warnings)


class TestThePlanPricesTheBlanks:
    """What a run is handed: the document, its blanks, and the room for them.

    The candidate's rule is *never more than one page*, and their CV already
    fills most of it. So the plan is where "how much can the tailoring say" stops
    being a matter of prompt wording and becomes a number measured off their own
    file.
    """

    @staticmethod
    def _crowded(lines: list[str]) -> bytes:
        document = Document()
        for line in lines:
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_it_finds_the_blanks_and_gives_each_one_a_budget(self):
        install_base_resume("fr")

        plan = base_documents.plan(RESUME, "fr")

        assert [slot.token for slot in plan.slots] == ["[Poste visé]", "[Entreprise]"]
        assert all(slot.budget > 0 for slot in plan.slots)

    def test_a_document_with_room_is_usable(self):
        install_base_resume("fr")

        plan = base_documents.plan(RESUME, "fr")

        assert plan.usable
        assert plan.complaint == ""
        assert plan.room > plan.needed

    def test_a_document_with_no_room_left_is_not(self):
        """A CV that already fills its page has nowhere to put a job title, and
        no amount of revision will find one."""
        lines = ["Poste : [Poste visé]"] + [f"Ligne {n} du document" for n in range(60)]
        install_base_resume("fr", data=self._crowded(lines))

        plan = base_documents.plan(RESUME, "fr")

        assert not plan.usable
        assert "one page" in plan.complaint
        assert "%" in plan.complaint

    def test_generating_against_it_is_a_409_that_says_what_to_fix(self, client):
        lines = ["Poste : [Poste visé]"] + [f"Ligne {n} du document" for n in range(60)]
        install_base_resume("fr", data=self._crowded(lines))
        install_base_resume("en")
        with session_scope() as session:
            job = JobPosting(dedupe_key="k", title="ML Intern", company="Acme")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            application_id = application.id

        response = client.post(
            f"/api/applications/{application_id}/generate", json={"language": "fr"}
        )

        assert response.status_code == 409
        assert "free up a line" in response.json()["detail"]

    def test_the_account_page_is_told_before_it_ever_gets_that_far(self, client):
        lines = ["Poste : [Poste visé]"] + [f"Ligne {n} du document" for n in range(60)]
        install_base_resume("fr", data=self._crowded(lines))

        entry = client.get("/api/config").json()["base_resumes"]["fr"]

        assert entry["crowded"] is True
        assert "%" in entry["page"]
        assert entry["placeholders"] == 1

    def test_it_is_a_warning_on_the_config_endpoint_too(self, client):
        """A crowded document is the same outcome as a missing one and far less
        obvious, because the card is green and the file is there."""
        lines = ["Poste : [Poste visé]"] + [f"Ligne {n} du document" for n in range(60)]
        install_base_resume("fr", data=self._crowded(lines))
        install_base_resume("en")

        warnings = client.get("/api/config").json()["warnings"]

        assert any("already fills its page" in warning for warning in warnings)

    def test_a_document_in_the_wrong_language_is_a_warning_not_a_gate(self):
        """The tailoring only writes into the blanks, so the language of the
        rest of the page is not something any agent can fix. Refusing every
        French application over it would punish the agent for the candidate's
        own file."""
        english = self._crowded(
            [
                "Poste : [Poste visé]",
                "Built and shipped the data pipeline that the team uses every day.",
            ]
        )
        install_base_resume("fr", data=english)

        plan = base_documents.plan(RESUME, "fr")
        entry = base_documents.status(RESUME)["fr"]

        assert plan.usable, "a warning, not a refusal"
        assert "uploaded the right file" in entry["language_warning"]


class TestTheExportIsTheCandidatesOwnFile:
    @staticmethod
    def _artifact(content: dict) -> int:
        with session_scope() as session:
            job = JobPosting(dedupe_key="k2", title="Stage ML", company="Acme")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id, language="fr")
            session.add(application)
            session.flush()
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=ArtifactKind.RESUME,
                version=1,
                content=content,
            )
            session.add(artifact)
            session.flush()
            return artifact.id

    def _tailored(self) -> dict:
        blocks = docx_template.read_blocks(build_docx())
        return {
            "language": "fr",
            "document_title": "CV — Stage ML",
            "blocks": docx_template.blocks_payload(blocks),
            # The slots travel with the artifact rather than being re-derived at
            # export. A run's fills are keyed to the blanks that existed when it
            # ran, and re-reading a CV whose placeholders have since moved would
            # put the employer where the job title goes.
            "slots": docx_template.slots_payload(docx_template.find_slots(blocks)),
            "fills": [
                {"slot": "s0", "text": "Stage Machine Learning"},
                {"slot": "s1", "text": "Nimbus"},
            ],
        }

    def test_the_download_is_a_docx_with_the_blanks_filled(self):
        install_base_resume("fr")
        artifact_id = self._artifact(self._tailored())

        path, mime, filename = flows.export_artifact_file(artifact_id)

        assert mime == DOCX_MIME
        assert filename.endswith(".docx")
        blocks = docx_template.read_blocks(open(path, "rb").read())
        assert blocks[3].text == "Objectif : Stage Machine Learning chez Nimbus"

    def test_the_untouched_lines_come_back_byte_for_byte(self):
        install_base_resume("fr")
        original = docx_template.read_blocks(base_documents.read(RESUME, "fr"))
        artifact_id = self._artifact(self._tailored())

        path, _mime, _filename = flows.export_artifact_file(artifact_id)
        exported = docx_template.read_blocks(open(path, "rb").read())

        assert len(exported) == len(original)
        assert [block.text for block in exported[:3]] == [
            block.text for block in original[:3]
        ]
        assert [block.text for block in exported[4:]] == [
            block.text for block in original[4:]
        ]

    def test_the_french_package_is_named_in_french(self):
        install_base_resume("fr")
        artifact_id = self._artifact(self._tailored())

        _path, _mime, filename = flows.export_artifact_file(artifact_id)

        assert filename.startswith("CV_")

    def test_an_artifact_whose_base_document_is_gone_says_so(self):
        artifact_id = self._artifact(self._tailored())

        with pytest.raises(BaseDocumentError):
            flows.export_artifact_file(artifact_id)


class TestTheLetterIsTheSameMechanism:
    """A cover letter is a base document like the résumé, uploaded the same way."""

    def test_it_is_stored_and_reported_apart_from_the_resume(self, client):
        response = client.post(
            "/api/profile/base-document/cover_letter/en",
            files={"file": ("letter.docx", build_letter_docx(), DOCX_MIME)},
        )

        assert response.status_code == 200, response.text
        body = client.get("/api/profile").json()
        assert body["base_cover_letters"]["en"] is not None
        assert body["base_resumes"]["en"] is None

    def test_uploading_one_does_not_call_the_extractor(self, client, monkeypatch):
        """A letter template holds no career facts the CV has not already given,
        and its availability sentence is a template line rather than a fact
        about the candidate."""

        def explode(**_kwargs):
            raise AssertionError("the extractor must not be called for a letter")

        monkeypatch.setattr(flows, "_extract_document", explode)

        response = client.post(
            "/api/profile/base-document/cover_letter/fr",
            files={"file": ("lettre.docx", build_letter_docx(), DOCX_MIME)},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "parsed"

    def test_an_unknown_kind_is_a_400(self, client):
        response = client.post(
            "/api/profile/base-document/portfolio/en",
            files={"file": ("x.docx", build_letter_docx(), DOCX_MIME)},
        )

        assert response.status_code == 400

    def test_a_letter_is_not_listed_among_the_removable_sources(self, client):
        install_base_document(COVER_LETTER, "en")

        body = client.get("/api/profile").json()

        assert all(source["kind"] != "base_cover_letter" for source in body["sources"])

    def test_delete_removes_the_row_and_the_file(self, client):
        install_base_document(COVER_LETTER, "en")
        path = base_documents.resolved_path(base_documents.get(COVER_LETTER, "en"))

        response = client.delete("/api/profile/base-document/cover_letter/en")

        assert response.status_code == 200
        assert base_documents.get(COVER_LETTER, "en") is None
        assert not path.exists()


class TestThePlanAnswersWhatItCan:
    """The two blanks Python fills before the agent is asked anything."""

    @staticmethod
    def _plan(language: str = "en", company: str = "Nimbus Labs"):
        from datetime import date

        install_base_document(COVER_LETTER, language)
        facts = letter_fields.LetterFacts(
            language=language, company=company, today=date(2026, 9, 9)
        )
        return base_documents.plan(
            COVER_LETTER, language, known=letter_fields.resolver(facts)
        )

    def test_the_date_and_the_employer_are_filled_from_the_record(self):
        plan = self._plan()

        filled = {
            plan.slots[index].token: text
            for index, text in enumerate(plan.auto.get(slot.key, "") for slot in plan.slots)
            if text
        }
        assert filled == {
            "[current_month_letters]": "September",
            "[current_date]": "9",
            "[company_name]": "Nimbus Labs",
        }

    def test_the_french_letter_gets_french_months(self):
        plan = self._plan("fr")

        assert "septembre" in plan.auto.values()

    def test_those_blanks_are_not_offered_to_the_agent(self):
        """It is never shown them, so it cannot spend a fill or a revision on
        them — and cannot get today's date wrong."""
        plan = self._plan()

        assert not (set(plan.auto) & {slot.key for slot in plan.open})
        assert "[cover_letter_opening_paragraph]" in [slot.token for slot in plan.open]

    def test_the_reference_line_stays_the_agents(self):
        """It has to fit the candidate's own sentence — 'Candidature au stage
        [x]' with a posting titled 'Stage – …' is what copying a column does."""
        plan = self._plan()

        assert "[job_posting_name]" in [slot.token for slot in plan.open]

    def test_a_paragraph_blank_is_priced_as_a_paragraph(self):
        """A résumé blank is a title or a list and is capped at 400 characters.
        The same cap on a letter would buy about 200 words of letter."""
        plan = self._plan()

        paragraphs = [
            slot for slot in plan.open if "paragraph" in slot.token
        ]
        assert paragraphs
        assert all(slot.budget > 400 for slot in paragraphs)


class TestTheLetterExport:
    @staticmethod
    def _artifact(content: dict) -> int:
        with session_scope() as session:
            job = JobPosting(dedupe_key="k3", title="Stage ML", company="Nimbus")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id, language="en")
            session.add(application)
            session.flush()
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=ArtifactKind.COVER_LETTER,
                version=1,
                content=content,
            )
            session.add(artifact)
            session.flush()
            return artifact.id

    @staticmethod
    def _content() -> dict:
        blocks = docx_template.read_blocks(build_letter_docx())
        slots = docx_template.find_slots(blocks)
        by_token = {slot.token: slot.key for slot in slots}
        return {
            "language": "en",
            "document_title": "Cover letter — Nimbus",
            "blocks": docx_template.blocks_payload(blocks),
            "slots": docx_template.slots_payload(slots),
            "fills": [
                {"slot": by_token["[current_month_letters]"], "text": "September"},
                {"slot": by_token["[current_date]"], "text": "9"},
                {"slot": by_token["[company_name]"], "text": "Nimbus Labs"},
                {"slot": by_token["[team_name]"], "text": "Data Science"},
                {"slot": by_token["[address_company]"], "text": ""},
                {"slot": by_token["[city_company]"], "text": "Paris"},
                {"slot": by_token["[job_posting_name]"], "text": "Data Scientist Intern"},
                {
                    "slot": by_token["[cover_letter_opening_paragraph]"],
                    "text": "I am writing about the Data Scientist internship.",
                },
                {
                    "slot": by_token["[cover_letter_middle_paragraph]"],
                    "text": "I built a pipeline that ran every day.",
                },
                {
                    "slot": by_token["[cover_letter_closing_paragraph]"],
                    "text": "I would be glad to talk it through.",
                },
            ],
        }

    def test_the_download_is_the_candidates_own_letter_filled_in(self):
        install_base_document(COVER_LETTER, "en")
        artifact_id = self._artifact(self._content())

        path, mime, filename = flows.export_artifact_file(artifact_id)

        assert mime == DOCX_MIME
        assert filename.startswith("Cover_Letter_")
        text = [block.text for block in docx_template.read_blocks(open(path, "rb").read())]
        assert "September 9, 2026" in text
        assert "Data Science Team" in text
        assert "Job reference: Data Scientist Intern" in text

    def test_everything_outside_the_blanks_is_copied(self):
        install_base_document(COVER_LETTER, "en")
        original = docx_template.read_blocks(base_documents.read(COVER_LETTER, "en"))
        artifact_id = self._artifact(self._content())

        path, _mime, _filename = flows.export_artifact_file(artifact_id)
        exported = docx_template.read_blocks(open(path, "rb").read())

        assert len(exported) == len(original)
        assert exported[0].text == "Alex Martin"
        assert exported[-1].text == "Sincerely,"

    def test_an_empty_address_line_becomes_an_empty_line(self):
        """Not a removed paragraph — nothing here may change the layout — and
        not the placeholder either: a letter with no street published for it
        shows a blank line, and `[address_company]` reaching an employer is the
        worst thing this can do."""
        install_base_document(COVER_LETTER, "en")
        artifact_id = self._artifact(self._content())
        base = docx_template.read_blocks(build_letter_docx())

        path, _mime, _filename = flows.export_artifact_file(artifact_id)
        blocks = docx_template.read_blocks(open(path, "rb").read())

        assert len(blocks) == len(base), "no paragraph was added or removed"
        assert "[address_company]" not in [block.text for block in blocks]
        # The address line itself, and one more blank line than the template had.
        empty = [block.text for block in blocks].count("")
        assert empty == [block.text for block in base].count("") + 1
