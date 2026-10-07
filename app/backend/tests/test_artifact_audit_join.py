"""Matching an artifact to its audit.

Regression test for a real bug: audits were looked up by `subject_id` alone, so
artifact #1 picked up the *search brief's* audit — a prompt id and an artifact
id are both just small integers. The first artifact showed a `search_brief_v1`
verdict and the résumé showed a `playbook_v1` one.
"""

from __future__ import annotations

from tinternship_backend.api.applications import _audit_for, _audit_lookups
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    AgentRun,
    Application,
    ApplicationArtifact,
    ArtifactKind,
    AuditRecord,
    JobPosting,
)


def _new_run() -> int:
    with session_scope() as session:
        run = AgentRun(kind="applying", label="test")
        session.add(run)
        session.flush()
        return int(run.id)


def seed() -> tuple[int, dict[str, ApplicationArtifact]]:
    run_id = _new_run()
    with session_scope() as session:
        job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus")
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id)
        session.add(application)
        session.flush()

        artifacts = {}
        for kind in (
            ArtifactKind.INTERVIEW_PREP,
            ArtifactKind.RESUME,
            ArtifactKind.COVER_LETTER,
        ):
            artifact = ApplicationArtifact(
                application_id=application.id, kind=kind, version=1, run_id=run_id
            )
            session.add(artifact)
            session.flush()
            session.refresh(artifact)
            artifacts[kind] = artifact

        # Advisory audits from earlier runs, whose subject_id is a *prompt* id
        # that collides numerically with the artifact ids above.
        for kind, subject_id, rubric, overall in (
            ("brief", "1", "search_brief_v1", 10.0),
            ("playbook", "2", "playbook_v1", 9.7),
        ):
            session.add(
                AuditRecord(
                    subject_kind=kind, subject_id=subject_id, rubric=rubric, overall=overall
                )
            )
        # The in-loop gate verdicts: no subject_id, only (run_id, kind).
        for kind, rubric, overall in (
            ("interview_prep", "interview_prep_v1", 9.07),
            ("resume", "resume_v1", 9.19),
            ("cover_letter", "cover_letter_v1", 9.43),
        ):
            session.add(
                AuditRecord(
                    subject_kind=kind,
                    rubric=rubric,
                    overall=overall,
                    run_id=run_id,
                    blocking=True,
                )
            )

        for artifact in artifacts.values():
            session.expunge(artifact)
        return run_id, artifacts


def resolve(artifact: ApplicationArtifact) -> tuple[str, float] | None:
    """Look the audit up and read it while its session is still open."""
    with session_scope() as session:
        by_run, by_subject = _audit_lookups(session)
        record = _audit_for(artifact, by_run, by_subject)
        return None if record is None else (record.rubric, record.overall)


def test_each_artifact_gets_its_own_rubric_not_a_colliding_one():
    _run_id, artifacts = seed()
    expected = {
        ArtifactKind.INTERVIEW_PREP: ("interview_prep_v1", 9.07),
        ArtifactKind.RESUME: ("resume_v1", 9.19),
        ArtifactKind.COVER_LETTER: ("cover_letter_v1", 9.43),
    }
    for kind, want in expected.items():
        assert resolve(artifacts[kind]) == want, kind


def test_a_later_reaudit_supersedes_the_gate_verdict():
    _run_id, artifacts = seed()
    resume = artifacts[ArtifactKind.RESUME]
    with session_scope() as session:
        session.add(
            AuditRecord(
                subject_kind="resume",
                subject_id=str(resume.id),
                rubric="resume_v1",
                overall=6.2,
                verdict="revise",
            )
        )
    assert resolve(resume) == ("resume_v1", 6.2)


def test_an_artifact_from_an_unaudited_run_has_no_audit():
    unrelated_run = _new_run()
    with session_scope() as session:
        job = JobPosting(dedupe_key="k2", title="X", company="Y")
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id)
        session.add(application)
        session.flush()
        orphan = ApplicationArtifact(
            application_id=application.id,
            kind=ArtifactKind.INTERVIEW_PREP,
            version=1,
            run_id=unrelated_run,
        )
        session.add(orphan)
        session.flush()
        session.refresh(orphan)
        session.expunge(orphan)

    assert resolve(orphan) is None
