"""SQLModel tables.

Design notes:

* `AgentPrompt` is the single versioned store for the *editable* system prompts
  the Interrogator and HR Expert produce. Its `structured` column holds the
  schema-validated payload (a `SearchBrief` or a `HiringPlaybook`), while
  `content` holds the rendered instruction text that downstream agents receive.
  Editing either one creates a new row rather than mutating the old, so a trace
  can always point at the exact version that was used.
* `TraceEvent` is the queryable decision log written by `AuditPlugin`. It is
  intentionally denormalised and append-only.
* Every timestamp column is `UTCDateTime`, so datetimes are timezone-aware UTC
  everywhere above the storage layer. See that class for why plain `datetime`
  is a trap on SQLite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, Index, Text, TypeDecorator
from sqlalchemy import DateTime as SADateTime
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """A `DateTime` that always reads back as timezone-aware UTC.

    SQLite has no datetime type: SQLAlchemy formats the value into a string and
    drops the tzinfo on the way in. So a column written with `utcnow()` — which
    is aware — comes back *naive*, and the two bite in different places:

    * `token.expires_at <= utcnow()` raises `TypeError: can't compare
      offset-naive and offset-aware datetimes` (this is what broke the OAuth
      import — every call went through the token expiry check);
    * `.isoformat()` yields no offset, so the browser's `new Date()` reads a
      UTC instant as local time and every timestamp in the UI is wrong by the
      viewer's offset.

    Normalising in one place fixes both, and keeps naive datetimes from leaking
    back in later. Stored values are unchanged — the same UTC wall clock the
    old code wrote — so existing rows read back correctly and no migration is
    needed.
    """

    impl = SADateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        # Naive values are assumed to be UTC already: nothing in this app ever
        # builds a local-time datetime.
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def timestamp_column(*, index: bool = False) -> Any:
    return Field(default_factory=utcnow, sa_type=UTCDateTime, index=index)


def optional_timestamp_column() -> Any:
    return Field(default=None, sa_type=UTCDateTime, nullable=True)


def json_column() -> Any:
    return Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))


def json_list_column() -> Any:
    return Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))


def text_column(default: str = "") -> Any:
    return Field(default=default, sa_column=Column(Text, nullable=False, default=default))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PromptKind(StrEnum):
    SEARCH_BRIEF = "search_brief"
    PLAYBOOK = "playbook"


class ProfileSourceKind(StrEnum):
    # The candidate's own .docx résumé, one per language. Not an ordinary
    # import: these two documents *are* the résumé an employer receives, and an
    # applying run edits a copy of the file rather than generating a new one.
    # At most one row per language, replaced rather than accumulated. See
    # `services/base_documents.py`.
    BASE_RESUME = "base_resume"
    # The candidate's own .docx cover letter, one per language, on exactly the
    # same terms — since 2026-09-09 the letter is filled in rather than written,
    # so the letterhead, the address block and the sign-off are theirs. The one
    # difference from a base résumé is that this upload is *not* read by the
    # profile extractor: a letter template holds no career facts the CV has not
    # already given, and "Available from January 2027" is a sentence from a
    # template rather than a fact about them.
    BASE_COVER_LETTER = "base_cover_letter"
    UPLOAD_PDF = "upload_pdf"
    UPLOAD_DOCX = "upload_docx"
    LINKEDIN_PDF = "linkedin_pdf"
    LINKEDIN_ARCHIVE = "linkedin_archive"
    MANUAL = "manual"


class CandidateListKind(StrEnum):
    """Which of the two lists an item belongs to.

    Two lists rather than one because the résumé has two blanks, and a course is
    not a skill: "Probabilités" belongs on a coursework line and nowhere else.
    """

    COURSE = "course"
    SKILL = "skill"


class ArtifactKind(StrEnum):
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    # The chase email for an application that has gone quiet. An artifact like
    # the package's two — versioned, audited, linked to the run that wrote it —
    # because a second follow-up months later must not overwrite the first.
    FOLLOW_UP = "follow_up"
    # The interview brief, written when the application first reaches one of
    # the `INTERVIEW_STATUSES`.
    # An artifact rather than a page of advice because it is produced by an
    # agent behind the same quality gate, and because a second interview at the
    # same employer deserves its own version rather than overwriting the first.
    INTERVIEW_PREP = "interview_prep"
    # Who to contact about this posting. Versioned like the rest: people move on
    # and postings are chased weeks apart, so a second run is a new shortlist
    # rather than an overwrite — and the old one still says who was written to.
    CONTACTS = "contacts"


class ApplicationStatus(StrEnum):
    """Where an application sits.

    `screening` used to live between `applied` and `interview`. It was removed
    on 2026-08-28: it described the employer's internal state, which the
    candidate can only guess at, so it was a column that either stayed empty or
    held applications nobody could honestly place. Legacy rows are rewritten to
    `applied` by `db/engine.py::_retire_removed_values` — the honest reading of
    "sent, no decision yet".

    `interview` was split on 2026-10-05 into the four rounds an internship
    process actually has — `hr_pre_call`, `hr_interview`, `technical_test`,
    `manager_interview` — because one column could not say how far along an
    application was, and processes skip rounds (many have no HR interview at
    all), so they are four statuses rather than one with a counter. Legacy
    `interview` rows are rewritten to `hr_pre_call`, the first round, by the same
    retirement migration. `INTERVIEW_STATUSES` is the four as a group; anything
    that asks "is this application interviewing" asks that, never one value.
    """

    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    HR_PRE_CALL = "hr_pre_call"
    HR_INTERVIEW = "hr_interview"
    TECHNICAL_TEST = "technical_test"
    MANAGER_INTERVIEW = "manager_interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"
    WITHDRAWN = "withdrawn"


# The interview rounds, in pipeline order. Reaching any of them is what starts
# the interview brief — once, whichever comes first, since a process may skip
# any round.
INTERVIEW_STATUSES: tuple[str, ...] = (
    ApplicationStatus.HR_PRE_CALL,
    ApplicationStatus.HR_INTERVIEW,
    ApplicationStatus.TECHNICAL_TEST,
    ApplicationStatus.MANAGER_INTERVIEW,
)


class RunKind(StrEnum):
    INTERROGATOR = "interrogator"
    HR_EXPERT = "hr_expert"
    INVESTIGATOR = "investigator"
    # One posting the candidate pasted a link to, read and scored — the other
    # way onto the Jobs page. Its own kind rather than an Investigator run
    # because the Traces page reads this as "what was this run for", and a
    # two-stage read of one URL is not a search.
    LINK_INTAKE = "link_intake"
    # The same two-stage read over text the candidate pasted instead of a link —
    # the posting that arrived as an email, a PDF, or on a board no fetch gets
    # through. Its own kind because it costs no fetch and no browser, and a
    # trace that called it `link_intake` would be naming a link that never
    # existed.
    TEXT_INTAKE = "text_intake"
    APPLYING = "applying"
    PROFILE_PARSE = "profile_parse"
    FOLLOW_UP = "follow_up"
    INTERVIEW_PREP = "interview_prep"
    CONTACTS = "contacts"
    # One connection note to one person on a shortlist, written when the
    # candidate presses the button beside their name. Its own kind rather than
    # a `contacts` run because the Traces page answers "what was this run for",
    # and one fast-model call writing two sentences is not the grounded
    # research that produced the shortlist — nor should it be priced like it.
    CONTACT_MESSAGE = "contact_message"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class Profile(SQLModel, table=True):
    """The master profile. Single-user app, so there is normally exactly one row."""

    __tablename__ = "profile"

    id: int | None = Field(default=None, primary_key=True)
    full_name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    summary: str = text_column()
    # The two lists the résumé's blanks are filled from used to be two text
    # columns here (`courses`, `skills_pool`), one item per line. They are rows
    # in `candidate_list_item` since 2026-09-08, because an item has to exist in
    # both languages — see that table. Both columns are dropped on boot by
    # `db/engine.py::RETIRED_COLUMNS`, their lines seeded into rows first.
    # {"experiences": [...], "education": [...], "skills": [...],
    #  "projects": [...], "languages": [...], "certifications": [...], "awards": [...]}
    data: dict[str, Any] = json_column()
    created_at: datetime = timestamp_column()
    updated_at: datetime = timestamp_column()


class CandidateListItem(SQLModel, table=True):
    """One course they took, or one skill they have — written in both languages.

    These are the **menu** the résumé's `[list_of_relevant_courses]` and
    `[list_of_relevant_skills]` blanks are filled from, and the rule attached to
    them is absolute: *select, never invent*.

    They were two text columns on `profile` until 2026-09-08, one item per line,
    written once in whatever language the candidate happened to think in — which
    left the Tailor translating "Recherche opérationnelle, optimisation
    combinatoire" into English on the fly, in a blank measured in characters,
    with no way for anyone to check the result. A row instead, carrying both
    spellings, moves the translation to the one person who knows what the course
    actually was, and turns the filling of that blank back into a copy.

    Both `en` and `fr` are required, which is what makes the block for a run's
    language a complete menu rather than one with holes in it. An item that is
    genuinely the same word in both — `Python`, `Docker` — is stored twice on
    purpose: "they are identical here" is a fact about this item, not a licence
    to fall back to the other language when one side is missing.
    """

    __tablename__ = "candidate_list_item"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # course | skill
    en: str = text_column()
    fr: str = text_column()
    # Where the candidate put it. Not a relevance ranking — that is the Tailor's
    # whole job — just a stable order so the list on the Account page does not
    # reshuffle itself between renders.
    position: int = 0
    created_at: datetime = timestamp_column()
    updated_at: datetime = timestamp_column()


class ProfileSource(SQLModel, table=True):
    """One imported document that contributed to the master profile."""

    __tablename__ = "profile_source"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    label: str = ""
    file_path: str = ""
    source_url: str = ""
    # Set only on a `base_resume` or `base_cover_letter` row: which language's
    # copy of that document this is. The other kinds are language-agnostic — a
    # LinkedIn archive has no language, and an ordinary upload only ever
    # contributes facts.
    language: str = Field(default="", index=True)
    # The structured extraction produced from this single document.
    extracted: dict[str, Any] = json_column()
    status: str = Field(default="pending", index=True)  # pending | parsed | failed
    error: str = text_column()
    invocation_id: str = Field(default="", index=True)
    created_at: datetime = timestamp_column()


# ---------------------------------------------------------------------------
# Editable, versioned agent prompts
# ---------------------------------------------------------------------------


class AgentPrompt(SQLModel, table=True):
    __tablename__ = "agent_prompt"
    __table_args__ = (Index("ix_agent_prompt_kind_active", "kind", "is_active"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    version: int = Field(default=1, index=True)
    title: str = ""
    content: str = text_column()
    structured: dict[str, Any] = json_column()
    is_active: bool = Field(default=True, index=True)
    author: str = Field(default="agent")  # agent | user
    note: str = text_column()
    invocation_id: str = Field(default="", index=True)
    created_at: datetime = timestamp_column()


# ---------------------------------------------------------------------------
# Jobs & applications
# ---------------------------------------------------------------------------


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_posting"

    id: int | None = Field(default=None, primary_key=True)
    dedupe_key: str = Field(index=True, unique=True)
    title: str = Field(index=True)
    company: str = Field(index=True)
    location: str = ""
    remote: str = ""  # onsite | hybrid | remote | unknown
    url: str = ""
    apply_url: str = ""
    source: str = Field(default="", index=True)  # grounded_search | adzuna | manual
    source_ref: str = ""
    description: str = text_column()
    # The one-line form of `description`, written by whichever agent read the
    # posting. The deck shows one card at a time and has room for exactly one
    # sentence about the role; `description` is the 3-6 sentence body behind it.
    summary: str = ""
    requirements: list[Any] = json_list_column()
    nice_to_have: list[Any] = json_list_column()
    contract_type: str = ""
    start_date: str = ""
    duration: str = ""
    compensation: str = ""
    language: str = ""
    # What the posting says about its own date, in its own words — "3 days ago",
    # "12 août 2026" — and that same date parsed to ISO by services/recency.py.
    # Both, because one is what the candidate reads and the other is what sorts.
    # An empty `posted_on` means the posting never said, which is common and is
    # not the same as being old.
    posted_at: str = ""
    posted_on: str = Field(default="", index=True)
    deadline: str = ""
    # Ranking output
    fit_score: float = Field(default=0.0, index=True)
    fit_rationale: str = text_column()
    strengths: list[Any] = json_list_column()
    risks: list[Any] = json_list_column()
    keywords: list[Any] = json_list_column()
    confidence: str = ""  # high | medium | low
    # Set by services/verification.py: ok | blocked | dead | error | unchecked.
    url_status: str = Field(default="unchecked", index=True)
    url_http_status: int = 0
    evidence: dict[str, Any] = json_column()
    # The two verdicts a swipe can leave on a posting without creating an
    # application. `dismissed` is "no" and lives in the trash; `deferred_at` is
    # "not now" and sends the card to the back of the deck — stamped rather than
    # flagged so the deck can bring the longest-deferred one back first, and
    # persisted so a reload does not undo the swipe.
    dismissed: bool = Field(default=False, index=True)
    deferred_at: datetime | None = optional_timestamp_column()
    # Deleted forever from a trash (`services/trash.py`). The row stays as a
    # tombstone — identity only, every other field back to its default, its
    # application and documents gone — because a posting the candidate threw
    # away must stay *answered*: with no row, the next Investigator run would
    # find it again and put it back in the deck. Hidden from every list.
    purged_at: datetime | None = optional_timestamp_column()
    run_id: int | None = Field(default=None, foreign_key="agent_run.id", index=True)
    invocation_id: str = Field(default="", index=True)
    discovered_at: datetime = timestamp_column()


class SearchQuery(SQLModel, table=True):
    """A past query sent to the Investigator from the Jobs chat (Ask the agents).

    Account-based, so queries sync across devices (desktop browser, phone PWA).
    """

    __tablename__ = "search_query"

    id: int | None = Field(default=None, primary_key=True)
    text: str = Field(index=True)
    created_at: datetime = timestamp_column(index=True)
    updated_at: datetime = timestamp_column(index=True)


class Application(SQLModel, table=True):
    __tablename__ = "application"

    id: int | None = Field(default=None, primary_key=True)
    job_posting_id: int = Field(foreign_key="job_posting.id", index=True)
    status: str = Field(default=ApplicationStatus.SAVED, index=True)
    # A favourite, set by swiping a posting up. It sorts the application to the
    # top of whatever Tracker column it is in — the card does not leave the
    # board when its status changes, it just stays first wherever it lands.
    pinned: bool = Field(default=False, index=True)
    # When the candidate gave up on this one. The Tracker's own trash, and a
    # timestamp rather than a flag for the same reason `JobPosting.deferred_at`
    # is one: the pile reads newest-first, and *when* they walked away is part
    # of the record.
    #
    # Deliberately **not** an `ApplicationStatus` value. `status` is the one
    # field that says how far this application actually got — it is what the
    # board columns, the follow-up sweep and the Feedback Analyst all read —
    # so overwriting it with `trashed` would destroy exactly the fact worth
    # keeping, and taking the application back out would have nowhere to put
    # the card. A column beside it keeps everything: the status, the timeline,
    # the notes, the personalisation, and every artifact that was generated.
    trashed_at: datetime | None = optional_timestamp_column()
    # The language the package is written in. Remembered per application so
    # regenerating does not silently switch it back to the default.
    language: str = "en"
    # What the candidate knows about this employer that the posting does not
    # say — a contact on the team, a conversation at a careers fair, an angle
    # they want taken. Asked for at the moment they generate the package, when
    # they are looking at the posting and it is actually in mind, and kept so a
    # regeneration months later still carries it. It reaches the Resume and
    # Cover Letter agents as its own context block; see
    # `services/context_blocks.py::personalisation_block`.
    personalisation: str = text_column()
    notes: str = text_column()
    next_action: str = ""
    next_action_date: str = ""
    applied_at: datetime | None = optional_timestamp_column()
    outcome_at: datetime | None = optional_timestamp_column()
    created_at: datetime = timestamp_column()
    updated_at: datetime = timestamp_column()


class ApplicationEvent(SQLModel, table=True):
    """Status transitions + notes. This is what the feedback digest reads."""

    __tablename__ = "application_event"

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    from_status: str = ""
    to_status: str = ""
    note: str = text_column()
    created_at: datetime = timestamp_column()


class ApplicationArtifact(SQLModel, table=True):
    __tablename__ = "application_artifact"
    __table_args__ = (Index("ix_artifact_app_kind", "application_id", "kind"),)

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    kind: str = Field(index=True)
    version: int = Field(default=1)
    content: dict[str, Any] = json_column()
    rendered_path: str = ""
    run_id: int | None = Field(default=None, foreign_key="agent_run.id", index=True)
    invocation_id: str = Field(default="", index=True)
    revisions: int = Field(default=0)
    created_at: datetime = timestamp_column()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


class AgentRun(SQLModel, table=True):
    """One user-visible pipeline execution, grouping many TraceEvents."""

    __tablename__ = "agent_run"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    label: str = ""
    status: str = Field(default=RunStatus.RUNNING, index=True)
    session_id: str = Field(default="", index=True)
    invocation_id: str = Field(default="", index=True)
    input: dict[str, Any] = json_column()
    output: dict[str, Any] = json_column()
    error: str = text_column()
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    cost_usd: float = 0.0
    started_at: datetime = timestamp_column()
    finished_at: datetime | None = optional_timestamp_column()


class TraceEvent(SQLModel, table=True):
    """Append-only decision log. One row per agent/model/tool lifecycle callback."""

    __tablename__ = "trace_event"
    __table_args__ = (
        Index("ix_trace_run_seq", "run_id", "seq"),
        Index("ix_trace_invocation", "invocation_id", "seq"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, foreign_key="agent_run.id", index=True)
    invocation_id: str = Field(default="", index=True)
    session_id: str = Field(default="", index=True)
    seq: int = Field(default=0)
    # run_start | agent_start | agent_end | model_request | model_response |
    # tool_start | tool_end | event | error | audit
    phase: str = Field(index=True)
    agent_name: str = Field(default="", index=True)
    model: str = ""
    tool_name: str = Field(default="", index=True)
    summary: str = text_column()
    input_preview: str = text_column()
    output_preview: str = text_column()
    payload: dict[str, Any] = json_column()
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    error: str = text_column()
    prompt_version_id: int | None = Field(default=None, index=True)
    content_hash: str = Field(default="", index=True)
    created_at: datetime = timestamp_column(index=True)


class AuditRecord(SQLModel, table=True):
    """A Critic verdict on one artifact, scored against a named rubric."""

    __tablename__ = "audit_record"
    __table_args__ = (Index("ix_audit_subject", "subject_kind", "subject_id"),)

    id: int | None = Field(default=None, primary_key=True)
    subject_kind: str = Field(index=True)  # plan | resume | cover_letter | job_ranking | brief ...
    subject_id: str = Field(default="", index=True)
    rubric: str = Field(default="", index=True)
    scores: dict[str, Any] = json_column()
    overall: float = Field(default=0.0, index=True)
    threshold: float = 0.0
    verdict: str = Field(default="", index=True)  # pass | revise | fail
    blocking: bool = Field(default=False)
    fixes: list[Any] = json_list_column()
    revision: int = Field(default=0)
    run_id: int | None = Field(default=None, foreign_key="agent_run.id", index=True)
    invocation_id: str = Field(default="", index=True)
    created_at: datetime = timestamp_column()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SettingOverride(SQLModel, table=True):
    """One `.env` setting the Settings page changed.

    Only the keys declared in `services/runtime_config.py` are ever written
    here, values are stored as text and coerced back on read, and *no row* means
    "whatever `.env` says" — so deleting the row is how a setting goes back to
    the file. See that module for why an override is worth a table at all.
    """

    __tablename__ = "setting_override"

    key: str = Field(primary_key=True)
    value: str = text_column()
    updated_at: datetime = timestamp_column()
