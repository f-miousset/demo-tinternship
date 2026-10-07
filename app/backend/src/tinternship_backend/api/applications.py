"""Applications: the tracker, the generated artifacts, and their exports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlmodel import col, select

from ..db.engine import session_scope
from ..db.models import (
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    ApplicationStatus,
    AuditRecord,
    JobPosting,
    Profile,
    utcnow,
)
from ..services import base_documents, flows, follow_up, language_check, render, trash
from ..services.audit import audit_payload
from ..services.base_documents import BaseDocumentError
from ..services.languages import SUPPORTED_LANGUAGES, normalise_language
from ..tools.persistence import track_posting
from .jobs import serialise_job
from .sse import sse_response

router = APIRouter(prefix="/api/applications", tags=["applications"])

VALID_STATUSES = {status.value for status in ApplicationStatus}


def _serialise_application(
    application: Application, job: JobPosting | None, artifacts: list[ApplicationArtifact]
) -> dict[str, Any]:
    return {
        "id": application.id,
        "job_posting_id": application.job_posting_id,
        "status": application.status,
        "pinned": application.pinned,
        "language": normalise_language(application.language),
        "personalisation": application.personalisation,
        "notes": application.notes,
        "next_action": application.next_action,
        "next_action_date": application.next_action_date,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "trashed_at": application.trashed_at.isoformat() if application.trashed_at else None,
        "created_at": application.created_at.isoformat(),
        "updated_at": application.updated_at.isoformat(),
        # The whole posting, exactly as the Jobs deck serialises it — summary,
        # fit score and rationale, strengths, risks, requirements, language,
        # age. This used to be eight hand-picked fields, which meant opening an
        # application showed less about the posting than the card you swiped to
        # create it, and the page had nowhere to get the rest from. Sharing the
        # serialiser also means a field added to the deck cannot go missing here.
        "job": serialise_job(job, application.id) if job else None,
        "artifacts": [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "version": artifact.version,
                "revisions": artifact.revisions,
                "rendered_path": artifact.rendered_path,
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in artifacts
        ],
    }


def _latest_artifacts(session, application_id: int) -> list[ApplicationArtifact]:
    artifacts = session.exec(
        select(ApplicationArtifact)
        .where(ApplicationArtifact.application_id == application_id)
        .order_by(ApplicationArtifact.version.desc())
    ).all()
    seen: set[str] = set()
    latest = []
    for artifact in artifacts:
        if artifact.kind in seen:
            continue
        seen.add(artifact.kind)
        latest.append(artifact)
    return latest


class CreateApplication(BaseModel):
    job_posting_id: int
    # Swiping a posting up is "yes, and this one first": it creates the
    # application exactly as swiping right does, and flags it a favourite.
    pinned: bool = False


@router.post("")
def create_application(body: CreateApplication):
    with session_scope() as session:
        job = session.get(JobPosting, body.job_posting_id)
        if job is None or job.purged_at is not None:
            raise HTTPException(status_code=404, detail=f"No job {body.job_posting_id}")
        # The write itself is `persistence.track_posting`, shared with the paste
        # paths, which say yes to a posting on the candidate's behalf. Idempotent
        # there too, pin included, and it takes an application out of the
        # Tracker's trash — validating a posting is a statement about it.
        application, created = track_posting(
            session,
            body.job_posting_id,
            note="Pinned from the deck." if body.pinned else "Saved from the deck.",
            pinned=body.pinned,
            # The language picker opens on the one the posting was written in,
            # here as well as on the paste path. Both go through the same
            # function, so a swiped posting and a pasted one cannot disagree
            # about what a French posting should be answered in.
            language=language_check.posting_language(job),
        )
        return _serialise_application(
            application,
            job,
            [] if created else _latest_artifacts(session, application.id),
        )


# What each surface of the Tracker is asking for. The same shape as
# `api/jobs.JOB_VIEWS`, and for the same reason: "which applications does the
# board show" is one rule, and a boolean at each call site would let two callers
# disagree about it.
APPLICATION_VIEWS = ("board", "trashed", "all")


@router.get("")
def list_applications(
    view: str = Query(
        default="board",
        description=(
            "board — the applications still in play, what the Tracker renders. "
            "trashed — the Tracker's trash. all — everything, trashed included."
        ),
    ),
):
    if view not in APPLICATION_VIEWS:
        raise HTTPException(status_code=400, detail=f"Unknown view {view!r}")

    with session_scope() as session:
        statement = select(Application)
        if view == "board":
            statement = statement.where(col(Application.trashed_at).is_(None))
        elif view == "trashed":
            statement = statement.where(col(Application.trashed_at).is_not(None))
        # The board reads by what moved last; the trash reads by what was thrown
        # away last, because that is the only date its cards are about.
        order = (
            col(Application.trashed_at).desc()
            if view == "trashed"
            else col(Application.updated_at).desc()
        )
        applications = session.exec(statement.order_by(order)).all()
        return {
            "applications": [
                _serialise_application(
                    application,
                    session.get(JobPosting, application.job_posting_id),
                    _latest_artifacts(session, application.id),
                )
                for application in applications
            ]
        }


@router.get("/follow-ups")
def list_follow_ups():
    """Applications that have gone quiet, each with the email already drafted.

    Declared above `/{application_id}` deliberately: routes match in
    declaration order, so the other way round FastAPI tries to read
    "follow-ups" as an integer id and answers 422.
    """
    return follow_up.pending()


@router.post("/{application_id}/follow-up")
def draft_follow_up(application_id: int):
    """Write (or rewrite) the follow-up email for one application.

    Normally the background sweep has already done this by the time the nudge
    appears — this is the "that draft is not right" button, and the way to get
    one for an application that has not gone quiet yet.

    Streams for the same reason `POST /{id}/generate` does: the writer plus up
    to two Critic rounds can outlast the proxy's 100-second patience.
    """
    with session_scope() as session:
        if session.get(Application, application_id) is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")

    return sse_response(flows.follow_up_stream(application_id))


def _note_on_the_follow_up(application_id: int, note: str) -> dict[str, Any]:
    """Write one plain note against an application, leaving the status alone.

    The mechanism behind both answers to the nudge: it lands in the timeline,
    it reaches the Feedback Analyst, and — because silence is measured from the
    last event — it resets the clock, so the next nudge is due a fresh
    `follow_up_after_days` from now. See `services/follow_up.py`.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        session.add(
            ApplicationEvent(
                application_id=application_id,
                from_status=application.status,
                to_status=application.status,
                note=note,
            )
        )
        application.updated_at = utcnow()
        session.add(application)
        session.flush()
        return _serialise_application(
            application,
            session.get(JobPosting, application.job_posting_id),
            _latest_artifacts(session, application_id),
        )


