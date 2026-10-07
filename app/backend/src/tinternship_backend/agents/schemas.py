"""Structured outputs for every agent.

These are enforced by Gemini structured output via `LlmAgent.output_schema`, so
they must stay within what the API's schema dialect supports: plain scalars,
lists, and nested models. No `Optional[...]`, no unions — use empty-string /
empty-list defaults instead, which also keeps downstream code free of None
checks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Interrogator
# ---------------------------------------------------------------------------


class SearchBrief(BaseModel):
    """Everything the downstream agents need to know about what the user wants."""

    headline: str = Field(description="One-line summary, e.g. 'Summer 2027 ML research internship in Paris'")
    role_titles: list[str] = Field(default_factory=list, description="Job titles to search for, including local-language variants")
    domain: str = Field(default="", description="Industry / field, e.g. 'computer vision', 'quantitative finance'")
    seniority: str = Field(default="internship", description="internship | apprenticeship | graduate | working-student")
    start_date: str = Field(default="", description="Earliest start, ISO date or free text")
    end_date: str = Field(default="", description="Latest end, ISO date or free text")
    duration: str = Field(default="", description="e.g. '6 months', '3-4 months'")
    locations: list[str] = Field(default_factory=list, description="Cities / regions / countries, most preferred first")
    remote_preference: str = Field(default="", description="onsite | hybrid | remote | any")
    relocation: str = Field(default="", description="Willingness to relocate and any constraints")
    work_authorisation: str = Field(default="", description="Citizenship / visa status relevant to eligibility")
    languages: list[str] = Field(default_factory=list, description="Languages spoken and level")
    company_profile: str = Field(default="", description="Kind of employer wanted: startup, lab, big tech, public sector…")
    target_companies: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list, description="Hard requirements — a posting missing these is disqualified")
    nice_to_haves: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list, description="Technical and soft skills the user can offer")
    compensation_expectation: str = Field(default="")
    education: str = Field(default="", description="Current school, programme and year")
    portfolio_links: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list, description="Concrete query strings for job boards, incl. local language")
    open_questions: list[str] = Field(default_factory=list, description="Things still unknown that would sharpen the search")
    confidence: str = Field(default="medium", description="high | medium | low — how complete this brief is")


# ---------------------------------------------------------------------------
# HR Expert
# ---------------------------------------------------------------------------


class SourceCitation(BaseModel):
    title: str = ""
    url: str = ""
    takeaway: str = ""


class PlaybookSection(BaseModel):
    title: str
    advice: list[str] = Field(default_factory=list, description="Concrete, actionable bullets — no platitudes")


class HiringPlaybook(BaseModel):
    """Research-backed hiring intel that steers the Investigator and Applying agents."""

    summary: str = Field(description="What it actually takes to land this specific internship")
    domain_insights: list[str] = Field(default_factory=list, description="Hiring norms specific to this domain/region")
    hiring_timeline: str = Field(default="", description="When postings open and close for this kind of role")
    where_to_search: list[str] = Field(default_factory=list, description="Named boards, sites, programmes, communities worth searching")
    search_query_patterns: list[str] = Field(default_factory=list, description="Query strings that work well for this domain")
    resume_guidance: list[str] = Field(default_factory=list)
    ats_keywords: list[str] = Field(default_factory=list, description="Literal strings a filter or recruiter search is set on for this role — hard skills, tools, methods, certifications, role titles, acronym and expansion both, in every hiring language")
    cover_letter_guidance: list[str] = Field(default_factory=list)
    interview_expectations: list[str] = Field(default_factory=list)
    outreach_strategy: list[str] = Field(default_factory=list, description="Referrals, cold email, events — what works here")
    common_mistakes: list[str] = Field(default_factory=list)
    red_flags_in_postings: list[str] = Field(default_factory=list, description="Signals that a posting is not worth applying to")
    extra_sections: list[PlaybookSection] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list, description="Real URLs consulted — required, no invented sources")


# ---------------------------------------------------------------------------
# Investigator
# ---------------------------------------------------------------------------


class JobLead(BaseModel):
    """A raw, unverified lead as returned by a single discovery source."""

    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    snippet: str = ""
    posted_at: str = ""


class DiscoveryResult(BaseModel):
    leads: list[JobLead] = Field(default_factory=list)
    queries_used: list[str] = Field(default_factory=list)
    notes: str = ""


class NormalisedJob(BaseModel):
    """A cleaned, de-duplicated posting."""

    title: str
    company: str
    location: str = ""
    remote: str = Field(default="unknown", description="onsite | hybrid | remote | unknown")
    url: str = ""
    apply_url: str = ""
    source: str = ""
    description: str = Field(default="", description="Substantive summary of the role, 3-6 sentences")
    summary: str = Field(default="", description="ONE sentence, at most 140 characters: what this role actually is. Never a restatement of the title, and never a sales pitch — it is the only line a card has room for")
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    contract_type: str = Field(default="", description="internship | apprenticeship | VIE | graduate…")
    start_date: str = ""
    duration: str = ""
    compensation: str = ""
    language: str = Field(default="", description="Working language of the role")
    posted_at: str = ""
    deadline: str = ""


class NormalisedJobList(BaseModel):
    jobs: list[NormalisedJob] = Field(default_factory=list)
    dropped_duplicates: int = 0
    notes: str = ""


class JobAssessment(BaseModel):
    """The verdict on one posting — everything scoring adds to a posting's facts.

    Separate from the posting itself because the two are produced by different
    agents: the Reader (or the normaliser) states what the page says, the
    Matcher says what it is worth, and asking the Matcher to re-emit the posting
    would invite it to quietly rewrite the description it was given. Both
    scoring paths return only this — the pasted link as `JobAssessment`, a
    search run as `ScoredPosting` — and Python joins it back onto the posting.
    """

    # Every one of them required, and that is load-bearing. A field with a
    # default is optional in the JSON schema, and structured output takes the
    # cheapest path a schema allows: measured on 2026-08-27 against the real
    # brief and ten real postings, a Matcher whose only required field was
    # `index` returned ten indices in a well-judged order, wrote a
    # `strategy_notes` citing specifics — and left every score at 0.0 and every
    # rationale empty. It had done the work and declined to write it down. The
    # deck would have shown ten postings, all scored zero, with nothing to read.
    #
    # Required means the decoder must emit them, so "score it" stops being a
    # request the schema quietly excuses.
    fit_score: float = Field(description="0-10, how well this matches the brief")
    fit_rationale: str = Field(description="Why this score — cite specifics from the brief and the posting")
    strengths: list[str] = Field(description="Where the user is a strong match")
    risks: list[str] = Field(description="Gaps, eligibility issues, or reasons this may not work out")
    keywords: list[str] = Field(description="The posting's own strings, verbatim, most central first — mirrored literally downstream, so never paraphrase")
    confidence: str = Field(description="high | medium | low — confidence the posting details are accurate")


# The most postings one run may hand the Matcher, and the size of the enum it
# picks from. Sixty is the ceiling a real run reaches (`MAX_RESULTS` × 1.5 leads),
# so a hundred is headroom rather than a limit — but it is a hard one, because a
# posting the Matcher has no name for is a posting it cannot score.
MAX_SCOREABLE = 100

# The join key's alphabet. Every value the Matcher is allowed to answer with,
# listed, because a listed value is one a constrained decoder cannot run past.
POSTING_INDEXES = tuple(str(number) for number in range(MAX_SCOREABLE))


class ScoredPosting(JobAssessment):
    """One verdict, addressed to the posting it judges by number.

    What the Investigator's Matcher actually returns. It is handed the
    normalised postings numbered, and answers with the number and the verdict —
    never the posting, which it already has and cannot improve on.

    That is not tidiness, it is the fix for a run lost on 2026-08-27: asked to
    re-emit all eighteen fields of twenty-three postings, the Matcher derailed
    inside the `deadline` string of the *first* one, repeated itself for 232 000
    characters, hit the model's output ceiling at 65 537 tokens, and took a
    six-minute run with a 149-second grounded search down with it. The copied
    fields were the larger half of what it was writing — 506 characters against
    291 for the verdict, averaged over saved postings — and `deadline`, the one
    it derailed in, is now a field it never writes at all.

    The join is `investigator.merge_scores`; the incident is in
    `documentation/decisions.md`.
    """

    # An enum of strings, not an integer, and that is the whole point. Asked for
    # an integer on 2026-08-27, this model answered `"index": 8` and then wrote
    # zeros for sixteen thousand characters: under constrained decoding every
    # further digit is still a valid integer, so nothing in the grammar ever
    # tells it to stop. Twice in three runs, both times in the first posting,
    # both times costing the whole ranking — a corrupt join key loses the
    # verdict entirely, where a corrupt `deadline` only spoiled one field.
    #
    # `Literal` of the hundred index strings makes that failure unreachable
    # rather than unlikely: after `"1` the only token the grammar allows is a
    # closing quote or one more digit that keeps it inside the list.
    #
    # Required, too: a field with a default is optional in the JSON schema, and
    # a model may leave an optional field out. `merge_scores` still checks both,
    # because a local model reached through LiteLLM is bound by neither.
    index: Literal[POSTING_INDEXES] = Field(  # type: ignore[valid-type]
        description="The `index` of the posting this scores, copied exactly from the list you were given",
    )


class ScoredJobList(BaseModel):
    jobs: list[ScoredPosting] = Field(default_factory=list)
    strategy_notes: str = Field(default="", description="What was searched, what worked, what to try next time")


class RankedJob(NormalisedJob, JobAssessment):
    """A posting plus its verdict: what the Jobs page stores for every row.

    No agent returns this. It is what `merge_scores` builds by putting a
    `ScoredPosting` back on the `NormalisedJob` it names — the shape of a row on
    the Jobs page, of `ranked_jobs` in session state, and of everything the rest
    of the pipeline reads.
    """


class RankedJobList(BaseModel):
    """The merged list, as `ranked_jobs` holds it after the Matcher's stage."""

    jobs: list[RankedJob] = Field(default_factory=list)
    strategy_notes: str = Field(default="", description="What was searched, what worked, what to try next time")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class ExperienceEntry(BaseModel):
    title: str = ""
    organisation: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    highlights: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str = ""
    institution: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    details: str = ""
    coursework: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str = ""
    description: str = ""
    url: str = ""
    highlights: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class LanguageEntry(BaseModel):
    language: str = ""
    level: str = ""


