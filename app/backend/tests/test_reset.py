"""Resetting stored data.

The interesting part is not the deletes themselves but the ordering: foreign
keys are enforced, and `JobPosting`, `ApplicationArtifact` and `AuditRecord` all
point at `AgentRun`, so a partial reset that drops runs while keeping jobs would
be rejected outright without the null-out step.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    AgentPrompt,
    AgentRun,
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    ArtifactKind,
    AuditRecord,
    JobPosting,
    Profile,
    ProfileSource,
    SearchQuery,
    TraceEvent,
)
from tinternship_backend.services import reset as reset_service


def seed_everything() -> None:
    with session_scope() as session:
        run = AgentRun(kind="applying", label="seed")
        session.add(run)
        session.flush()

        job = JobPosting(
            dedupe_key="seed", title="ML Intern", company="Nimbus", run_id=run.id
        )
        session.add(job)
        session.flush()

        application = Application(job_posting_id=job.id)
        session.add(application)
        session.flush()

        session.add(ApplicationEvent(application_id=application.id, to_status="saved"))
        session.add(
            ApplicationArtifact(
                application_id=application.id,
                kind=ArtifactKind.RESUME,
                version=1,
                run_id=run.id,
            )
        )
        session.add(AuditRecord(subject_kind="resume", rubric="resume_v1", run_id=run.id))
        session.add(TraceEvent(phase="model_response", run_id=run.id))
        session.add(Profile(full_name="Camille Rousseau"))
        session.add(ProfileSource(kind="upload_pdf", label="cv.pdf", status="parsed"))
        session.add(AgentPrompt(kind="search_brief", version=1, content="brief"))
        session.add(SearchQuery(text="seed query"))


def counts() -> dict[str, int]:
    with session_scope() as session:
        return {
            "jobs": len(session.exec(select(JobPosting)).all()),
            "applications": len(session.exec(select(Application)).all()),
            "artifacts": len(session.exec(select(ApplicationArtifact)).all()),
            "runs": len(session.exec(select(AgentRun)).all()),
            "trace_events": len(session.exec(select(TraceEvent)).all()),
            "audits": len(session.exec(select(AuditRecord)).all()),
            "profiles": len(session.exec(select(Profile)).all()),
            "sources": len(session.exec(select(ProfileSource)).all()),
            "prompts": len(session.exec(select(AgentPrompt)).all()),
            "search_queries": len(session.exec(select(SearchQuery)).all()),
        }


async def test_full_reset_leaves_a_blank_page():
    seed_everything()
    await reset_service.reset({scope.key for scope in reset_service.SCOPES})
    assert all(value == 0 for value in counts().values()), counts()


async def test_clearing_traces_while_keeping_jobs_does_not_violate_foreign_keys():
    """The regression this ordering exists for."""
    seed_everything()
    await reset_service.reset({"traces"})

    remaining = counts()
    assert remaining["runs"] == 0
    assert remaining["trace_events"] == 0
    assert remaining["audits"] == 0
    # Jobs and artifacts survive, with their run reference released.
    assert remaining["jobs"] == 1
    assert remaining["artifacts"] == 1
    assert remaining["search_queries"] == 1
    with session_scope() as session:
        assert session.exec(select(JobPosting)).one().run_id is None
        assert session.exec(select(ApplicationArtifact)).one().run_id is None


async def test_clearing_jobs_removes_their_applications_and_artifacts():
    seed_everything()
    await reset_service.reset({"jobs"})
    remaining = counts()
    assert remaining["jobs"] == 0
    assert remaining["applications"] == 0
    assert remaining["artifacts"] == 0
    assert remaining["search_queries"] == 0
    # Untouched scopes survive.
    assert remaining["profiles"] == 1
    assert remaining["prompts"] == 1
    assert remaining["runs"] == 1


async def test_keeping_the_profile_is_possible():
    """Resetting everything else must not take the base résumés with it.

    The profile scope is the one that owns them — they are `ProfileSource` rows
    and files under `uploads/` — so clearing jobs and strategy has to leave the
    documents an application is built from exactly where they were.
    """
    seed_everything()
    await reset_service.reset({"strategy", "jobs", "conversations", "traces"})
    remaining = counts()
    assert remaining["profiles"] == 1
    assert remaining["sources"] == 1
    assert remaining["prompts"] == 0
    assert remaining["jobs"] == 0


async def test_the_tally_reports_what_was_deleted():
    seed_everything()
    deleted = await reset_service.reset({"jobs"})
    assert deleted["jobs"] == 1
    assert deleted["applications"] == 1
    assert deleted["artifacts"] == 1


async def test_an_unknown_scope_is_rejected_before_anything_is_deleted():
    seed_everything()
    with pytest.raises(ValueError, match="Unknown reset scope"):
        await reset_service.reset({"jobs", "everything"})
    assert counts()["jobs"] == 1


async def test_an_empty_selection_is_rejected():
    with pytest.raises(ValueError, match="Nothing selected"):
        await reset_service.reset(set())


async def test_resetting_an_already_empty_database_is_a_no_op():
    deleted = await reset_service.reset({"jobs", "profile"})
    assert all(value == 0 for value in deleted.values())


def test_summary_counts_what_is_stored():
    seed_everything()
    result = reset_service.summary()
    assert result["jobs"] == 1
    assert result["profile_sources"] == 1