@router.post("/{application_id}/follow-up/sent")
def mark_follow_up_sent(application_id: int):
    """Record that the follow-up went out."""
    return _note_on_the_follow_up(application_id, follow_up.SENT_NOTE)


@router.post("/{application_id}/follow-up/no-contact")
def mark_follow_up_unreachable(application_id: int):
    """Record that there was nobody to send the follow-up to.

    The nudge's other honest answer, for a posting that offers no address and
    no name. "Mark as sent" would put a lie in the timeline the next draft is
    written from, and pressing nothing leaves the same application raised
    tomorrow — so this says what happened, and postpones rather than dismisses:
    the clock restarts, and a contact that does not exist today may exist in a
    fortnight. See `services/follow_up.py::NO_CONTACT_NOTE`.
    """
    return _note_on_the_follow_up(application_id, follow_up.NO_CONTACT_NOTE)


@router.get("/{application_id}")
def get_application(application_id: int):
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        events = session.exec(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.created_at)
        ).all()
        payload = _serialise_application(
            application,
            session.get(JobPosting, application.job_posting_id),
            _latest_artifacts(session, application_id),
        )
        payload["timeline"] = [
            {
                "from": event.from_status,
                "to": event.to_status,
                "note": event.note,
                "at": event.created_at.isoformat(),
            }
            for event in events
        ]
        # How quiet this one has been. Served even when nothing is due, because
        # the page offers to write the follow-up whenever the candidate wants
        # one — it needs to say how long the silence actually is, and the rule
        # for that lives in `services/follow_up.py`, not in the browser.
        payload["silence"] = follow_up.silence_of(application, list(events)).as_dict()
        return payload