class MasterProfile(BaseModel):
    """The user's career facts, extracted from their résumé or a LinkedIn export.

    Since 2026-08-28 this is no longer what a résumé is built from — the
    candidate's own .docx is (see `services/base_documents.py`). It is still the
    only permitted source of facts for everything that *writes*: the cover
    letter, the interview brief, the matcher's read of who this person is, and
    the Interrogator's decision not to re-ask what the CV already says.
    """

    full_name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    summary: str = ""
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    extraction_notes: str = Field(default="", description="Anything unreadable, ambiguous or possibly mis-parsed")


# ---------------------------------------------------------------------------
# Applying — Resume Tailor
# ---------------------------------------------------------------------------

# The most placeholders one base résumé may have. Kept in step with
# `services/docx_template.MAX_SLOTS` by `tests/test_docx_template.py` — a blank
# the model has no name for is a blank that never gets filled.
MAX_SLOTS = 40

# Every slot key the Tailor is allowed to address, listed. Strings rather than
# integers, and a `Literal` rather than a bounded int, for the reason recorded
# on `ScoredPosting.index`: under constrained decoding every further digit of an
# integer is still a valid integer, so nothing in the grammar ever tells the
# model to stop, and a corrupt join key loses the fill.
SLOT_KEYS = tuple(f"s{number}" for number in range(MAX_SLOTS))


