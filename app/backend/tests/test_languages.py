"""The English/French choice made before generating has to reach four places.

The agents (so they write in it), the application row (so regenerating keeps
it), the filename (so a French package arrives as `CV_…`), and — since
2026-08-28 — the *base document*, because the choice now also decides which of
the candidate's two .docx résumés is the one being tailored.

The gate is the fourth: `services/language_check.py` reads what was actually
produced and rejects a document with the other language still in it. That is the
bug this all exists for; see `tests/test_language_check.py` for the detector
itself.
"""

from __future__ import annotations

import pytest
from conftest import (
    applying_critics,
    applying_gates,
    applying_producers,
    build_letter_plan,
    build_plan,
)
from fastapi.testclient import TestClient

from tinternship_backend.agents.applying import build_applying_team, hard_check
from tinternship_backend.agents.prompts import language_block
from tinternship_backend.agents.schemas import TailoredResume
from tinternship_backend.services.languages import DEFAULT_LANGUAGE, normalise_language


def _letters(language: str = "fr"):
    return build_letter_plan(language)


def _plan(language: str = "fr"):
    """The candidate's base résumé, read and priced. Line 3 holds the two
    blanks — `s0` is the target role, `s1` the employer."""
    return build_plan(language)


class TestNormalisation:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("fr", "fr"), ("FR", "fr"), ("fr-FR", "fr"), ("français", "fr"), ("en", "en")],
    )
    def test_accepts_the_shapes_a_model_or_a_caller_might_send(self, value, expected):
        assert normalise_language(value) == expected

    @pytest.mark.parametrize("value", ["", None, "de", "klingon", 7])
    def test_anything_unsupported_falls_back_rather_than_raising(self, value):
        assert normalise_language(value) == DEFAULT_LANGUAGE


class TestLanguageBlock:
    def test_names_the_chosen_language(self):
        block = language_block("fr")
        assert "French" in block and "français" in block

    def test_says_it_overrides_the_posting(self):
        assert "overrides the posting" in language_block("en")

    def test_does_not_ask_the_model_to_report_the_language_back(self):
        """Observed live: told to "set the `language` field", the (since
        removed) plan agent narrated into that string and ended the JSON object
        before `steps`, losing the entire plan. The language is stamped on by
        the flow that saves the artifact, never asked for inline."""
        for language in ("en", "fr"):
            assert "`language`" not in language_block(language)

    def test_the_resume_is_never_asked_for_a_language_field(self):
        assert "language" not in TailoredResume.model_fields


class TestAgentWiring:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("language", ["en", "fr"])
    async def test_every_applying_agent_is_told_the_language(self, language):
        team = build_applying_team(
            job_id=0, resume_plan=_plan(language), letter_plan=_letters(language)
        )
        expected = language_block(language)

        class Ctx:
            state: dict = {}

        for producer in applying_producers(team).values():
            instruction = await producer.instruction(Ctx())
            assert expected in instruction, producer.name


class TestGenerateEndpoint:
    @pytest.fixture()
    def client(self):
        from tinternship_backend.main import app

        return TestClient(app)

    def _application(self) -> int:
        from tinternship_backend.db.engine import session_scope
        from tinternship_backend.db.models import Application, JobPosting

        with session_scope() as session:
            job = JobPosting(
                dedupe_key="nimbus-ml-intern",
                title="ML Intern",
                company="Nimbus",
                url="https://example.com/1",
            )
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            return application.id

    def test_an_unsupported_language_is_rejected(self, client):
        response = client.post(f"/api/applications/{self._application()}/generate", json={"language": "de"})
        assert response.status_code == 400
        assert "de" in response.json()["detail"]

    def test_the_choice_is_remembered_on_the_application(
        self, client, monkeypatch, base_documents_installed
    ):
        from tinternship_backend.services import flows

        seen: dict[str, str] = {}

        async def fake_run(
            application_id,
            job_id,
            language=DEFAULT_LANGUAGE,
            personalisation="",
            cover_letter=False,
            resume=True,
        ):
            seen["language"] = language
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake_run)
        application_id = self._application()

        client.post(f"/api/applications/{application_id}/generate", json={"language": "fr"})
        assert seen["language"] == "fr"
        assert client.get(f"/api/applications/{application_id}").json()["language"] == "fr"

        # Regenerating without a language keeps the one already chosen rather
        # than quietly reverting to English.
        client.post(f"/api/applications/{application_id}/generate")
        assert seen["language"] == "fr"