class StatusUpdate(BaseModel):
    status: str | None = None
    pinned: bool | None = None
    note: str = ""
    notes: str | None = None
    next_action: str | None = None
    next_action_date: str | None = None


@router.patch("/{application_id}")
def update_application(application_id: int, body: StatusUpdate):
    """Move an application along. Transitions are what the feedback loop learns from."""
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown status {body.status!r}. Valid: {sorted(VALID_STATUSES)}",
        )

    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")

        if body.status is not None and body.status != application.status:
            previous = application.status
            application.status = body.status
            if body.status == ApplicationStatus.APPLIED and application.applied_at is None:
                application.applied_at = utcnow()
            if body.status in {
                ApplicationStatus.OFFER,
                ApplicationStatus.REJECTED,
                ApplicationStatus.GHOSTED,
                ApplicationStatus.WITHDRAWN,
            }:
                application.outcome_at = utcnow()
            session.add(
                ApplicationEvent(
                    application_id=application_id,
                    from_status=previous,
                    to_status=body.status,
                    note=body.note,
                )
            )
        elif body.note:
            session.add(
                ApplicationEvent(
                    application_id=application_id,
                    from_status=application.status,
                    to_status=application.status,
                    note=body.note,
                )
            )

        if body.pinned is not None:
            application.pinned = body.pinned
        if body.notes is not None:
            application.notes = body.notes
        if body.next_action is not None:
            application.next_action = body.next_action
        if body.next_action_date is not None:
            application.next_action_date = body.next_action_date

        application.updated_at = utcnow()
        session.add(application)
        session.flush()
        return _serialise_application(
            application,
            session.get(JobPosting, application.job_posting_id),
            _latest_artifacts(session, application_id),
        )


@router.post("/{application_id}/trash")
def trash_application(application_id: int, trashed: bool = True):
    """Move an application to the Tracker's trash, or take it back out.

    The Tracker's counterpart to `POST /api/jobs/{id}/dismiss`, and it destroys
    just as little: `trashed_at` is stamped, the card leaves the board, and
    everything else stays exactly where it was — the status it had reached, its
    whole timeline, the standing note, the personalisation, and every résumé,
    cover letter, brief and shortlist ever generated for it. Taking it back out
    puts the card back in the column it left, not at the start.

    It is its own verdict rather than a status because the two answer different
    questions: `status` is how far this application got, `trashed_at` is whether
    the candidate is still pursuing it. Folding one into the other would lose
    the first, which is the half the Feedback Analyst learns from.

    **No `ApplicationEvent` is written**, and that is deliberate on both sides.
    The timeline is the record of what happened *with the employer* — it is
    evidence, and "I gave up on this" is not a thing they did. It is also the
    clock `services/follow_up.py` measures silence from, so an event here would
    reset it: an application trashed after a month of silence and taken back out
    would come back looking freshly active, and the nudge it is owed would be
    hidden for another `follow_up_after_days`. Skipping the event keeps the
    silence real, which is what makes restoring safe.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        # `updated_at` is left alone on purpose: it orders the board, and a trip
        # through the trash is not work on the application.
        application.trashed_at = utcnow() if trashed else None
        session.add(application)
        session.flush()
        return _serialise_application(
            application,
            session.get(JobPosting, application.job_posting_id),
            _latest_artifacts(session, application_id),
        )


# Declared before `/{application_id}` routes so "trash" is never read as an id.
@router.delete("/trash")
def empty_trash():
    """Delete every application in the Tracker's trash, and its posting, forever."""
    return trash.empty_tracker_trash()