class PlaceholderFill(BaseModel):
    """One blank in a document the candidate wrote, filled in.

    This is the *entire* vocabulary either writer has — the résumé's Tailor
    since 2026-08-29, the cover letter's since 2026-09-09 — and it is
    deliberately smaller than the one it replaced. There is no "re-word this
    line", no "add a bullet", no "move Projects above Experience", no "change
    the sign-off": what goes on the page outside the brackets is not something
    an agent is allowed an opinion about, so it is not something the schema can
    express. See `services/docx_template.py`.
    """

    slot: Literal[SLOT_KEYS] = Field(  # type: ignore[valid-type]
        description="The slot key of the blank you are filling, copied exactly from the list of blanks you were given (s0, s1, …)",
    )
    text: str = Field(
        description="What goes in the blank — the replacement text only, not the whole line, and never a tab or a line break. Do not repeat the words around it",
    )
    reason: str = Field(
        default="",
        description="Why this text: which posting requirement it answers, or which of the candidate's own courses or skills it selects",
    )


class TailoredResume(BaseModel):
    """What an applying run produces for the résumé: the blanks, filled.

    Not a résumé. The résumé already exists — the candidate wrote it — and this
    is what goes into the gaps they left for the target role, the posting's
    vocabulary, the relevant coursework and the relevant skills.
    `services/flows.py` slices their .docx around those gaps and saves the
    result; the file an employer receives is their own document with the blanks
    filled in.

    No `language` field, for the reason the old schema recorded and this one
    inherits: which language this is written in is a fact about the request, not
    something to ask the model to report back, and a model that starts narrating
    into a free-text code field can end the JSON object early and lose
    everything after it.
    """

    document_title: str = Field(
        default="",
        description="A title for the document's Word properties, e.g. 'CV — Alex Martin — Stage Machine Learning, Nimbus Labs'. Not printed on the page",
    )
    fills: list[PlaceholderFill] = Field(
        default_factory=list,
        description="One entry per blank in the document. Every blank must appear exactly once",
    )
    keywords_covered: list[str] = Field(default_factory=list, description="Posting keywords that literally appear in the résumé after your fills, spelled as the posting spells them — not paraphrases")
    keywords_missing: list[str] = Field(default_factory=list, description="Posting keywords the candidate's experience genuinely cannot support. Leaving this empty when there are real gaps is a failure")
    gap_analysis: list[str] = Field(default_factory=list, description="Honest gaps against the posting and what the candidate could do about them")
    changes_made: list[str] = Field(default_factory=list, description="What you put in each blank and why, in words the candidate can check against their own CV")


