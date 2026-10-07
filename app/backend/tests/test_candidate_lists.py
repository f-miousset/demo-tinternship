"""The two lists the résumé's blanks are filled from, in both languages.

Courses and skills, written by the candidate one item at a time. They replaced a
single free-text "further background" box on 2026-08-29, and the reason is half
of what these tests are about: the coursework and skills blanks are filled by
**selecting**, and you cannot select from prose.

The other half is 2026-09-08. Until then they were two text boxes of their own,
one item per line, written once in whichever language the candidate thought in —
their courses in French, their skills in English. So every run had to translate
one list or the other *inside a blank measured in characters*, differently each
time, with nobody able to check the result. Each item carries both spellings
now, a run is shown only its own language, and the fill is a copy.

Which is why "both sides are required" and "the block never carries the other
language" are tested as hard as the gate is: a fallback to the other side would
put a French course on an English CV silently, and that is the failure this
whole change exists to remove.
"""

from __future__ import annotations

import pytest
from conftest import applying_critics, applying_producers, build_letter_plan, build_plan
from fastapi.testclient import TestClient

from tinternship_backend.agents.applying import build_applying_team
from tinternship_backend.main import app
from tinternship_backend.services import candidate_lists, onboarding
from tinternship_backend.services.context_blocks import candidate_lists_block

COURSE = {"en": "Operations Research and Combinatorial Optimisation",
          "fr": "Recherche opérationnelle, optimisation combinatoire"}