@router.delete("/{application_id}")
def delete_application(application_id: int):
    """Delete one application in the Tracker's trash, forever.

    Everything `trash_application` was careful to keep goes: the timeline, the
    notes, every generated document and its exported file. The posting behind it
    is reduced to the tombstone that keeps it answered (`services/trash.py`).
    409 for an application still on the board — it has to be trashed first.
    """
    try:
        return trash.delete_application(application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except trash.NotInTrash as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class GenerateRequest(BaseModel):
    """`language` is the English/French choice made before generating.

    Optional so an existing application regenerates in the language it was last
    generated in rather than silently reverting to English.

    `personalisation` is what the candidate typed into the dialog that opens
    when they press Generate — someone they know on the team, a conversation at
    a careers fair, an angle they want taken. `None` means "leave whatever is
    stored alone", which is how a regeneration keeps the note from the first
    run; an empty string is a deliberate clear.

    `cover_letter` is the box beside that field, and it is off by default — for
    the run started by a paste, which asks nothing, as much as for the button.
    Most applications are a form with nowhere to attach a letter, and the
    letter's lane is the expensive half of the run.

    `resume` is on by default and exists to be turned *off*: `{resume: false,
    cover_letter: true}` is *Add a cover letter*, the button on an application
    that already has a résumé. Rewriting that résumé to get a letter beside it
    would spend a second run producing a document that is already on the row.
    Both false is a 400 — there would be nothing to stream.
    """

    language: str = ""
    personalisation: str | None = None
    cover_letter: bool = False
    resume: bool = True


@router.post("/{application_id}/generate")
def generate(
    application_id: int, body: GenerateRequest = Body(default_factory=GenerateRequest)
):
    """Stream the Applying team over the documents this run asks for, each audited.

    Server-sent events rather than one long JSON response, for the same reason as
    `POST /api/jobs/search`: two agents behind critic gates take minutes, and a
    proxy cuts off a response that has said nothing for 100 seconds even though
    each artifact is saved as it is produced. Everything that can be rejected —
    an unknown language, a missing application — is rejected before the stream
    opens, so those are still ordinary 4xx responses.

    Asking for a package also moves the application to `preparing`, because that
    is what has just become true of it — writing the documents *is* the
    preparation, and a Tracker that still files it under "saved" is a board the
    candidate has to maintain by hand. Only from `saved`: regenerating the
    package for something already sent must not walk its status backwards.
    """
    requested = body.language.strip().lower()
    if requested and requested not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language {body.language!r}. Valid: {list(SUPPORTED_LANGUAGES)}",
        )
    if not body.resume and not body.cover_letter:
        raise HTTPException(
            status_code=400,
            detail="Ask for at least one document: the résumé, the cover letter, or both.",
        )

    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        job_id = application.job_posting_id
        language = requested or normalise_language(application.language)
        application.language = language
        if body.personalisation is not None:
            application.personalisation = body.personalisation.strip()
        personalisation = application.personalisation or ""
        if application.status == ApplicationStatus.SAVED:
            application.status = ApplicationStatus.PREPARING
            session.add(
                ApplicationEvent(
                    application_id=application_id,
                    from_status=ApplicationStatus.SAVED,
                    to_status=ApplicationStatus.PREPARING,
                    note="Generating the application package.",
                )
            )
        application.updated_at = utcnow()
        session.add(application)

    # Checked here, before the stream opens, while a status code can still say
    # so. Inside the stream this would be an `error` event on a page that has
    # already switched to showing progress, and the candidate would read it as
    # "the run failed" rather than "you have not uploaded that document yet".
    #
    # Two ways it can fail, and the second one is newer: the document may exist
    # and have no room. A base résumé that already fills its page has nowhere to
    # put a job title, and the run would spend a model call, a critic round and
    # a revision discovering that the page rule cannot be satisfied. Better to
    # say it up front, with the number and the fix.
    #
    # Each document this run will actually produce is checked, and only those:
    # a missing or full base cover letter must not block a run that was never
    # going to write one. The letter's plan is built the way the run will build
    # it — with the date and the employer already filled in — so "is there room"
    # is asked about the blanks the agent is actually going to be given.
    # One at a time and in document order, so the first real problem is the one
    # reported: building both plans up front would let a letter that has not
    # been uploaded yet mask a résumé with no room left on its page.
    try:
        if body.resume:
            resume = base_documents.plan(base_documents.RESUME, language)
            if not resume.usable:
                raise HTTPException(status_code=409, detail=resume.complaint)
        if body.cover_letter:
            letter = flows.letter_plan(job_id, language)
            if not letter.usable:
                raise HTTPException(status_code=409, detail=letter.complaint)
    except BaseDocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return sse_response(
        flows.applying_stream(
            application_id,
            job_id,
            language,
            personalisation,
            body.cover_letter,
            body.resume,
        )
    )