# ---------------------------------------------------------------------------
# Applying — Cover Letter agent
# ---------------------------------------------------------------------------


class TailoredCoverLetter(BaseModel):
    """What an applying run produces for the letter: the blanks, filled.

    Not a letter. The letter already exists — the candidate wrote it, with their
    letterhead, their address block, their salutation, their availability
    sentence and their sign-off — and this is what goes into the gaps they left:
    the paragraphs, the team to address, whatever else they named.

    It replaced a nine-field `CoverLetter` on 2026-09-09 (`recipient`,
    `subject`, `greeting`, `hook`, `fit`, `evidence`, `motivation`, `close`,
    `signature`), which a renderer then laid out into a letter of its own
    design. Every argument that took the résumé out of a template applies here
    unchanged, plus one that is worse for a letter: the fields *were* the layout,
    so a candidate who wanted their own letterhead had nowhere to put it.

    No `language` field, and no `word_count`. Which language this is written in
    is a fact about the request rather than something to ask the model to report
    back, and the length that matters is the character budget on each blank,
    which is measured in Python off the room left on the page. A model narrating
    into a free-text field can also end the JSON object early and lose
    everything after it.
    """

    document_title: str = Field(
        default="",
        description="A title for the document's Word properties, e.g. 'Cover letter — Alex Martin — Nimbus Labs'. Not printed on the page",
    )
    fills: list[PlaceholderFill] = Field(
        default_factory=list,
        description="One entry per blank you were asked for. Every one must appear exactly once",
    )
    facts_used: list[str] = Field(default_factory=list, description="Profile facts relied on, for auditing against invention")
    changes_made: list[str] = Field(default_factory=list, description="What you put in each blank and why, in words the candidate can check")
    address_source: str = Field(
        default="",
        description="The URL the employer's address came from, copied from the research notes. Empty if you left the address blank",
    )


class ProseRewrite(BaseModel):
    """One paragraph of the letter, written again in a human register."""

    slot: Literal[SLOT_KEYS] = Field(  # type: ignore[valid-type]
        description="The slot key of the paragraph you rewrote, copied exactly from the list you were given",
    )
    text: str = Field(
        description="The paragraph in full, rewritten. Same facts, same claims, same posting keywords — different sentences. Never a tab or a line break",
    )
    tells: str = Field(
        default="",
        description="Which machine tells you removed, named — 'triad in the second sentence, "
        "\'testament to\'', 'trois phrases de 19 mots'. One short line",
    )


