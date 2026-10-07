"""When an application has gone quiet, and what to do about it.

An application that got no answer is the most common outcome and the least
visible one. Nothing changes on the Tracker card, no event arrives, and the
candidate's own memory is the only thing tracking that Datadog has now been
silent for three weeks. The gap this closes is not "I did not know I should
follow up" — everyone knows — it is that following up costs a blank page at the
exact moment there is nothing new to say, so it does not happen.

So two halves:

* **Detection is arithmetic.** An application is *waiting* when the ball is in
  the employer's court (`WAITING_STATUSES`) and *silent* when nothing has
  happened on it for `follow_up_after_days`. Both are computed here in Python
  rather than asked of a model — the same rule the rest of this codebase
  follows, for the same reason.
* **The email is already written.** A nudge that says "you should follow up"
  and hands you an empty compose window is the situation the candidate was
  already in. `sweep()` runs in the background and drafts the email as the
  application comes due, so the notification and the draft arrive together.

## The event log is the clock

There is no `last_chased_at` column and no "dismissed" flag, because
`ApplicationEvent` already records everything that would set one. Silence is
measured from the most recent event — a status change, a note, or the note the
Tracker writes when you mark a follow-up as sent — so:

* sending the follow-up resets the clock by writing an event, and the next
  nudge is due `follow_up_after_days` later;
* any note at all resets it too, which is correct: "recruiter says decisions in
  March" means the application is not being ignored, it is waiting;
* moving it to `rejected`, `offer` or `withdrawn` takes it out of
  `WAITING_STATUSES` entirely and it stops being raised.

The Tracker's trash is the one thing that silences an application without
touching the clock. `trashed_at` is checked alongside the status and writes no
event, so an application thrown away after a month of silence and later taken
back out comes back still a month silent — and is nudged immediately, which is
the truth about it. See `documentation/triage.md`.

A stored flag would have to be kept in step with all three of those by hand,
and the first one it missed would be a nudge for an application that had
already been answered.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, select

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import (
    INTERVIEW_STATUSES,
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    ApplicationStatus,
    ArtifactKind,
    JobPosting,
    utcnow,
)
from .languages import normalise_language

logger = logging.getLogger(__name__)

# Statuses where the employer owes the answer. `saved` and `preparing` have not
# been sent yet, and the four terminal ones are over — chasing either is noise,
# and a nudge that fires when nothing is owed is how a notification gets muted.
WAITING_STATUSES: tuple[str, ...] = (
    ApplicationStatus.APPLIED,
    *INTERVIEW_STATUSES,
)

# Statuses where there is nothing to follow up on *yet*, because the application
# has not been sent. Everything outside `WAITING_STATUSES` but inside this
# complement — a rejection, a withdrawal — is unusual to chase but is the
# candidate's call to make, not the app's: the "Write it" button is theirs to
# press whenever they want one.
UNSENT_STATUSES: tuple[str, ...] = (ApplicationStatus.SAVED, ApplicationStatus.PREPARING)

# What the Tracker writes when you mark one as sent. It is an ordinary
# `ApplicationEvent`, so it both resets the silence clock and shows up in the
# timeline and in the Feedback Analyst's history like everything else.
SENT_NOTE = "Follow-up email sent."

# And what it writes when the candidate could not find anybody to send it to.
# Plenty of postings carry no address at all — an agency listing, a portal that
# answers nothing, a careers page with a form and no name — and the nudge then
# has two honest answers and neither is "mark as sent". That one is a lie in
# the timeline, and the timeline is what `draft_context` hands the writer, so
# the next chase would be written as a second one to somebody who never got a
# first. Leaving it alone is the other failure: the same application is raised
# again tomorrow with nothing having changed.
#
# So an ordinary `ApplicationEvent` like the other, which restarts the clock
# the same way. Deliberately a postponement rather than a dismissal: in another
# `follow_up_after_days` there may be a contact that does not exist today — a
# name on the team page, a run of the Contacts agent — and an application
# nobody could chase is still one nobody has answered.
NO_CONTACT_NOTE = "Follow-up not sent: nobody found to send it to."

# How long after boot the first sweep runs. Long enough that it never competes
# with the first page load, short enough that restarting the container is a
# usable way to say "check now".
FIRST_SWEEP_SECONDS = 90.0


def after_days() -> int:
    """Days of silence before an application is raised. Read live — it is a knob."""
    return max(1, int(get_settings().follow_up_after_days))


def sweep_seconds() -> float:
    return max(300.0, float(get_settings().follow_up_sweep_hours) * 3600.0)


def days_since(moment: datetime) -> int:
    """Whole days, floored. 13.9 days of silence is not yet 14."""
    return max(0, int((utcnow() - moment).total_seconds() // 86400))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _events(session: Any, application_id: int) -> list[ApplicationEvent]:
    return list(
        session.exec(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.created_at)
        ).all()
    )


def _last_activity(application: Application, events: list[ApplicationEvent]) -> datetime:
    """The most recent thing that happened on this application.

    Events first, because every status change and every note writes one. The
    two fallbacks are for a row that somehow has none — `updated_at` is
    deliberately *not* one of them: editing the `next_action` field touches it
    without anything having happened.
    """
    if events:
        return events[-1].created_at
    return application.applied_at or application.created_at


@dataclass(frozen=True)
class Silence:
    """How quiet one application has been, and what that means for chasing it.

    Computed from an application and its events, so the same rule serves the
    Tracker's due list, the sweep, and the application page — which needs it
    even when nothing is due, because the "Write the follow-up" button is
    available whenever the candidate wants one rather than only after the
    threshold. One definition, three readers.
    """

    days: int
    last_activity: datetime
    after_days: int
    # The employer owes the answer: `applied` or one of the interview rounds.
    waiting: bool
    # The application has actually been sent, so a chase email has a subject.
    sendable: bool

    @property
    def due(self) -> bool:
        """Silent long enough that the Tracker raises it unprompted."""
        return self.waiting and self.days >= self.after_days

    @property
    def due_at(self) -> datetime:
        return self.last_activity + timedelta(days=self.after_days)

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "last_activity": self.last_activity.isoformat(),
            "after_days": self.after_days,
            "waiting": self.waiting,
            "sendable": self.sendable,
            "due": self.due,
        }


def silence_of(
    application: Application, events: list[ApplicationEvent], threshold: int | None = None
) -> Silence:
    last = _last_activity(application, events)
    return Silence(
        days=days_since(last),
        last_activity=last,
        after_days=after_days() if threshold is None else threshold,
        waiting=application.status in WAITING_STATUSES,
        sendable=application.status not in UNSENT_STATUSES,
    )


def _latest_draft(session: Any, application_id: int) -> ApplicationArtifact | None:
    return session.exec(
        select(ApplicationArtifact)
        .where(
            ApplicationArtifact.application_id == application_id,
            ApplicationArtifact.kind == ArtifactKind.FOLLOW_UP,
        )
        .order_by(ApplicationArtifact.version.desc())
    ).first()


@dataclass(frozen=True)
class Silent:
    """One application that has gone quiet, with whatever draft it already has."""

    application_id: int
    job_id: int
    status: str
    language: str
    days_silent: int
    last_activity: datetime
    title: str
    company: str
    apply_url: str
    draft: dict[str, Any] | None
    # True when the draft was written *before* this application came due — so it
    # was written about a shorter silence than the one now being reported.
    #
    # That covers both ways it happens. A newer event pushes the due moment
    # forward past an existing draft, which is the original case: the state of
    # play moved after it was written. And a draft the candidate asked for early
    # — a week in, from the button on the application page — is by definition
    # written before the threshold, so the sweep replaces it when the threshold
    # actually arrives instead of surfacing a fortnight-old draft as the nudge.
    draft_stale: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "job_posting_id": self.job_id,
            "status": self.status,
            "language": self.language,
            "days_silent": self.days_silent,
            "last_activity": self.last_activity.isoformat(),
            "job": {"title": self.title, "company": self.company, "apply_url": self.apply_url},
            "draft": self.draft,
            "draft_stale": self.draft_stale,
        }


def silent_applications(threshold: int | None = None) -> list[Silent]:
    """Every waiting application that has been silent for at least `threshold` days."""
    limit = after_days() if threshold is None else threshold
    found: list[Silent] = []
    with session_scope() as session:
        applications = session.exec(
            select(Application).where(
                col(Application.status).in_(WAITING_STATUSES),
                # An application in the Tracker's trash is one the candidate
                # walked away from. Chasing it is the sweep's worst possible
                # output: an email drafted for a job they decided against.
                col(Application.trashed_at).is_(None),
            )
        ).all()
        for application in applications:
            events = _events(session, application.id)
            silence = silence_of(application, events, limit)
            if not silence.due:
                continue
            last = silence.last_activity
            days = silence.days
            job = session.get(JobPosting, application.job_posting_id)
            draft = _latest_draft(session, application.id)
            found.append(
                Silent(
                    application_id=application.id,
                    job_id=application.job_posting_id,
                    status=application.status,
                    language=normalise_language(application.language),
                    days_silent=days,
                    last_activity=last,
                    title=job.title if job else "",
                    company=job.company if job else "",
                    apply_url=(job.apply_url or job.url) if job else "",
                    draft=(
                        {
                            "id": draft.id,
                            "version": draft.version,
                            "revisions": draft.revisions,
                            "run_id": draft.run_id,
                            "created_at": draft.created_at.isoformat(),
                            "content": draft.content,
                        }
                        if draft
                        else None
                    ),
                    draft_stale=bool(draft and draft.created_at < silence.due_at),
                )
            )

    # Longest silence first: that is the one most likely to have been forgotten.
    found.sort(key=lambda item: item.days_silent, reverse=True)
    return found


def pending() -> dict[str, Any]:
    """What the Tracker renders, and what the header badge counts."""
    threshold = after_days()
    return {
        "after_days": threshold,
        "follow_ups": [item.as_dict() for item in silent_applications(threshold)],
    }


# ---------------------------------------------------------------------------
# Context for the writer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftContext:
    application_id: int
    job_id: int
    language: str
    days_silent: int
    history: str


def draft_context(application_id: int) -> DraftContext:
    """Everything the Follow-up agent needs that is not the profile or posting.

    Assembled here rather than in `context_blocks.py` because it is the only
    block that is about an *application* — its timeline, what was already sent,
    and what a previous chase already said — rather than about the candidate or
    the job.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"No application {application_id}")

        events = _events(session, application_id)
        last = _last_activity(application, events)
        language = normalise_language(application.language)
        job_id = application.job_posting_id

        timeline = [
            {
                "at": event.created_at.date().isoformat(),
                "from": event.from_status,
                "to": event.to_status,
                "note": event.note,
            }
            for event in events
        ]

        record: dict[str, Any] = {
            "status": application.status,
            "applied_on": application.applied_at.date().isoformat()
            if application.applied_at
            else "",
            "days_since_anything_happened": days_since(last),
            "candidate_notes": application.notes,
            "timeline": timeline,
        }

        letter = session.exec(
            select(ApplicationArtifact)
            .where(
                ApplicationArtifact.application_id == application_id,
                ApplicationArtifact.kind == ArtifactKind.COVER_LETTER,
            )
            .order_by(ApplicationArtifact.version.desc())
        ).first()
        if letter is not None:
            content = letter.content or {}
            record["cover_letter_sent"] = {
                "addressed_to": content.get("recipient", ""),
                "subject": content.get("subject", ""),
                "points_already_made": content.get("facts_used", []),
            }

        previous = _latest_draft(session, application_id)
        if previous is not None:
            content = previous.content or {}
            record["previous_follow_up"] = {
                "drafted_on": previous.created_at.date().isoformat(),
                "subject": content.get("subject", ""),
                "paragraphs": content.get("paragraphs", []),
            }

    history = f"""
# This application so far

Today is {utcnow().date().isoformat()}. Everything below is the record — if a
conversation, a promise or a name is not in it, it did not happen and you may
not refer to it.

```json
{json.dumps(record, indent=2, ensure_ascii=False, default=str)}
```

`cover_letter_sent.points_already_made` is what the candidate has already told
them: do not make those arguments again. `previous_follow_up`, when present, is
a chase that has already gone out — this one must not repeat its wording, and
should acknowledge that it is the second time only if it genuinely is.
""".strip()

    return DraftContext(
        application_id=application_id,
        job_id=job_id,
        language=language,
        days_silent=days_since(last),
        history=history,
    )