@router.post("/{application_id}/interview-prep")
def interview_prep(application_id: int):
    """Research the employer and write the interview brief.

    Fired by the Tracker the first time an application reaches any of the
    `INTERVIEW_STATUSES` — once, whichever round comes first, because a process
    may skip any of them — and available by hand afterwards for a later round:
    each run saves its own version, so preparing for the technical test does
    not overwrite what was written for the HR pre-call.

    Streams for the same reason the package does, and more so: grounded research
    plus a writer plus up to two Critic rounds is the longest single-artifact run
    in the app.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        if session.get(JobPosting, application.job_posting_id) is None:
            raise HTTPException(
                status_code=409,
                detail="This application's posting is gone, so there is nothing to research.",
            )

    return sse_response(flows.interview_prep_stream(application_id))


@router.post("/{application_id}/contacts")
def contacts(application_id: int):
    """Find the people worth contacting about this posting.

    Fired by **Find people to contact** on the application page, and by **Look
    again** on the tab afterwards — people move on, and an application chased six
    weeks later deserves a fresh look rather than the shortlist from the day it
    was saved. Each run saves its own version, so the old one still records who
    was written to. Nothing starts it automatically: it is a grounded research
    run, and opening a page is not asking for one.

    Streams for the same reason the interview brief does, plus one stage it does
    not have: every link the research produced is fetched before the shortlist is
    saved. See `services/outreach.py`.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail=f"No application {application_id}")
        if session.get(JobPosting, application.job_posting_id) is None:
            raise HTTPException(
                status_code=409,
                detail="This application's posting is gone, so there is no employer to "
                "look for people at.",
            )

    return sse_response(flows.contacts_stream(application_id))


class ContactMessage(BaseModel):
    """Which person on the shortlist to write to.

    `index` is the position, `name` is who was standing in it when the page
    rendered. Both, because an index alone is a position and a shortlist re-run
    in another tab renumbers positions — and a message written about the wrong
    human being onto somebody else's card reads exactly like a considered one.
    """

    index: int
    name: str = ""


@router.post("/{application_id}/contacts/message")
async def contact_message(application_id: int, body: ContactMessage):
    """Write the connection note to one person on the shortlist.

    Pressed beside that person's name, and nothing writes it before that. Until
    2026-09-03 the shortlist run wrote a message for everybody it named, which
    meant eight drafts to send one — output tokens, run time and a weighted
    Critic criterion spent on seven the candidate never opened.

    A plain POST rather than a stream: one fast-model call writing two sentences
    from facts already in the prompt, seconds rather than the minutes that make
    a proxy give up. The message is stored on the shortlist itself, so it is
    still there tomorrow.
    """
    try:
        return await flows.write_opening_line(application_id, body.index, body.name)
    except flows.PersonMoved as exc:
        # 409, not 400: the request was right when it was made, and the fix is
        # to reload rather than to send something different.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except flows.RunFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _audit_lookups(session) -> tuple[dict[tuple[int, str], AuditRecord], dict[tuple[str, str], AuditRecord]]:
    """Two ways to find an artifact's audit.

    The in-loop `QualityGate` runs *before* the artifact row exists, so it can
    only record `(run_id, subject_kind)`. A manual re-audit happens afterwards
    and does know the artifact id, so it records that. Keying on `subject_id`
    alone — as this used to — collides across kinds, because an artifact id and
    a prompt id are both just small integers.
    """
    by_run: dict[tuple[int, str], AuditRecord] = {}
    by_subject: dict[tuple[str, str], AuditRecord] = {}
    # Oldest first, so later records overwrite earlier ones and we end up with
    # the most recent verdict for each key.
    for record in session.exec(select(AuditRecord).order_by(AuditRecord.created_at)).all():
        if record.run_id is not None:
            by_run[(record.run_id, record.subject_kind)] = record
        if record.subject_id:
            by_subject[(record.subject_kind, record.subject_id)] = record
    return by_run, by_subject


