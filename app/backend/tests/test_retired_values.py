"""Removing an enum value from a database that already holds it.

`_add_missing_columns` handles a model *gaining* a field. This is the other
half: on 2026-08-28 `screening` left `ApplicationStatus` and `plan` left
`ArtifactKind`, and the user's database — their actual job search — had rows
carrying both. Dropping the value from the enum without touching the rows leaves
an application filed under a column the Tracker no longer draws, and artifacts
wearing a badge no page can open.

**And one that is not an enum value at all: a removed *column*.** The policy is
that `_add_missing_columns` handles no drops, because an unread column costs a
few bytes — but SQLModel maps `field: str = ""` to `VARCHAR NOT NULL` with the
default applied in Python rather than in SQL. So the moment such a field leaves
the model, every INSERT omits it and SQLite rejects the row. Removing the Canva
integration bricked every profile import and every saved artifact on an existing
database while passing this entire suite, because tests build their schema from
the current models and the column was never there to violate.

Also here: `job_block`, which is what makes the removal of the plan agent
survivable. The résumé and the letter now argue from the app's own assessment of
the posting — the summary, the score, the strengths and the risks — because that
assessment is in the prompt rather than only on the card.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import select

from tinternship_backend.db.engine import (
    RETIRED_COLUMNS,
    _retire_removed_values,
    get_engine,
    session_scope,
)
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationStatus,
    ArtifactKind,
    JobPosting,
)
from tinternship_backend.services.context_blocks import job_block


def _application(status: str = ApplicationStatus.SAVED) -> int:
    with session_scope() as session:
        job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus")
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id, status=status)
        session.add(application)
        session.flush()
        return application.id


class TestRetiredValues:
    def test_a_screening_application_becomes_applied(self):
        """The honest reading of a row that carried it: sent, no decision yet.
        Written with raw SQL because the enum no longer has the value — which is
        exactly the situation the migration exists for."""
        application_id = _application()
        with session_scope() as session:
            session.exec(
                text(f"UPDATE application SET status = 'screening' WHERE id = {application_id}")
            )

        _retire_removed_values()

        with session_scope() as session:
            assert session.get(Application, application_id).status == ApplicationStatus.APPLIED

    def test_an_interview_application_becomes_hr_pre_call(self):
        """`interview` was split into four rounds on 2026-10-05; the first round
        is where a row that only said "interviewing" honestly sits. Its
        events keep saying `interview` — they are history."""
        application_id = _application()
        with session_scope() as session:
            session.exec(
                text(f"UPDATE application SET status = 'interview' WHERE id = {application_id}")
            )

        _retire_removed_values()

        with session_scope() as session:
            assert (
                session.get(Application, application_id).status == ApplicationStatus.HR_PRE_CALL
            )

    def test_obsolete_plan_artifacts_are_deleted(self):
        """Nothing renders them and the agent that wrote them is gone, so left
        behind they would put a "plan" badge on Tracker cards for something no
        page can open."""
        application_id = _application()
        with session_scope() as session:
            session.exec(
                text(
                    "INSERT INTO application_artifact "
                    "(application_id, kind, version, content, rendered_path, "
                    " invocation_id, revisions, created_at) "
                    f"VALUES ({application_id}, 'plan', 1, '{{}}', '', '', 0, "
                    "'2026-08-01 00:00:00')"
                )
            )
            session.add(
                ApplicationArtifact(
                    application_id=application_id, kind=ArtifactKind.RESUME, version=1
                )
            )

        _retire_removed_values()

        with session_scope() as session:
            kinds = [
                artifact.kind for artifact in session.exec(select(ApplicationArtifact)).all()
            ]
        assert kinds == [ArtifactKind.RESUME]

    def test_it_is_idempotent_and_silent_when_there_is_nothing_to_do(self):
        """It runs on every boot. The normal case is that it finds nothing."""
        application_id = _application(status=ApplicationStatus.APPLIED)
        _retire_removed_values()
        _retire_removed_values()

        with session_scope() as session:
            assert session.get(Application, application_id).status == ApplicationStatus.APPLIED


class TestJobBlock:
    def test_it_carries_the_apps_own_assessment_and_not_only_the_ad(self):
        """`summary` and `confidence` were on the deck card and missing from the
        prompt until 2026-08-28, so the writers were re-deriving an assessment
        the candidate had already read."""
        with session_scope() as session:
            job = JobPosting(
                dedupe_key="k",
                title="ML Intern",
                company="Nimbus",
                summary="Six months building training pipelines.",
                description="A long description.",
                strengths=["Python and SQL are on the profile"],
                risks=["No PyTorch anywhere in the profile"],
                requirements=["PyTorch"],
                fit_score=7.4,
                fit_rationale="Strong on data engineering, thin on ML frameworks.",
                confidence="high",
                language="en",
                posted_on="2026-08-01",
            )
            session.add(job)
            session.flush()
            job_id = job.id

        block = job_block(job_id)
        for expected in (
            "Six months building training pipelines.",
            "No PyTorch anywhere in the profile",
            "Python and SQL are on the profile",
            "Strong on data engineering, thin on ML frameworks.",
            '"confidence": "high"',
            "2026-08-01",
        ):
            assert expected in block, expected

    def test_a_missing_posting_says_so_rather_than_rendering_an_empty_record(self):
        assert "not found" in job_block(999999)


class TestRetiredColumns:
    """A column a model lost, that is `NOT NULL` in a database already on disk.

    The failure this exists for, verbatim from a real upload on 2026-08-28:

        IntegrityError: NOT NULL constraint failed: profile_source.canva_design_id

    Nothing in the suite could have caught it, because every test database is
    built from the current models. So these tests put the column *back* first.
    """

    @staticmethod
    def _add_column(table: str, column: str) -> None:
        """Recreate a legacy column exactly as SQLModel would have made it."""
        with get_engine().begin() as connection:
            connection.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" VARCHAR NOT NULL DEFAULT \'\'')
            )

    @staticmethod
    def _columns(table: str) -> set[str]:
        from sqlalchemy import inspect

        return {item["name"] for item in inspect(get_engine()).get_columns(table)}

    def test_every_retired_column_is_dropped(self):
        for table, column in RETIRED_COLUMNS:
            self._add_column(table, column)
            assert column in self._columns(table), f"{table}.{column} was not restored"

        _retire_removed_values()

        for table, column in RETIRED_COLUMNS:
            assert column not in self._columns(table), f"{table}.{column} survived"

    def test_an_insert_works_again_afterwards(self):
        """The actual symptom: with the column there, this raises."""
        from tinternship_backend.db.models import ProfileSource

        self._add_column("profile_source", "canva_design_id")
        _retire_removed_values()

        with session_scope() as session:
            session.add(ProfileSource(kind="base_resume", label="cv.docx", language="fr"))

        with session_scope() as session:
            assert session.exec(select(ProfileSource)).one().label == "cv.docx"

    def test_a_profile_insert_works_again_after_the_free_text_box_is_retired(self):
        """The same failure one table over, 2026-08-29. `extra_context` was one
        free-text box replaced by the two curated lists; leaving the column
        behind would make every profile insert fail on an existing database
        while the whole suite stayed green. The lists themselves left the same
        row on 2026-09-08 and are in `RETIRED_COLUMNS` for the same reason."""
        from tinternship_backend.db.models import Profile

        for column in ("extra_context", "courses", "skills_pool"):
            self._add_column("profile", column)
        _retire_removed_values()

        with session_scope() as session:
            session.add(Profile(full_name="Alex Martin", summary="ML student"))

        with session_scope() as session:
            assert session.exec(select(Profile)).one().summary == "ML student"

    def test_it_is_idempotent(self):
        """The normal case is every boot after the first, where there is nothing
        to drop and this must be silent rather than an error."""
        _retire_removed_values()
        _retire_removed_values()

        assert "canva_design_id" not in self._columns("profile_source")


class TestSeedingTheBilingualLists:
    """Two of those retired columns held work, and it is carried out first.

    2026-09-08. `profile.courses` and `profile.skills_pool` were two text boxes
    of one item per line; items are rows carrying both languages now, because
    the Tailor was translating course titles mid-run inside a blank measured in
    characters. Dropping the columns is right — but the live database had
    sixteen course titles and forty skills typed into them, so they are read
    into rows before the drop, with the original wording on **both** sides.

    That is deliberately not a guess at which language each line was in: it is
    what the old behaviour amounted to, except now it is visible on the Account
    page as two fields to check rather than a translation happening inside a
    prompt.
    """

    @staticmethod
    def _add_column(column: str) -> None:
        """Put a legacy column back, exactly as SQLModel would have made it.

        Tolerant of one that is already there: `clean_tables` empties the rows
        between tests but leaves the schema alone, so a column this class adds
        outlives the test that added it.
        """
        from sqlalchemy import inspect

        if column in {item["name"] for item in inspect(get_engine()).get_columns("profile")}:
            return
        with get_engine().begin() as connection:
            connection.execute(
                text(f'ALTER TABLE "profile" ADD COLUMN "{column}" VARCHAR NOT NULL DEFAULT \'\'')
            )

    @staticmethod
    def _write_legacy(courses: str, skills: str) -> None:
        from tinternship_backend.db.models import Profile

        with session_scope() as session:
            session.add(Profile(full_name="Alex Martin"))
        with get_engine().begin() as connection:
            connection.execute(
                text("UPDATE profile SET courses = :courses, skills_pool = :skills"),
                {"courses": courses, "skills": skills},
            )

    def _seed(self, courses: str, skills: str) -> dict:
        from tinternship_backend.db.engine import _seed_candidate_lists
        from tinternship_backend.services import candidate_lists

        self._add_column("courses")
        self._add_column("skills_pool")
        self._write_legacy(courses, skills)
        _seed_candidate_lists()
        return candidate_lists.all_items()

    def test_every_line_becomes_an_item_in_both_languages(self):
        lists = self._seed("Probabilités\nMéthodes statistiques", "Python")

        assert [item["en"] for item in lists["course"]] == [
            "Probabilités",
            "Méthodes statistiques",
        ]
        assert lists["course"][0]["fr"] == "Probabilités"
        assert lists["skill"] == [
            {"id": lists["skill"][0]["id"], "kind": "skill", "en": "Python",
             "fr": "Python", "position": 0}
        ]

    def test_blank_lines_and_repeats_are_dropped(self):
        lists = self._seed("Probabilités\n\n  \nprobabilités\n", "Python\nPython")

        assert len(lists["course"]) == 1
        assert len(lists["skill"]) == 1

    def test_it_does_not_run_twice_over_edited_items(self):
        """The whole point of the page is fixing the seeded wording. A second
        boot must not put `Probabilités` back into the English field."""
        from tinternship_backend.db.engine import _seed_candidate_lists
        from tinternship_backend.services import candidate_lists

        lists = self._seed("Probabilités", "Python")
        candidate_lists.update(lists["course"][0]["id"], en="Probability", fr="Probabilités")

        _seed_candidate_lists()

        courses = candidate_lists.all_items()["course"]
        assert len(courses) == 1
        assert courses[0]["en"] == "Probability"

    def test_a_database_that_never_had_the_columns_is_left_alone(self):
        """Every fresh install, and every boot after the columns are dropped."""
        from sqlalchemy import inspect

        from tinternship_backend.db.engine import _retire_removed_values, _seed_candidate_lists
        from tinternship_backend.services import candidate_lists

        _retire_removed_values()
        columns = {item["name"] for item in inspect(get_engine()).get_columns("profile")}
        assert "courses" not in columns and "skills_pool" not in columns

        _seed_candidate_lists()

        assert candidate_lists.all_items() == {"course": [], "skill": []}
