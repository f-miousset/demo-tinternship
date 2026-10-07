"""The Account endpoint reports the proxy's identity, and one setup state.

The app authenticates nobody — Authelia does, and hands the result down as
`Remote-*` headers. What matters here is that we read them without inventing an
identity when they are absent (local dev), and that "setup complete" means the
same thing to `/api/account` and to `/api/config`, since the second one is what
holds a half-configured account on the Account page.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.agents.schemas import MasterProfile
from tinternship_backend.db.models import PromptKind
from tinternship_backend.main import create_app
from tinternship_backend.services import profile_store, prompt_store


def _write_lists() -> None:
    """The two lists the résumé's blanks are filled from, which setup requires.

    Required since 2026-08-29 for the same reason the base documents are: a
    coursework or skills blank with no list behind it leaves the Tailor choosing
    between an unfinished sentence and an invented qualification. One row per
    item, carrying both languages, since 2026-09-08.
    """
    from tinternship_backend.services import candidate_lists

    candidate_lists.add("course", en="Machine Learning", fr="Apprentissage automatique")
    candidate_lists.add("skill", en="Python", fr="Python")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_authelia_headers_become_the_signed_in_user(client: TestClient):
    response = client.get(
        "/api/account",
        headers={
            "Remote-User": "alex",
            "Remote-Name": "Alex Martin",
            "Remote-Email": "alex.martin@example.org",
            "Remote-Groups": "admins, users",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["authenticated"] is True
    assert body["username"] == "alex"
    assert body["display_name"] == "Alex Martin"
    assert body["email"] == "alex.martin@example.org"
    assert body["groups"] == ["admins", "users"]


def test_no_proxy_headers_means_not_signed_in(client: TestClient):
    body = client.get("/api/account").json()

    assert body["authenticated"] is False
    assert body["username"] == ""
    assert body["groups"] == []


def test_setup_is_only_complete_once_every_artifact_exists(
    client: TestClient, base_documents_installed
):
    def states() -> tuple[dict, dict]:
        return (
            client.get("/api/account").json()["setup"],
            client.get("/api/config").json()["progress"],
        )

    setup, progress = states()
    assert setup["complete"] is False
    assert setup == progress
    # The fixture uploaded all four documents; the two kinds are their own
    # steps, because "the app has the CV it sends" and "the app has the letter
    # it sends" are different states and each blocks an application on its own.
    assert setup["has_base_resumes"] is True
    assert setup["has_base_letters"] is True

    profile_store.save_profile(MasterProfile(full_name="Alex Martin"))
    _write_lists()
    prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="brief")
    setup, progress = states()
    assert setup == progress
    assert setup["has_profile"] and setup["has_brief"]
    assert setup["complete"] is False, "the playbook is still missing"

    prompt_store.save_prompt(PromptKind.PLAYBOOK, content="playbook")
    setup, progress = states()
    assert setup == progress
    assert setup["complete"] is True


def test_an_untouched_interview_is_a_step_still_to_do(client: TestClient):
    """The interview is its own step of the page, so it needs its own flag —
    taken from the session rather than from the brief, or it would tick before
    anyone had said anything."""
    assert client.get("/api/config").json()["progress"]["has_interview"] is False


def test_the_interview_step_ticks_when_the_interrogator_has_answered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """A question typed into the box is not an interview; a reply to it is."""
    from google.genai import types

    from tinternship_backend.services import onboarding

    class Event:
        def __init__(self, author: str, text: str):
            self.author = author
            self.partial = False
            self.content = types.Content(role="model", parts=[types.Part(text=text)])

    class Session:
        def __init__(self, *events: Event):
            self.events = list(events)

    def session_of(*events: Event):
        async def fake(*_args, **_kwargs):
            return Session(*events)

        return fake

    monkeypatch.setattr(onboarding, "get_session", session_of(Event("user", "hello?")))
    assert client.get("/api/config").json()["progress"]["has_interview"] is False

    monkeypatch.setattr(
        onboarding,
        "get_session",
        session_of(Event("user", "hello?"), Event("interrogator", "From when, and where?")),
    )
    assert client.get("/api/config").json()["progress"]["has_interview"] is True


def test_completeness_does_not_depend_on_the_interview_session_surviving(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, base_documents_installed
):
    """Starting the interview over deletes the session. The brief and playbook
    it produced still exist, so the app must not lock itself back down."""
    from tinternship_backend.services import onboarding

    async def no_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(onboarding, "get_session", no_session)
    profile_store.save_profile(MasterProfile(full_name="Alex Martin"))
    _write_lists()
    prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="brief")
    prompt_store.save_prompt(PromptKind.PLAYBOOK, content="playbook")

    progress = client.get("/api/config").json()["progress"]

    assert progress["has_interview"] is False
    assert progress["complete"] is True