def _audit_for(
    artifact: ApplicationArtifact,
    by_run: dict[tuple[int, str], AuditRecord],
    by_subject: dict[tuple[str, str], AuditRecord],
) -> AuditRecord | None:
    # A re-audit is newer information than the gate's verdict, so it wins.
    reaudit = by_subject.get((artifact.kind, str(artifact.id)))
    if reaudit is not None:
        return reaudit
    if artifact.run_id is not None:
        return by_run.get((artifact.run_id, artifact.kind))
    return None


@router.get("/{application_id}/artifacts")
def list_artifacts(application_id: int):
    with session_scope() as session:
        artifacts = session.exec(
            select(ApplicationArtifact)
            .where(ApplicationArtifact.application_id == application_id)
            .order_by(ApplicationArtifact.kind, ApplicationArtifact.version.desc())
        ).all()
        by_run, by_subject = _audit_lookups(session)
        return {
            "artifacts": [
                {
                    "id": artifact.id,
                    "kind": artifact.kind,
                    "version": artifact.version,
                    "content": artifact.content,
                    "revisions": artifact.revisions,
                    "rendered_path": artifact.rendered_path,
                    "run_id": artifact.run_id,
                    "invocation_id": artifact.invocation_id,
                    "created_at": artifact.created_at.isoformat(),
                    "audit": audit_payload(_audit_for(artifact, by_run, by_subject)),
                }
                for artifact in artifacts
            ]
        }


@router.get("/artifacts/{artifact_id}/preview", response_class=HTMLResponse)
def preview_artifact(artifact_id: int):
    """The artifact as HTML, for the in-app preview.

    For a filled document — the résumé and, since 2026-09-09, the letter — this
    is *not* what the download contains, and it says so on the page: the
    download is the candidate's own .docx with its blanks completed, and no HTML
    rendering of an arbitrary Word document would be honest about its layout.
    What this shows is the text and which lines were filled, which is the
    question the candidate actually has.
    """
    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"No artifact {artifact_id}")
        kind, content = artifact.kind, dict(artifact.content or {})
    try:
        return HTMLResponse(render.render_artifact(kind, content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}/text", response_class=PlainTextResponse)
def artifact_text(artifact_id: int):
    """The artifact as plain text, for the Copy button on the cover letter.

    A great many application forms have no attachment field for a letter at
    all — they have a "motivation" box you paste into — and neither of the two
    things already on this row serves that: the .docx is a file, and the
    preview is an iframe of a page scaled to fit a phone, which cannot be
    selected.

    For a cover letter, this extracts the actual letter content from the
    salutation (e.g. "Dear Recruiter:", "Madame, Monsieur,") until the goodbye
    sign-off (e.g. "Sincerely,", "Veuillez agréer..."), with the candidate's
    name appended at the end. Letterhead, date, recipient address and subject
    lines are omitted so the text is immediately pasteable into form textareas.

    404 for a kind with no text form — today, a pre-2026-08-28 résumé. The
    button is only ever drawn on the letter, so nobody reaches this by hand.
    """
    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"No artifact {artifact_id}")
        kind, content = artifact.kind, dict(artifact.content or {})
        profile = session.exec(select(Profile)).first()
        full_name = profile.full_name if profile else ""
    try:
        return PlainTextResponse(render.artifact_text(kind, content, candidate_name=full_name))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(artifact_id: int):
    try:
        path, mime, filename = flows.export_artifact_file(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=mime, filename=filename)


@router.post("/artifacts/{artifact_id}/reaudit")
async def reaudit(artifact_id: int):
    try:
        return await flows.reaudit_artifact(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