class HumanisedProse(BaseModel):
    """What the Humaniser returns: the paragraphs it re-wrote, and nothing else.

    Deliberately *not* a whole `TailoredCoverLetter`. This agent's only business
    is the prose, and the way to stop it having any other business is to give it
    no way to express one: it cannot touch the employer's name, the date, the
    reference line or the address, because the schema has no field for them.
    Python decides which slots count as prose and merges the rewrites back —
    the same shape as `merge_scores` joining the Matcher's verdicts onto
    postings it was never handed. See `agents/applying.py`.

    Returning **fewer** rewrites than there were paragraphs is a valid answer: a
    paragraph that already reads like a person wrote it should be left alone,
    and an agent that must produce something for every input produces churn.
    """

    rewrites: list[ProseRewrite] = Field(
        default_factory=list,
        description="One entry per paragraph you actually changed. Leave out the ones that were already fine",
    )
    left_alone: list[str] = Field(
        default_factory=list,
        description="Slot keys you deliberately did not touch, and why, in a few words each",
    )


# ---------------------------------------------------------------------------
# Follow-up
# ---------------------------------------------------------------------------


class FollowUpEmail(BaseModel):
    """The chase email for an application that has gone quiet.

    Written to be *sent*, not edited: the candidate opens their mail client,
    pastes it and presses send. So it is split the way a mail client is —
    subject, greeting, body, sign-off — rather than as one blob of prose, and
    `send_notes` carries everything that is advice to the candidate instead of
    words for the employer, so none of it can end up in the message by mistake.
    """

    recipient: str = Field(default="", description="Named person if the record identifies one, otherwise an appropriate team salutation")
    to_hint: str = Field(default="", description="Which address to send to, in words — 'reply in the thread from the recruiter', 'the careers inbox on the posting'. Never invent an address")
    subject: str = Field(description="Prefer 'Re: <the original subject>' when replying in an existing thread; include the requisition reference if the posting has one")
    greeting: str = ""
    paragraphs: list[str] = Field(default_factory=list, description="The body, one string per paragraph, at most three")
    sign_off: str = Field(default="", description="'Kind regards', 'Bien cordialement' — the closing line only")
    signature: str = Field(default="", description="Name and the contact details worth repeating, one line")
    language: str = Field(default="en", description="ISO code of the language written in")
    word_count: int = Field(default=0, description="Words in the body paragraphs — checked in Python, so report it honestly")
    facts_used: list[str] = Field(default_factory=list, description="Profile and timeline facts relied on, for auditing against invention")
    send_notes: list[str] = Field(default_factory=list, description="For the candidate, never for the employer: who to send it to, what to attach, when to chase again")


# ---------------------------------------------------------------------------
# Interview prep
# ---------------------------------------------------------------------------


class InterviewQuestion(BaseModel):
    """One question the candidate should expect, with the shape of an answer.

    `answer_outline` is deliberately an outline and not a script: an answer read
    off a page is audible, and the point of preparing is to have the material
    ready rather than the sentences. It must be built from facts in the master
    profile, which is what makes it defensible under a follow-up question.
    """

    question: str
    asked_by: str = Field(default="", description="Who typically asks it — recruiter | hiring manager | team | panel")
    why_asked: str = Field(default="", description="What the interviewer is really testing")
    answer_outline: list[str] = Field(default_factory=list, description="Beats of the answer, drawn from the candidate's real experience — never a script to read")
    evidence: list[str] = Field(default_factory=list, description="Which profile facts back this answer up")


class InterviewGap(BaseModel):
    """A weakness the posting exposes, and the honest way to answer for it.

    Never a way to hide it: the answer names the gap, says what the candidate
    has done that is closest to it, and says how they would close it.
    """

    gap: str = Field(description="What the candidate is missing against this posting")
    severity: str = Field(default="", description="blocking | significant | minor")
    honest_answer: str = Field(description="What to actually say when it comes up — acknowledge, bridge to the nearest real experience, state the plan")
    preparation: str = Field(default="", description="What could be done before the interview to narrow it")