# ---------------------------------------------------------------------------
# The background sweep
# ---------------------------------------------------------------------------


def _needs_draft(item: Silent) -> bool:
    """No draft at all, or one written before the last thing that happened."""
    return item.draft is None or item.draft_stale


async def sweep() -> dict[str, int]:
    """Draft the email for every application that has newly gone quiet.

    Costs one model call per application per silence, and nothing at all on a
    tracker where everything has either answered or been chased already.
    """
    settings = get_settings()
    if not settings.google_api_key:
        # Every run would fail identically and fill the trace log with it.
        return {"due": 0, "drafted": 0, "failed": 0}

    # Local import: `flows` imports this module for `draft_context`, so the two
    # can only meet at call time.
    from . import flows

    due = [item for item in silent_applications() if _needs_draft(item)]
    drafted = failed = 0
    for item in due:
        try:
            await flows.run_follow_up(item.application_id)
            drafted += 1
        except Exception:
            failed += 1
            logger.exception(
                "Could not draft the follow-up for application %s", item.application_id
            )
    if due:
        logger.info(
            "Follow-up sweep: %d due, %d drafted, %d failed", len(due), drafted, failed
        )
    return {"due": len(due), "drafted": drafted, "failed": failed}


async def sweeper() -> None:
    """The forever-loop `main.py` runs as a background task."""
    await asyncio.sleep(FIRST_SWEEP_SECONDS)
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A sweep that raised must not stop the next one from running.
            logger.exception("Follow-up sweep failed")
        await asyncio.sleep(sweep_seconds())
