"""Deleting a posting forever, from either trash.

The two trashes keep everything so they can be undone; this is the step past
them. Three things must hold, and the third is the one that fails quietly:

1. Only something already in a trash can be deleted — never a live card.
2. Everything is erased: the content, the application, its timeline, its
   documents and their exported files.
3. The posting stays **answered**. A tombstone row survives so the next
   Investigator run cannot find it and put it back in the deck.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select

from tinternship_backend.config import get_settings
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    JobPosting,
    utcnow,
)
from tinternship_backend.main import create_app
from tinternship_backend.services import flows
from tinternship_backend.services.context_blocks import known_postings_block
from tinternship_backend.tools.persistence import (
    partition_answered,
    paste_key,
    save_job_postings,
)

client = TestClient(create_app())


def save(title: str, company: str = "Acme") -> int:
    url = f"https://{company.lower()}.example/jobs/{title.replace(' ', '-')}"
    save_job_postings(
        [
            {
                "title": title,
                "company": company,
                "url": url,
                "url_status": "ok",
                "description": "A long description of the role.",
                "fit_score": 8.0,
            }
        ]
    )
    with session_scope() as session:
        return int(session.exec(select(JobPosting).where(JobPosting.url == url)).one().id)


def as_found(title: str, company: str = "Acme") -> dict[str, str]:
    """The same posting, as a later Investigator run would return it."""
    return {
        "title": title,
        "company": company,
        "url": f"https://{company.lower()}.example/jobs/{title.replace(' ', '-')}",
    }


def titles(view: str) -> list[str]:
    return [job["title"] for job in client.get("/api/jobs", params={"view": view}).json()["jobs"]]


def tracked_and_trashed(title: str) -> tuple[int, int, str]:
    """A posting with an application, a timeline, a document and its file — trashed."""
    job_id = save(title)
    application_id = client.post("/api/applications", json={"job_posting_id": job_id}).json()["id"]
    exported = get_settings().artifacts_path / f"{title.replace(' ', '-')}.docx"
    exported.parent.mkdir(parents=True, exist_ok=True)
    exported.write_bytes(b"docx")
    with session_scope() as session:
        session.add(
            ApplicationArtifact(
                application_id=application_id,
                kind="resume",
                content={"text": "x"},
                rendered_path=str(exported),
            )
        )
        application = session.get(Application, application_id)
        application.trashed_at = utcnow()
        session.add(application)
    return job_id, application_id, str(exported)


class TestTheDecksTrash:
    def test_a_posting_in_the_trash_is_deleted_and_vanishes_from_every_list(self):
        job_id = save("Gone")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        response = client.delete(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        assert response.json()["deleted"] == 1
        assert titles("discarded") == [] and titles("all") == [] and titles("deck") == []
        assert client.get(f"/api/jobs/{job_id}").status_code == 404

    def test_a_posting_still_in_the_deck_cannot_be_deleted(self):
        job_id = save("Still deciding")
        assert client.delete(f"/api/jobs/{job_id}").status_code == 409
        assert titles("deck") == ["Still deciding"]

    def test_a_posting_on_the_tracker_cannot_be_deleted_from_here(self):
        job_id = save("Tracked")
        client.post("/api/applications", json={"job_posting_id": job_id})
        with session_scope() as session:
            posting = session.get(JobPosting, job_id)
            posting.dismissed = True
            session.add(posting)
        assert client.delete(f"/api/jobs/{job_id}").status_code == 409

    def test_the_content_is_erased_but_the_identity_is_kept(self):
        job_id = save("Erased")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})
        client.delete(f"/api/jobs/{job_id}")
        with session_scope() as session:
            posting = session.get(JobPosting, job_id)
            assert posting.purged_at is not None and posting.dismissed is True
            assert posting.description == "" and posting.fit_score == 0.0
            assert posting.title == "Erased" and posting.url

    def test_emptying_the_trash_leaves_the_deck_alone(self):
        for title in ("One", "Two"):
            client.post(f"/api/jobs/{save(title)}/dismiss", params={"dismissed": True})
        save("Keep")

        assert client.delete("/api/jobs/trash").json()["deleted"] == 2
        assert titles("discarded") == [] and titles("deck") == ["Keep"]


class TestTheTrackersTrash:
    def test_everything_the_application_carried_is_erased_files_included(self):
        job_id, application_id, exported = tracked_and_trashed("Given up")

        response = client.delete(f"/api/applications/{application_id}")

        assert response.status_code == 200
        assert response.json() == {"deleted": 1, "files": 1}
        with session_scope() as session:
            assert session.exec(select(Application)).all() == []
            assert session.exec(select(ApplicationEvent)).all() == []
            assert session.exec(select(ApplicationArtifact)).all() == []
            assert session.get(JobPosting, job_id).purged_at is not None
        assert not (get_settings().artifacts_path / exported).exists()
        assert client.get("/api/applications", params={"view": "trashed"}).json() == {
            "applications": []
        }

    def test_an_application_on_the_board_cannot_be_deleted(self):
        job_id = save("On the board")
        application_id = client.post("/api/applications", json={"job_posting_id": job_id}).json()[
            "id"
        ]
        assert client.delete(f"/api/applications/{application_id}").status_code == 409

    def test_emptying_the_trash_leaves_the_board_alone(self):
        tracked_and_trashed("Thrown A")
        tracked_and_trashed("Thrown B")
        client.post("/api/applications", json={"job_posting_id": save("Pursued")})

        assert client.delete("/api/applications/trash").json()["deleted"] == 2
        board = client.get("/api/applications").json()["applications"]
        assert [application["job"]["title"] for application in board] == ["Pursued"]

    def test_a_file_outside_the_exports_directory_is_never_touched(self, tmp_path):
        job_id, application_id, _ = tracked_and_trashed("Outside")
        stray = tmp_path / "not-ours.docx"
        stray.write_bytes(b"keep me")
        with session_scope() as session:
            artifact = session.exec(select(ApplicationArtifact)).one()
            artifact.rendered_path = str(stray)
            session.add(artifact)

        assert client.delete(f"/api/applications/{application_id}").json()["files"] == 0
        assert stray.exists()


class TestItStaysAnswered:
    """The half that would fail silently: a deleted posting must not come back."""

    def test_a_later_run_drops_a_posting_deleted_from_the_decks_trash(self):
        job_id = save("Never again")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})
        client.delete(f"/api/jobs/{job_id}")

        kept, drops = partition_answered([as_found("Never again")])

        assert kept == [] and drops == {"dismissed": 1}

    def test_a_later_run_drops_a_posting_deleted_from_the_trackers_trash(self):
        _, application_id, _ = tracked_and_trashed("Over")
        client.delete(f"/api/applications/{application_id}")

        kept, _ = partition_answered([as_found("Over")])

        assert kept == []

    def test_the_agents_are_still_told_it_was_rejected(self):
        job_id = save("Told")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})
        client.delete(f"/api/jobs/{job_id}")
        assert "[rejected]" in known_postings_block()

    def test_pasting_it_again_brings_it_back_whole(self):
        job_id = save("Second thoughts")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})
        client.delete(f"/api/jobs/{job_id}")

        job = {**as_found("Second thoughts"), "description": "Read again.", "fit_score": 7.0}
        key = paste_key(job["url"])
        save_job_postings([job], pasted_as=key)
        restored_id, was_dismissed, _ = flows._restore_posting(job, key)

        assert restored_id == job_id and was_dismissed is True
        with session_scope() as session:
            posting = session.get(JobPosting, job_id)
            assert posting.purged_at is None and posting.dismissed is False
            assert posting.description == "Read again."
        assert client.get(f"/api/jobs/{job_id}").status_code == 200