SKILL = {"en": "Data Analysis", "fr": "Analyse de données"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _add(client: TestClient, kind: str, item: dict[str, str]) -> dict:
    response = client.post("/api/profile/lists", json={"kind": kind, **item})
    assert response.status_code == 200, response.text
    return response.json()


def _both(client: TestClient) -> None:
    _add(client, "course", COURSE)
    _add(client, "skill", SKILL)


class TestStoringThem:
    def test_an_item_is_saved_in_both_languages(self, client):
        body = _add(client, "course", COURSE)

        assert body["item"]["en"] == COURSE["en"]
        assert body["item"]["fr"] == COURSE["fr"]

    def test_every_write_answers_with_both_lists(self, client):
        """One request, one source of truth: the browser writes the response
        into its cache rather than refetching, so a stale list cannot survive an
        add. Both kinds come back, not only the one that changed."""
        body = _add(client, "skill", SKILL)

        assert set(body["lists"]) == {"course", "skill"}
        assert body["lists"]["skill"][0]["en"] == SKILL["en"]

    def test_items_keep_the_order_they_were_added_in(self, client):
        for index in range(3):
            _add(client, "skill", {"en": f"Skill {index}", "fr": f"Compétence {index}"})

        saved = client.get("/api/profile/lists").json()["lists"]["skill"]

        assert [item["en"] for item in saved] == ["Skill 0", "Skill 1", "Skill 2"]

    def test_one_list_does_not_touch_the_other(self, client):
        _both(client)
        _add(client, "course", {"en": "Probability", "fr": "Probabilités"})

        lists = client.get("/api/profile/lists").json()["lists"]

        assert len(lists["course"]) == 2
        assert len(lists["skill"]) == 1

    def test_an_item_can_be_corrected(self, client):
        """Not a secondary path. The migration seeded every old line into both
        languages, so the list arrives full of items whose other half is still
        to be written, and this is where that work happens."""
        item = _add(client, "course", {"en": "Probabilités", "fr": "Probabilités"})["item"]

        body = client.patch(
            f"/api/profile/lists/{item['id']}",
            json={"en": "Probability", "fr": "Probabilités"},
        )

        assert body.status_code == 200
        assert body.json()["lists"]["course"][0]["en"] == "Probability"

    def test_an_item_can_be_removed(self, client):
        item = _add(client, "skill", SKILL)["item"]

        body = client.delete(f"/api/profile/lists/{item['id']}")

        assert body.status_code == 200
        assert body.json()["lists"]["skill"] == []

    def test_they_do_not_collide_with_the_extracted_skills(self, client):
        """`profile.data["skills"]` is what an extractor summarised. This is the
        menu the candidate curated, and conflating the two would let a summary
        decide what may go on their CV — which is why they are not even on the
        same row any more."""
        from tinternship_backend.services.profile_store import profile_as_dict

        _add(client, "skill", SKILL)

        assert "skills_pool" not in profile_as_dict()


class TestBothLanguagesAreRequired:
    def test_an_item_with_one_side_missing_is_refused(self, client):
        """The whole point of the table. A missing side would have to fall back
        to the other one, which puts the wrong language on the page silently."""
        response = client.post(
            "/api/profile/lists", json={"kind": "course", "en": "Probability", "fr": "  "}
        )

        assert response.status_code == 400
        assert "French" in response.json()["detail"]

    def test_a_correction_cannot_empty_a_side_either(self, client):
        item = _add(client, "skill", SKILL)["item"]

        response = client.patch(f"/api/profile/lists/{item['id']}", json={"en": "", "fr": "SQL"})

        assert response.status_code == 400
        assert client.get("/api/profile/lists").json()["lists"]["skill"][0]["en"] == SKILL["en"]

    def test_the_same_word_twice_is_fine(self, client):
        """Most skills are: Python is Python. Storing it twice is a fact about
        the item, not a licence to fall back when one side is missing."""
        body = _add(client, "skill", {"en": "Python", "fr": "Python"})

        assert body["item"]["en"] == body["item"]["fr"] == "Python"

    def test_a_pasted_list_is_refused_rather_than_saved_as_one_item(self, client):
        """The old box took a whole list; this one takes an item. Saving the
        paste would put "Python\\nSQL\\nDocker" on a single résumé line."""
        response = client.post(
            "/api/profile/lists",
            json={"kind": "skill", "en": "Python\nSQL\nDocker", "fr": "Python\nSQL\nDocker"},
        )

        assert response.status_code == 400
        assert "one item at a time" in response.json()["detail"].lower()

    def test_the_same_item_twice_is_refused(self, client):
        """A duplicate is not a harmless extra row: it is the same course twice
        on one coursework line, in front of an employer."""
        _add(client, "course", COURSE)

        response = client.post("/api/profile/lists", json={"kind": "course", **COURSE})

        assert response.status_code == 400
        assert "already on the list" in response.json()["detail"]

    def test_an_unknown_list_is_refused(self, client):
        response = client.post(
            "/api/profile/lists", json={"kind": "hobbies", "en": "Chess", "fr": "Échecs"}
        )

        assert response.status_code == 400


class TestTheyGateSetup:
    @pytest.mark.asyncio
    async def test_setup_is_incomplete_without_them(self, client, base_documents_installed):
        from tinternship_backend.agents.schemas import MasterProfile
        from tinternship_backend.services import profile_store

        profile_store.save_profile(MasterProfile(full_name="Alex Martin"))

        assert (await onboarding.setup_state())["has_lists"] is False

    @pytest.mark.asyncio
    async def test_one_of_the_two_is_not_enough(self, client):
        _add(client, "course", COURSE)

        assert (await onboarding.setup_state())["has_lists"] is False

    @pytest.mark.asyncio
    async def test_both_together_are(self, client):
        _both(client)

        assert (await onboarding.setup_state())["has_lists"] is True


class TestTheyReachTheAgentsInOneLanguage:
    def test_the_block_carries_both_lists(self, client):
        _both(client)

        block = candidate_lists_block("en")

        assert COURSE["en"] in block
        assert SKILL["en"] in block

    def test_a_french_run_is_shown_the_french_wording(self, client):
        _both(client)

        block = candidate_lists_block("fr")

        assert COURSE["fr"] in block
        assert SKILL["fr"] in block

    def test_the_other_language_is_not_in_the_block_at_all(self, client):
        """Not even as a hint. A model handed both spellings picks between them,
        and asking the candidate for both was to take that choice away."""
        _both(client)

        assert COURSE["en"] not in candidate_lists_block("fr")
        assert COURSE["fr"] not in candidate_lists_block("en")

    def test_it_tells_the_model_to_copy_rather_than_translate(self, client):
        _both(client)

        block = candidate_lists_block("en")

        assert "Copy the wording exactly" in block
        assert "select, never invent" in block

    def test_an_empty_pair_produces_no_block_at_all(self):
        assert candidate_lists_block("en") == ""

    @pytest.mark.asyncio
    async def test_both_producers_and_both_critics_are_given_them(self, client):
        """The Tailor picks from them; the Cover Letter agent has room to use
        what a one-page CV cannot; and a Critic without them cannot tell a
        selected course from an invented one — or from a translated one."""
        _both(client)
        team = build_applying_team(
            job_id=0, resume_plan=build_plan("fr"), letter_plan=build_letter_plan("fr")
        )

        class Ctx:
            state: dict = {}

        for member in {**applying_producers(team), **applying_critics(team)}.values():
            instruction = await member.instruction(Ctx())
            assert COURSE["fr"] in instruction, member.name
            assert COURSE["en"] not in instruction, member.name


class TestTheServiceDirectly:
    def test_in_language_falls_back_to_nothing_rather_than_the_other_side(self, client):
        """Belt and braces: the API refuses a half-written item, so this cannot
        normally happen. If one ever does exist, the list is one item shorter —
        which is recoverable — rather than one item wrong, which is not."""
        _add(client, "course", COURSE)
        with_hole = candidate_lists.all_items()["course"][0]["id"]
        from sqlmodel import select

        from tinternship_backend.db.engine import session_scope
        from tinternship_backend.db.models import CandidateListItem

        with session_scope() as session:
            row = session.exec(
                select(CandidateListItem).where(CandidateListItem.id == with_hole)
            ).one()
            row.en = ""
            session.add(row)

        assert candidate_lists.in_language("course", "en") == []
        assert candidate_lists.in_language("course", "fr") == [COURSE["fr"]]