class TestTheGateIsArithmetic:
    """The hard checks that decide a tailoring run, none of them a judgement.

    This replaced the one-page check on 2026-08-28, and then grew it back on
    2026-08-29 in a form that can actually be measured. The old rule existed
    because the Critic scored `concision` 7/10 on a résumé it had just been told
    to cap at 2 pages; these rules exist for the same reason, applied to what
    can now go wrong — a blank left unfilled, a fill that spills the page,
    English left in a French CV.
    """

    @staticmethod
    def _team(language: str = "fr"):
        return build_applying_team(
            job_id=0, resume_plan=_plan(language), letter_plan=_letters(language)
        )

    @staticmethod
    def _gates(team) -> dict:
        return applying_gates(team)

    def test_a_complete_set_of_fills_passes(self):
        artifact = {
            "fills": [
                {"slot": "s0", "text": "Stage Data"},
                {"slot": "s1", "text": "Acme"},
            ]
        }

        assert hard_check(artifact, _plan()) == ""

    def test_a_blank_left_unfilled_is_refused(self):
        assert "left unfilled" in hard_check({"fills": []}, _plan())

    def test_an_empty_fill_is_refused(self):
        artifact = {
            "fills": [
                {"slot": "s0", "text": "Stage Data"},
                {"slot": "s1", "text": "  "},
            ]
        }

        assert "came back empty" in hard_check(artifact, _plan())

    def test_english_left_in_a_french_resume_is_refused(self):
        """Measured on the fills alone as well as in place: four English words
        in a long French document do not move a whole-document ratio, and they
        are the only words this run actually wrote."""
        artifact = {
            "fills": [
                {"slot": "s0", "text": "an internship in the data team"},
                {"slot": "s1", "text": "the company that we like"},
            ]
        }

        assert "still has English in it" in hard_check(artifact, _plan("fr"))

    def test_the_same_fills_are_fine_in_an_english_resume(self):
        artifact = {
            "fills": [
                {"slot": "s0", "text": "an internship in the data team"},
                {"slot": "s1", "text": "the company that we like"},
            ]
        }

        assert hard_check(artifact, _plan("en")) == ""

    def test_a_fill_that_would_spill_the_page_is_refused(self):
        """The candidate's rule, and the only one a filled blank can still
        break: their CV is one page and it is nearly full."""
        import dataclasses

        from tinternship_backend.services import docx_template

        lines = ["Poste : [Poste visé]"] + [f"Ligne {n} du document" for n in range(56)]
        plan = build_plan("fr", data=_crowded(lines))
        # Budget raised past what the page can take, so the per-slot cap cannot
        # be what refuses this. The page is the backstop, and it is measured on
        # the document that would actually be sent.
        plan = dataclasses.replace(
            plan, slots=docx_template.with_budgets(plan.slots, {"s0": 5000})
        )
        artifact = {"fills": [{"slot": "s0", "text": "mots " * 300}]}

        assert "second page" in hard_check(artifact, plan)

    def test_a_coursework_line_that_stops_early_is_refused_too(self):
        """The other half of the same rule, and the candidate's second report on
        2026-09-10: the lists coming back at half their budget, with room on the
        line for two more courses. Their CV is 96% full, so the room is small —
        which is exactly why leaving 40% of it unused matters."""
        lines = [
            "Cours : [liste de cours]",
            "Competences : [liste de competences]",
        ] + [f"Ligne {n} du document" for n in range(44)]
        plan = build_plan("fr", data=_crowded(lines))
        artifact = {
            "fills": [
                {"slot": "s0", "text": "Bases de donnees"},
                {"slot": "s1", "text": "Python, SQL"},
            ]
        }

        problem = hard_check(artifact, plan)

        assert "characters this page has room for" in problem
        assert "s0 (16 of " in problem

    def test_the_same_lines_filled_to_the_budget_pass(self):
        """And the fix the message asks for actually satisfies it — a gate whose
        complaint cannot be answered is a revision loop, not a rule.

        With list text rather than a repeated letter: `slack_chars` is an
        average over the document's own characters, so a fill made of nothing
        but wide ones spends the page faster than the room it was counted
        against and lands back on the page gate. Real fills are lists and
        sentences, which is what it was averaged over."""
        lines = [
            "Cours : [liste de cours]",
            "Competences : [liste de competences]",
        ] + [f"Ligne {n} du document" for n in range(44)]
        plan = build_plan("fr", data=_crowded(lines))
        share = -(-plan.target // len(plan.open))
        items = "Bases de donnees, Analyse de donnees, Statistiques, Python, SQL, Docker, "
        artifact = {
            "fills": [
                {"slot": slot.key, "text": (items * 6)[: len(slot.token) + share]}
                for slot in plan.open
            ]
        }

        assert hard_check(artifact, plan) == ""

    def test_both_gates_carry_a_hard_check_now(self):
        """The letter gained one: it is fully generated prose, which is where
        the wrong language was most likely to survive in the first place."""
        gates = self._gates(self._team())

        assert gates["resume_agent"]._hard_check is not None
        assert gates["cover_letter_agent"]._hard_check is not None

    def test_the_letter_gate_rejects_the_wrong_language(self):
        """The same detector, over the same thing: the blanks this run wrote.
        The letterhead around them is the candidate's and is not scored."""
        gates = self._gates(self._team("fr"))
        plan = _letters("fr")
        opening = next(slot for slot in plan.open if "opening" in slot.token)
        letter = {
            "fills": [
                {
                    "slot": opening.key,
                    "text": "I am writing to you about the internship that you posted.",
                }
            ]
        }

        assert "still has English in it" in gates["cover_letter_agent"]._hard_check(letter)

    def test_the_letter_gate_does_not_score_pythons_own_fills(self):
        """The date and the employer's name were filled from the record, in the
        run's language or in nobody's. Failing a French letter because its
        employer is called "Nimbus Labs" would be unwinnable."""
        plan = build_letter_plan("fr", company="Nimbus Data Labs")

        assert plan.auto
        assert hard_check({"fills": []}, plan).count("left unfilled") >= 1
        assert "still has English in it" not in hard_check({"fills": []}, plan)

    @pytest.mark.asyncio
    async def test_each_critic_is_shown_its_own_finished_document(self):
        """The Critic reads JSON, and a list of fills is unreadable as a résumé
        or as a letter — it would be scoring fragments with nothing to compare
        them to. So each is shown the page as it will read, with the filled
        lines marked, and neither is shown the other's."""
        from tinternship_backend.agents.applying import (
            COVER_LETTER_STATE_KEY,
            RESUME_STATE_KEY,
        )

        letter_plan = _letters()
        opening = next(slot for slot in letter_plan.open if "opening" in slot.token)

        class Ctx:
            state = {
                RESUME_STATE_KEY: {"fills": [{"slot": "s0", "text": "Stage Data"}]},
                COVER_LETTER_STATE_KEY: {
                    "fills": [{"slot": opening.key, "text": "Votre offre m'intéresse."}]
                },
            }

        critics = applying_critics(self._team())

        resume_critic = await critics["resume_agent"].instruction(Ctx())
        letter_critic = await critics["cover_letter_agent"].instruction(Ctx())

        assert "The résumé as it will actually read" in resume_critic
        assert "Objectif : Stage Data chez" in resume_critic
        assert "The cover letter as it will actually read" in letter_critic
        assert "Votre offre m'intéresse." in letter_critic
        assert "Objectif : Stage Data chez" not in letter_critic


def _crowded(lines: list[str]) -> bytes:
    """A document with almost no room left on its page."""
    import io

    from docx import Document

    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