class InterviewPrep(BaseModel):
    """The interview brief for one application.

    Produced when the application first reaches an interview round, from
    grounded research on the employer plus the candidate's own profile and the posting's recorded
    strengths and risks. Everything about the company must be traceable to a
    cited source, and everything about the candidate to the master profile.
    """

    company_brief: str = Field(description="What this employer actually does, in 3-5 sentences a candidate could say back — product, market, size, anything recent and relevant")
    recent_developments: list[str] = Field(default_factory=list, description="Genuinely recent, sourced facts worth referencing — funding, launches, papers, reorganisations. Empty is a valid answer")
    role_brief: str = Field(default="", description="What the day-to-day of this role looks like and who it reports to, as far as the posting and the research say")
    interview_process: list[str] = Field(default_factory=list, description="The stages this employer's process is reported to have, in order, with what each one tests")
    pitch: str = Field(default="", description="The answer to 'tell me about yourself' for THIS role — 60-90 seconds, built only from profile facts")
    strengths_to_lead_with: list[str] = Field(default_factory=list, description="The candidate's real advantages for this posting, each tied to the evidence that proves it")
    gaps: list[InterviewGap] = Field(default_factory=list, description="Weaknesses against this posting and how to answer for them honestly")
    likely_questions: list[InterviewQuestion] = Field(default_factory=list, description="What they will most likely ask, hardest ones included")
    questions_to_ask: list[str] = Field(default_factory=list, description="Questions for the candidate to ask, specific enough that they could not be asked of another employer")
    technical_topics: list[str] = Field(default_factory=list, description="What to revise beforehand, drawn from the posting's requirements")
    logistics: list[str] = Field(default_factory=list, description="Practical preparation: format, dress, documents, timing, what to have to hand")
    red_flags_to_probe: list[str] = Field(default_factory=list, description="What the candidate should satisfy themselves about before accepting — an interview runs both ways")
    sources: list[SourceCitation] = Field(default_factory=list, description="Every URL genuinely read for the company research. A claim about the employer with no source here is fabrication")
    language: str = Field(default="en", description="ISO code of the language written in")


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


# The vocabulary a contact is described with. `Literal` rather than `str` for the
# reason `ScoredPosting.index` is: under constrained decoding, a free string
# field has no stopping rule — after `"re` every further character is still a
# valid string — and a model that starts enumerating inside one ends the JSON
# object early and loses everything after it. Listing the values makes that
# unreachable rather than unlikely, and it also guarantees the badge the page
# looks up by this key exists.
CONTACT_CATEGORIES = ("recruiter", "campus", "hiring_manager", "team", "alumnus", "other")
CONFIDENCE_LEVELS = ("high", "medium", "low")


class ContactLead(BaseModel):
    """One person worth writing to about this posting.

    Note what this schema *cannot* say. There is no field for a search URL: the
    scout describes who to look for and `services/outreach.py` builds the link,
    for the reason `ScoredPosting` answers with an index rather than a posting —
    a URL a model types is a URL it can invent, and a fabricated contact link
    costs exactly the time this feature exists to save.

    `linkedin_url` is the one exception, and it is not an exception to that
    rule so much as a use of it: it may only be given when the profile URL was
    genuinely read off a page, and it is fetched afterwards and thrown away
    unless the page turns out to be titled with this person's name.

    **No `opening_line` either, since 2026-09-03.** Writing the message to send
    somebody is not part of deciding who is worth writing to: a shortlist of
    eight people came with eight messages, seven of which were never read. The
    message is written on request now, one person at a time, by the agent below.
    """

    name: str = Field(description="The person's full name, exactly as the source spells it")
    role: str = Field(default="", description="Their own job title, as the source gives it — not the title of the posting")
    category: Literal[CONTACT_CATEGORIES] = Field(  # type: ignore[valid-type]
        default="other",
        description="What this person is to this application: recruiter | campus | hiring_manager | team | alumnus | other",
    )
    why: str = Field(default="", description="Why this person, for THIS posting — what they own, or what they share with the candidate")
    linkedin_url: str = Field(default="", description="Their linkedin.com/in/… URL ONLY if you actually read it on a page you retrieved. Never assemble one from their name. Leave empty otherwise — the app finds them by search instead")
    evidence_url: str = Field(description="The page you read that names this person. Required: a name with no page behind it is an invention, and the app drops it")
    confidence: Literal[CONFIDENCE_LEVELS] = Field(  # type: ignore[valid-type]
        default="medium",
        description="How sure you are this person is at this company in this role: high | medium | low",
    )


