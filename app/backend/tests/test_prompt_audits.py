"""A prompt is served with the score it was given.

The brief and the playbook are audited once, when they are written, and the
verdict used to live only in the response of the run that produced it — so the
scores vanished the moment you reloaded the Account page. They now travel with
the prompt, which means the lookup has to survive the thing that has already
broken it once: a prompt id and an artifact id are both small integers, so
`subject_id` alone puts one artifact's verdict on another's.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import AuditRecord, PromptKind
from tinternship_backend.services import audit, prompt_store


def _audited(subject_kind: str, subject_id: str, overall: float, rubric: str = "") -> None:
    with session_scope() as session:
        session.add(
            AuditRecord(
                subject_kind=subject_kind,
                subject_id=subject_id,
                rubric=rubric,
                overall=overall,
                verdict="pass",
                scores={"criteria": [], "reasoning": "because"},
            )
        )


@pytest.fixture()
def client() -> TestClient:
    from tinternship_backend.main import app

    return TestClient(app)


class TestLatestVerdicts:
    def test_the_newest_verdict_for_a_subject_wins(self):
        _audited("brief", "1", 4.0)
        _audited("brief", "1", 8.5)

        assert audit.latest_verdicts(["brief"])[("brief", "1")]["overall"] == 8.5

    def test_kinds_do_not_borrow_each_others_scores(self):
        """The bug this guards: ids collide across kinds, keys must not."""
        _audited("brief", "2", 9.1)
        _audited("playbook", "2", 5.4)

        verdicts = audit.latest_verdicts(["brief", "playbook"])

        assert verdicts[("brief", "2")]["overall"] == 9.1
        assert verdicts[("playbook", "2")]["overall"] == 5.4

    def test_a_subject_with_no_id_is_not_a_lookup_key(self):
        """In-loop gate verdicts record a run, not a subject — they key on
        `(run_id, kind)` elsewhere and would otherwise collide here as ''."""
        _audited("brief", "", 7.0)

        assert audit.latest_verdicts(["brief"]) == {}


class TestPromptsCarryTheirAudit:
    def test_the_active_prompts_are_served_with_their_scores(self, client: TestClient):
        brief = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="brief")
        playbook = prompt_store.save_prompt(PromptKind.PLAYBOOK, content="playbook")
        # As `flows` files them: the rubric's subject kind, not the prompt kind.
        _audited("brief", str(brief.id), 8.4, rubric="search_brief_v1")
        _audited("playbook", str(playbook.id), 7.2, rubric="playbook_v1")

        body = client.get("/api/strategy/prompts/active").json()

        assert body["search_brief"]["audit"]["overall"] == 8.4
        assert body["search_brief"]["audit"]["rubric"] == "search_brief_v1"
        assert body["search_brief"]["audit"]["scores"]["reasoning"] == "because"
        assert body["playbook"]["audit"]["overall"] == 7.2

    def test_every_version_carries_its_own_score(self, client: TestClient):
        first = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="v1")
        second = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="v2")
        _audited("brief", str(first.id), 6.0)
        _audited("brief", str(second.id), 9.0)

        prompts = client.get("/api/strategy/prompts?kind=search_brief").json()["prompts"]
        by_version = {p["version"]: p["audit"] for p in prompts}

        assert by_version[1]["overall"] == 6.0
        assert by_version[2]["overall"] == 9.0

    def test_a_hand_edited_version_is_served_with_no_score_rather_than_a_stale_one(
        self, client: TestClient
    ):
        """Edits are not re-scored, and inheriting the previous version's verdict
        would claim the Critic had read something it never saw."""
        agent_version = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="v1")
        _audited("brief", str(agent_version.id), 8.4)
        client.put("/api/strategy/prompts/search_brief", json={"content": "edited by hand"})

        active = client.get("/api/strategy/prompts/active").json()["search_brief"]

        assert active["version"] == 2
        assert active["audit"] is None
