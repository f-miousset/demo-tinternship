"""The four verdicts a swipe leaves on a posting, and what the deck does with them.

The Jobs page shows one posting at a time and every gesture is a decision that
gets written down: right and up create an application, left dismisses, down
defers. This file owns what the API must do with each of them — which postings
the deck still offers, in what order, and what comes back out of the trash.

The ordering test is the one that matters most: "put it at the end of the list"
is worth nothing if a reload undoes it, so deferral is stamped on the row rather
than remembered in the browser.

`TestTheTrackerTrash` owns the *fifth* verdict, which is not a swipe: giving up
on an application you already validated. It has its own pile because it throws
away something quite different — a posting you said yes to, with a status, a
timeline and possibly a generated package on it — and the guarantee attached to
it is that none of that is destroyed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import Application
from tinternship_backend.main import create_app
from tinternship_backend.tools.persistence import save_job_postings

client = TestClient(create_app())


def save(title: str, company: str = "Acme", **fields: object) -> int:
    save_job_postings(
        [
            {
                "title": title,
                "company": company,
                "url": f"https://{company.lower().replace(' ', '')}.example/{title}",
                "url_status": "ok",
                **fields,
            }
        ]
    )
    for job in client.get("/api/jobs", params={"view": "all"}).json()["jobs"]:
        if job["title"] == title and job["company"] == company:
            return int(job["id"])
    raise AssertionError(f"{title!r} at {company!r} was not saved")


def deck() -> list[str]:
    return [job["title"] for job in client.get("/api/jobs").json()["jobs"]]


class TestWhatTheDeckOffers:
    def test_an_untouched_posting_is_in_the_deck(self):
        save("Untouched")
        assert deck() == ["Untouched"]

    def test_a_discarded_posting_leaves_the_deck_for_the_trash(self):
        job_id = save("Discarded")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        assert deck() == []
        discarded = client.get("/api/jobs", params={"view": "discarded"}).json()["jobs"]
        assert [job["title"] for job in discarded] == ["Discarded"]

    def test_the_trash_holds_only_the_trash(self):
        # Otherwise the trash screen would show every posting on the list and
        # the "put back" button would sit next to postings that never left.
        save("Untouched")
        job_id = save("Discarded")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        discarded = client.get("/api/jobs", params={"view": "discarded"}).json()["jobs"]
        assert [job["title"] for job in discarded] == ["Discarded"]

    def test_putting_one_back_returns_it_to_the_deck(self):
        job_id = save("Second thoughts")
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": False})

        assert deck() == ["Second thoughts"]

    def test_a_validated_posting_leaves_the_deck(self):
        # Swiping right creates the application; the posting now lives on the
        # Tracker, and showing it again would ask a question already answered.
        job_id = save("Validated")
        client.post("/api/applications", json={"job_posting_id": job_id})

        assert deck() == []
        assert [job["title"] for job in client.get("/api/jobs", params={"view": "all"}).json()["jobs"]] == [
            "Validated"
        ]

    def test_an_unknown_view_is_refused_rather_than_guessed(self):
        assert client.get("/api/jobs", params={"view": "everything"}).status_code == 400


class TestDeferral:
    def test_a_deferred_posting_goes_behind_every_undecided_one(self):
        # Even though it scores higher: "not now" outranks the match, which is
        # the whole point of the gesture.
        job_id = save("Deferred", fit_score=9.5)
        save("Untouched", company="Beta", fit_score=4.0)

        client.post(f"/api/jobs/{job_id}/defer")

        assert deck() == ["Untouched", "Deferred"]

    def test_the_longest_deferred_posting_comes_back_first(self):
        first = save("First deferred", fit_score=1.0)
        second = save("Second deferred", company="Beta", fit_score=9.0)

        client.post(f"/api/jobs/{first}/defer")
        client.post(f"/api/jobs/{second}/defer")

        assert deck() == ["First deferred", "Second deferred"]

    def test_deferral_survives_a_reload(self):
        # The reason it is a column and not a piece of component state: a swipe
        # the browser forgets on refresh is not a decision, it is a scroll.
        job_id = save("Deferred", fit_score=9.5)
        save("Untouched", company="Beta", fit_score=4.0)
        client.post(f"/api/jobs/{job_id}/defer")

        assert deck() == ["Untouched", "Deferred"]
        assert deck() == ["Untouched", "Deferred"]

    def test_deferring_a_posting_that_does_not_exist_is_a_404(self):
        assert client.post("/api/jobs/9999/defer").status_code == 404


class TestPinning:
    def test_swiping_up_creates_the_application_pinned(self):
        job_id = save("Favourite")
        created = client.post(
            "/api/applications", json={"job_posting_id": job_id, "pinned": True}
        ).json()

        assert created["pinned"] is True
        assert created["status"] == "saved"

    def test_swiping_right_creates_it_unpinned(self):
        job_id = save("Ordinary")
        created = client.post("/api/applications", json={"job_posting_id": job_id}).json()

        assert created["pinned"] is False

    def test_pinning_a_posting_already_tracked_pins_the_application_it_has(self):
        # `POST /api/applications` is idempotent, but a pin arriving on the
        # second call is the candidate saying so rather than a duplicate call.
        job_id = save("Already tracked")
        first = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        second = client.post(
            "/api/applications", json={"job_posting_id": job_id, "pinned": True}
        ).json()

        assert second["id"] == first["id"]
        assert second["pinned"] is True

    def test_a_pin_can_be_taken_back(self):
        job_id = save("Regret")
        application = client.post(
            "/api/applications", json={"job_posting_id": job_id, "pinned": True}
        ).json()

        unpinned = client.patch(
            f"/api/applications/{application['id']}", json={"pinned": False}
        ).json()
        assert unpinned["pinned"] is False

    def test_a_pin_survives_a_status_change(self):
        # It sorts the card to the top of whatever column it is in, so moving
        # across the board must not quietly clear it.
        job_id = save("Promoted")
        application = client.post(
            "/api/applications", json={"job_posting_id": job_id, "pinned": True}
        ).json()

        moved = client.patch(
            f"/api/applications/{application['id']}", json={"status": "hr_interview"}
        ).json()
        assert moved["status"] == "hr_interview"
        assert moved["pinned"] is True


class TestTheLanguageAnApplicationOpensIn:
    """You answer a posting in the language it was advertised in.

    The swipe shares this with the paste, which is the point of it being on
    `track_posting` rather than in either caller: the picker on the application
    page opens on the same guess however the application was created, and the
    paste path — where nobody is asked at all — cannot disagree with the deck.
    """

    def test_a_french_posting_makes_a_french_application(self):
        job_id = save(
            "Stage Data Scientist",
            description=(
                "Au sein de notre équipe Data, vous participerez à la conception et à la "
                "mise en production de modèles de Machine Learning."
            ),
        )
        created = client.post("/api/applications", json={"job_posting_id": job_id}).json()

        assert created["language"] == "fr"

    def test_an_english_posting_makes_an_english_application(self):
        job_id = save(
            "ML Research Intern",
            description=(
                "You will join the perception team and work on representation learning "
                "for our robotics stack, supervised by a senior researcher."
            ),
        )
        created = client.post("/api/applications", json={"job_posting_id": job_id}).json()

        assert created["language"] == "en"

    def test_a_second_swipe_does_not_re_guess_a_language_already_chosen(self):
        # An application that exists may have been generated in a language the
        # candidate picked by hand — `POST /generate` stores what they chose.
        # Re-guessing on a later call would overwrite that silently, which is the
        # worst way to be wrong about this, so the guess is made on creation only.
        job_id = save(
            "Stage Ingénieur",
            description="Vous rejoindrez notre équipe pour travailler sur nos modèles.",
        )
        created = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        assert created["language"] == "fr"

        with session_scope() as session:
            application = session.get(Application, created["id"])
            application.language = "en"
            session.add(application)

        again = client.post("/api/applications", json={"job_posting_id": job_id}).json()

        assert again["id"] == created["id"]
        assert again["language"] == "en"


class TestTheTrackerTrash:
    """Giving up on an application you already validated.

    The deck's trash and this one are not the same pile. Swiping left throws
    away a posting you looked at for four seconds; this throws away one you
    said yes to, worked on, and possibly applied to. So it lives on the
    Tracker, it keeps everything, and it is reversible in one tap.
    """

    def track(self, title: str = "Tracked") -> int:
        job_id = save(title)
        return int(
            client.post("/api/applications", json={"job_posting_id": job_id}).json()["id"]
        )

    def board(self) -> list[int]:
        return [
            application["id"]
            for application in client.get("/api/applications").json()["applications"]
        ]

    def trash(self) -> list[int]:
        return [
            application["id"]
            for application in client.get(
                "/api/applications", params={"view": "trashed"}
            ).json()["applications"]
        ]

    def test_trashing_takes_it_off_the_board_and_puts_it_in_the_trash(self):
        application_id = self.track()

        client.post(f"/api/applications/{application_id}/trash")

        assert self.board() == []
        assert self.trash() == [application_id]

    def test_putting_it_back_returns_it_to_the_board(self):
        application_id = self.track()
        client.post(f"/api/applications/{application_id}/trash")

        client.post(f"/api/applications/{application_id}/trash", params={"trashed": False})

        assert self.board() == [application_id]
        assert self.trash() == []

    def test_the_trash_keeps_everything_the_application_had(self):
        # The whole promise. A trashed application is not a deleted one: the
        # status it reached, the timeline that got it there, the standing note
        # and the personalisation are all still on the row, which is what makes
        # putting it back a restoration rather than a re-creation.
        application_id = self.track()
        client.patch(
            f"/api/applications/{application_id}",
            json={"status": "applied", "note": "Sent through their form.", "pinned": True},
        )
        client.patch(f"/api/applications/{application_id}", json={"notes": "Ask about the team."})

        client.post(f"/api/applications/{application_id}/trash")

        kept = client.get(f"/api/applications/{application_id}").json()
        assert kept["status"] == "applied"
        assert kept["pinned"] is True
        assert kept["notes"] == "Ask about the team."
        assert [entry["note"] for entry in kept["timeline"]] == [
            "Saved from the deck.",
            "Sent through their form.",
        ]
        assert kept["job"]["title"] == "Tracked"
        assert kept["trashed_at"]

    def test_it_goes_back_into_the_column_it_left(self):
        application_id = self.track()
        client.patch(f"/api/applications/{application_id}", json={"status": "hr_interview"})
        client.post(f"/api/applications/{application_id}/trash")

        restored = client.post(
            f"/api/applications/{application_id}/trash", params={"trashed": False}
        ).json()

        assert restored["status"] == "hr_interview"
        assert restored["trashed_at"] is None

    def test_trashing_writes_no_timeline_event(self):
        # It is not a thing the employer did, and `services/follow_up.py`
        # measures silence from the last event — so an event here would make an
        # application that had been ignored for a month look freshly active the
        # moment it came back out.
        application_id = self.track()
        before = client.get(f"/api/applications/{application_id}").json()["timeline"]

        client.post(f"/api/applications/{application_id}/trash")
        client.post(f"/api/applications/{application_id}/trash", params={"trashed": False})

        assert client.get(f"/api/applications/{application_id}").json()["timeline"] == before

    def test_a_trashed_application_does_not_send_its_posting_back_to_the_deck(self):
        # The verdict was on the posting too. Sending it back would ask a
        # question the candidate has now answered twice.
        application_id = self.track()

        client.post(f"/api/applications/{application_id}/trash")

        assert deck() == []

    def test_validating_the_posting_again_takes_the_application_back_out(self):
        # `POST /api/applications` is idempotent, but asking for a posting whose
        # application is in the trash is the candidate saying so — same reason a
        # pin lands on the second call.
        job_id = save("Second thoughts")
        application_id = client.post(
            "/api/applications", json={"job_posting_id": job_id}
        ).json()["id"]
        client.post(f"/api/applications/{application_id}/trash")

        again = client.post("/api/applications", json={"job_posting_id": job_id}).json()

        assert again["id"] == application_id
        assert again["trashed_at"] is None

    def test_a_trashed_application_is_left_out_of_the_feedback_digest(self):
        # The digest reads what happens to applications actually being pursued.
        # A trashed one's status froze wherever it was when the candidate walked
        # away, so counting it would only dilute the tallies the Investigator is
        # re-steered by. Dismissed postings are already absent for that reason.
        from tinternship_backend.services.feedback import collect_history

        application_id = self.track("Given up")
        client.patch(f"/api/applications/{application_id}", json={"status": "applied"})
        assert collect_history()[1]["total_applied"] == 1

        client.post(f"/api/applications/{application_id}/trash")

        history, stats = collect_history()
        assert history == []
        assert stats["total_tracked"] == 0

    def test_an_unknown_view_is_refused_rather_than_guessed(self):
        assert client.get("/api/applications", params={"view": "everything"}).status_code == 400

    def test_trashing_an_application_that_does_not_exist_is_a_404(self):
        assert client.post("/api/applications/9999/trash").status_code == 404
