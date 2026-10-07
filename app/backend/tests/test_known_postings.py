"""A second Investigator run adds to the list; it does not rebuild it.

Two halves, and only one of them is a promise. `tools/persistence.py` is the
promise — it never deletes a posting and a re-found one updates its own row —
and `test_persistence.py` owns that. This file owns the request: the postings
already saved are named in the three instructions that decide what a run goes
looking for, so the run spends its slots on postings the candidate has not seen.
"""

from __future__ import annotations

from tinternship_backend.agents.investigator import (
    build_matcher,
    build_normaliser,
    build_query_planner,
    build_scout,
)
from tinternship_backend.services.context_blocks import (
    KNOWN_POSTINGS_LIMIT,
    known_postings_block,
)
from tinternship_backend.tools.persistence import save_job_postings

HEADING = "# Already on the candidate's list"


class Ctx:
    """The ReadonlyContext an instruction is rendered against."""

    state: dict[str, object] = {}


def save(title: str, company: str = "Acme", **fields: object) -> None:
    save_job_postings(
        [
            {
                "title": title,
                "company": company,
                "url": f"https://{company.lower().replace(' ', '')}.com/jobs/{title[:6]}",
                **fields,
            }
        ]
    )


class TestTheBlock:
    def test_an_empty_list_renders_nothing(self):
        # A new account has saved nothing, and `compose` drops an empty block —
        # so the first run reads exactly as it did before this existed.
        assert known_postings_block() == ""

    def test_every_saved_posting_is_named_with_its_link(self):
        save("ML Intern", "Mistral AI")
        save("Data Scientist", "Criteo")
        block = known_postings_block()
        assert HEADING in block
        for fragment in ("Mistral AI", "ML Intern", "Criteo", "Data Scientist", "https://"):
            assert fragment in block

    def test_a_dismissed_posting_is_listed_and_marked(self):
        # Rejected is not the same as duplicate: the candidate answered. It has
        # to stay in the list — dropping it is how a run brings it back.
        save("Rejected Intern")
        save_job_postings(
            [
                {
                    "title": "Rejected Intern",
                    "company": "Acme",
                    "url": "https://acme.com/jobs/Reject",
                    "url_status": "dead",
                }
            ]
        )
        block = known_postings_block()
        assert "Rejected Intern" in block
        assert "`[rejected]`" in block

    def test_a_validated_posting_is_listed_and_marked(self):
        # The other kind of answer. An application is already on the Tracker, so
        # re-proposing the posting behind it is a slot spent on a decision the
        # candidate made — and the mark is distinct from `[rejected]` because
        # the two verdicts are opposite ones.
        save("Applied Intern")
        from fastapi.testclient import TestClient

        from tinternship_backend.main import create_app

        client = TestClient(create_app())
        job_id = client.get("/api/jobs", params={"view": "all"}).json()["jobs"][0]["id"]
        client.post("/api/applications", json={"job_posting_id": job_id})

        block = known_postings_block()
        assert "Applied Intern" in block
        assert "`[applied]`" in block
        assert "`[rejected]`" not in block.split("\n- ", 1)[1]

    def test_a_trashed_application_is_listed_and_marked_apart(self):
        # The third answer, and it needs its own mark: `[applied]` would tell
        # the model the candidate is tracking a posting they have given up on,
        # and `[rejected]` would lose that they looked at it properly first.
        save("Given Up Intern")
        from fastapi.testclient import TestClient

        from tinternship_backend.main import create_app

        client = TestClient(create_app())
        job_id = client.get("/api/jobs", params={"view": "all"}).json()["jobs"][0]["id"]
        application = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        client.post(f"/api/applications/{application['id']}/trash")

        block = known_postings_block()
        assert "Given Up Intern" in block
        assert "`[trashed]`" in block
        assert "`[applied]`" not in block.split("\n- ", 1)[1]

    def test_the_list_is_capped_and_says_so(self):
        for index in range(5):
            save(f"Role {index}")
        block = known_postings_block(limit=3)
        assert "3 most recently found of 5" in block
        assert block.count("\n- ") == 3

    def test_the_cap_leaves_room_for_several_runs(self):
        # A run returns at most MAX_RESULTS (40) postings, so the cap has to be
        # a multiple of that or a run starts re-finding what fell off the list.
        assert KNOWN_POSTINGS_LIMIT >= 120


class TestTheWiring:
    async def test_the_three_deciding_stages_carry_the_list(self):
        save("ML Intern", "Mistral AI")
        for instruction in (
            await build_query_planner(15).instruction(Ctx()),
            await build_scout(15).instruction(Ctx()),
            await build_matcher(15).instruction(Ctx()),
        ):
            assert HEADING in instruction
            assert "Mistral AI" in instruction

    async def test_the_normaliser_is_left_out(self):
        # It de-duplicates one run's leads against each other and gets the
        # cheapest model; the exclusion is enforced either side of it, by the
        # Scout that never reports the lead and the Matcher that never ranks it.
        save("ML Intern", "Mistral AI")
        assert HEADING not in await build_normaliser().instruction(Ctx())

    async def test_each_stage_is_told_what_to_do_with_the_list(self):
        save("ML Intern", "Mistral AI")
        assert "Never write a query aimed at a posting on it." in await build_query_planner(
            15
        ).instruction(Ctx())
        assert "is not a lead" in await build_scout(15).instruction(Ctx())
        matcher = await build_matcher(15).instruction(Ctx())
        assert "Drop the postings the candidate already has" in matcher
        # Both verdicts are named where the decision is actually made.
        assert "`[rejected]` or `[applied]`" in matcher

    async def test_nothing_saved_leaves_the_instructions_alone(self):
        for instruction in (
            await build_query_planner(15).instruction(Ctx()),
            await build_scout(15).instruction(Ctx()),
            await build_matcher(15).instruction(Ctx()),
        ):
            assert HEADING not in instruction