class SearchAngle(BaseModel):
    """A way to look for people, expressed as the search itself.

    Keywords rather than a link, and the app turns them into one. LinkedIn's
    people search takes quoted phrases and boolean operators, so a good angle is
    a real query and not a description of one.
    """

    label: str = Field(description="What this search finds, in the candidate's words")
    keywords: str = Field(description='The LinkedIn people-search query. Quote multi-word terms: \'"Nimbus Labs" ("campus" OR "early careers")\'')
    why: str = Field(default="", description="Why these people are worth reaching for this posting")


class ContactPlan(BaseModel):
    """Who to contact about one posting, and how.

    Produced on request from grounded research on the employer, plus what the app
    already knows about the posting and the candidate's own schools. Every named
    person must carry the page that names them; every link is either built in
    Python or proved by a fetch.

    **No `language` field**, and it is not an oversight — it is the same lesson
    `TailoredResume` records, learned again the hard way on 2026-08-29. A real
    run answered `"language": "fr` and then enumerated locale tags — `fr-UZ
    fr-TM fr-TJ …` — for 128 000 characters until it hit the output ceiling, so
    the JSON never closed and pydantic threw `EOF while parsing a string`. The
    whole run went with it, grounded search and all. A free-text code field has
    no stopping rule under constrained decoding, and which language this was
    written in is a fact about the request: `contacts_stream` stamps it on.
    """

    people: list[ContactLead] = Field(default_factory=list, description="Named individuals you actually found. Empty is a valid and honest answer — better than a plausible name")
    angles: list[SearchAngle] = Field(default_factory=list, description="Searches worth running that the app's standard ones would miss — a parent company, a local subsidiary's name, the team's own vocabulary")
    company_linkedin_slug: str = Field(default="", description="The employer's LinkedIn company slug ONLY — 'mistralai', not a URL, not a guess. It is fetched and dropped if it 404s")
    approach: list[str] = Field(default_factory=list, description="How to actually reach these people for this employer: which channel, in what order, what to say first, what not to do")
    notes: str = Field(default="", description="What you could not find, and anything the candidate should know before writing")
    sources: list[SourceCitation] = Field(default_factory=list, description="Every URL genuinely read. A person named here with no source is fabrication")


class OpeningMessage(BaseModel):
    """The first message to one person, written when the candidate asks for it.

    One field, and deliberately so. Everything else about the message — who it
    is to, which posting it is about, which language it is in — is a fact about
    the request that `flows.write_opening_line` already holds, and a field a
    model fills is a field it can derail in: `ContactPlan` lost a whole grounded
    run to a free-text `language` on 2026-08-29. What is left is the one thing
    only the model can produce.

    The length rule is in the prompt and the count is done in Python, for the
    reason every other promise here is kept outside the model: a prompt is a
    request. The page shows the count against LinkedIn's 300-character limit.
    """

    message: str = Field(description="The connection request to send this person: at most 280 characters, in the language asked for, naming the specific reason to write to THEM")


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class CriterionScore(BaseModel):
    criterion: str
    score: float = Field(description="0-10")
    justification: str = ""


class CriticVerdict(BaseModel):
    """A rubric-scored audit of one artifact."""

    subject_kind: str = Field(default="", description="plan | resume | cover_letter | brief | playbook | job_ranking")
    scores: list[CriterionScore] = Field(default_factory=list)
    overall: float = Field(default=0.0, description="0-10 weighted overall quality")
    verdict: str = Field(default="revise", description="pass | revise | fail")
    fixes: list[str] = Field(default_factory=list, description="Specific, actionable corrections — empty when verdict is pass")
    unsupported_claims: list[str] = Field(default_factory=list, description="Statements not backed by the profile or the posting")
    reasoning: str = Field(default="", description="Short explanation of the overall score")


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackDigest(BaseModel):
    summary: str = Field(default="", description="What the application history says about what is and isn't working")
    what_works: list[str] = Field(default_factory=list)
    what_fails: list[str] = Field(default_factory=list)
    search_adjustments: list[str] = Field(default_factory=list, description="Concrete changes the Investigator should make next run")
    playbook_amendments: list[str] = Field(default_factory=list)
