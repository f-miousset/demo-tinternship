"""Rubrics the Critic scores against, one per artifact kind.

Kept as data rather than prose so the same definitions drive both the live
quality gate and the offline eval harness in `evals/`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    name: str
    description: str
    weight: float = 1.0


@dataclass(frozen=True)
class Rubric:
    key: str
    subject_kind: str
    criteria: tuple[Criterion, ...]
    blocking: bool = False

    def render(self) -> str:
        lines = [f"## Rubric: {self.key}", ""]
        for criterion in self.criteria:
            lines.append(f"- **{criterion.name}** (weight {criterion.weight}): {criterion.description}")
        return "\n".join(lines)


# The résumé track scores what an agent put in the *blanks* of the candidate's
# own document, not a résumé it wrote. So the criteria that used to matter most
# here — completeness, bullet quality, whether it fits a page — are gone: the
# candidate settled all three when they wrote the file, and the agent cannot
# reach them. `selection` takes their place alongside truthfulness, because with
# rewriting off the table the whole of this agent's judgement is *which of the
# candidate's own courses, skills and words go in the gaps*.
#
# `restraint` went with the re-wording design on 2026-08-29. It scored "did you
# change more than you had to", which is now unanswerable in the interesting
# direction: an agent cannot change anything it was not handed a blank for.
#
# `brevity` became `page_use` on 2026-09-10, and it is a rename because the
# question changed rather than the wording. It had asked only whether the fills
# were short, on a document whose whole problem is that it is nearly full — so
# it rewarded exactly the failure the candidate reported: coursework and skills
# lists coming back at half their budget, with the room on the line unused. The
# criterion now scores both directions, which is what `page_fit` measures.
# Audits recorded before that date carry `brevity` and are not comparable with
# it; nothing joins the two, and inventing a name that hid the change would have
# made them look comparable when they are not.
#
# The key stays `resume_v1`: it is the rubric for the `resume` subject kind, and
# a new key would orphan every audit already recorded against the old one.
RESUME_RUBRIC = Rubric(
    key="resume_v1",
    subject_kind="resume",
    blocking=True,
    criteria=(
        Criterion(
            "truthfulness",
            "Every course, skill, title and claim written into a blank is one the candidate "
            "actually has — present in the two lists they curated, in the master profile, or in "
            "the posting where the blank asks for the employer's own words. A course they did "
            "not take or a tool they have never used is falsifying their CV, not tailoring it. "
            "Items taken from the two lists appear character for character as those lists spell "
            "them: the lists are already written in this document's language, so a course whose "
            "title has been translated, re-phrased or shortened is one the candidate cannot show "
            "on a transcript, and scores as invented. "
            "This criterion caps the overall score.",
            weight=2.0,
        ),
        Criterion(
            "selection",
            "Each blank holds the *best available* answer for this posting, not the first "
            "acceptable one: the job title the posting itself uses, the courses closest to what "
            "it asks for, the skills it screens on — ordered most relevant first. Score down for "
            "a generic list that would suit any posting, and just as hard for one that omits "
            "something the candidate has and the posting explicitly asks for.",
            weight=2.0,
        ),
        Criterion(
            "keyword_coverage",
            "The posting's own strings — its hard skills, tools, methods and role vocabulary — "
            "appear verbatim wherever the candidate genuinely supports them and a blank had room "
            "for them. Genuine gaps are declared in keywords_missing rather than papered over. "
            "Score down for paraphrase where the posting's exact term was available, and just as "
            "hard for stuffing: a term with no evidence behind it, or a keyword smuggled in as a "
            "job title the candidate never held.",
            weight=1.5,
        ),
        Criterion(
            "fit",
            "Each fill completes the candidate's own sentence: right grammar in it, right "
            "register, right punctuation and separators, no repetition of the words already on "
            "the line, no trailing full stop where the line does not want one. A fill is read as "
            "part of their line, never on its own. Score down hard for recruitment boilerplate "
            "like '(F/H)' or '(H/F)', raw formulaic dashes copied into sentences (e.g. 'Ingénieur "
            "IA - Conception...' instead of 'Ingénieur IA pour la conception...'), and regular words "
            "left in ALL CAPS ('DATA' instead of 'Data').",
            weight=1.5,
        ),
        Criterion(
            "page_use",
            "Each fill uses the room it was given, and no more. Their CV is one page: score "
            "down for anything that spills it, for padding and for filler adjectives — and "
            "just as hard the other way, for a list that stops at three items with room on the "
            "line for five, or a fill that came back at half its budget. Every character of "
            "that page is one the candidate can put a qualification on, and an item left off "
            "is a match a recruiter's search never makes. The question is whether the room was "
            "spent well, not whether little of it was spent.",
            weight=1.0,
        ),
        Criterion(
            "language",
            "Every fill is in the language the candidate chose, with that language's "
            "conventions and grammatical function words. Reject any fill carrying foreign "
            "grammar. This criterion caps the overall score.",
            weight=1.0,
        ),
    ),
)


# The key stayed `cover_letter_v1` when the letter stopped being written from
# scratch on 2026-09-09, for the reason `resume_v1` records: a new key orphans
# every audit already recorded against the old one, and the question this rubric
# asks — is this letter true, specific and worth reading — did not change. What
# changed is what the agent is allowed to touch, so `structure` now scores the
# paragraphs rather than a salutation the candidate's own template supplies.
COVER_LETTER_RUBRIC = Rubric(
    key="cover_letter_v1",
    subject_kind="cover_letter",
    blocking=True,
    criteria=(
        Criterion(
            "truthfulness",
            "Every claim about the candidate traces to the master profile, to their coursework "
            "and skills lists, or to the candidate's own note; every claim about the employer "
            "traces to the posting or to the address scout's notes. An invented fact — a "
            "project they never worked on, a technology they have never touched, an office the "
            "employer does not have — is falsifying an application, not tailoring it. "
            "This criterion caps the overall score.",
            weight=2.0,
        ),
        Criterion(
            "specificity",
            "The opening could not be pasted into an application to a different company. "
            "References something real about this employer or role, and names the posting's "
            "exact job title. Letters are indexed alongside the résumé, so a few of the "
            "posting's own requirement phrases should appear in the candidate's own sentences "
            "— but a keyword list or a skills dump in prose is a defect, not coverage.",
            weight=1.5,
        ),
        Criterion(
            "evidence",
            "Concrete accomplishments with specifics, not adjectives about the candidate.",
            weight=1.5,
        ),
        Criterion(
            "tone_and_language",
            "Written in the language the candidate chose, at the right register for that "
            "language's conventions. No clichés ('I am writing to express my interest'), no "
            "grovelling. Never include recruitment boilerplate such as '(F/H)' or '(H/F)', "
            "formulaic title dashes, or normal words left in ALL CAPS ('DATA' instead of 'Data').",
            weight=1.0,
        ),
        Criterion(
            "structure",
            "Each filled paragraph does its job — why they are writing, why this employer and "
            "what they have done, a plain close — and none of them repeats what the "
            "candidate's own template already says around them. Score only the blanks that "
            "were filled: the letterhead, the greeting and the sign-off are theirs. Their "
            "template is two thirds of a page before a word is written and the paragraphs are "
            "what fills the rest, so score down a letter that ends halfway down its page as "
            "hard as one that rambles: the fix for a thin letter is another concrete example, "
            "never a longer way of saying the same thing.",
            weight=1.0,
        ),
    ),
)


INTERVIEW_PREP_RUBRIC = Rubric(
    key="interview_prep_v1",
    subject_kind="interview_prep",
    blocking=True,
    criteria=(
        Criterion(
            "truthfulness",
            "Every claim about the employer traces to a URL in `sources`, and every claim "
            "about the candidate to the master profile. No invented funding round, product, "
            "headcount, interview loop or achievement. The candidate will repeat this out "
            "loud to someone who knows the answer, so this caps the overall score.",
            weight=2.0,
        ),
        Criterion(
            "research_depth",
            "The company brief says something the posting did not — what they build, who "
            "for, what changed recently — rather than paraphrasing the job ad. Where the "
            "research genuinely found nothing, it says so instead of padding.",
            weight=1.5,
        ),
        Criterion(
            "candidate_specificity",
            "The pitch, the strengths and the answer outlines are built from THIS "
            "candidate's real experience and could not be handed to another applicant. "
            "The posting's recorded strengths and risks are visibly used.",
            weight=1.5,
        ),
        Criterion(
            "gap_honesty",
            "The gaps are the real ones, including whatever the posting's risks named, and "
            "each answer acknowledges the gap and bridges to something true. Advice to "
            "deflect, minimise or bluff is a failure, not a strategy.",
            weight=1.5,
        ),
        Criterion(
            "question_quality",
            "The likely questions include the hard ones the risks imply, not only the "
            "comfortable ones, and the questions to ask are specific to this employer's "
            "actual work — not 'what does a typical day look like'.",
            weight=1.5,
        ),
        Criterion(
            "usability",
            "Readable in the ten minutes before an interview: outlines rather than scripts, "
            "the useful thing first in every entry, no filler encouragement.",
            weight=1.0,
        ),
        Criterion(
            "language",
            "Written throughout in the language the candidate chose, with that language's "
            "conventions. Proper nouns and the posting's own vocabulary stay untranslated.",
            weight=1.0,
        ),
    ),
)


FOLLOW_UP_RUBRIC = Rubric(
    key="follow_up_v1",
    subject_kind="follow_up",
    blocking=True,
    criteria=(
        Criterion(
            "truthfulness",
            "Every fact exists in the profile or in the application's own timeline. It does "
            "not invent a conversation that never happened, a recruiter's name, a promise to "
            "get back, or an achievement since applying. Caps the overall score.",
            weight=2.0,
        ),
        Criterion(
            "brevity",
            "Under 180 words of body, at most three short paragraphs. A chase email is read "
            "on a phone between two meetings; anything that needs scrolling is not read at all.",
            weight=1.5,
        ),
        Criterion(
            "tone",
            "Polite, warm and entirely free of pressure. No guilt ('I still have not heard "
            "back'), no manufactured urgency ('I have another offer' unless the record says "
            "so), no apologising for existing, no grovelling. It should read like a person "
            "who assumes the silence is ordinary busyness, because it usually is.",
            weight=1.5,
        ),
        Criterion(
            "specificity",
            "Names the exact role as the posting writes it, says when the application went "
            "in, and cites the reference number if there is one — enough for the reader to "
            "find the file without asking. Adds something new where the record supports one, "
            "rather than only asking.",
            weight=1.5,
        ),
        Criterion(
            "actionability",
            "Ends with one plain question the reader can answer in a sentence — a status or "
            "an expected timeline — and offers whatever is missing. Not an open-ended essay "
            "prompt, not three questions.",
            weight=1.0,
        ),
        Criterion(
            "language",
            "Written in the language the candidate chose, at that language's register for "
            "writing to someone you have not met. Proper nouns and the posting's job title "
            "stay untranslated.",
            weight=1.0,
        ),
    ),
)



CONTACTS_RUBRIC = Rubric(
    key="contacts_v1",
    subject_kind="contacts",
    blocking=True,
    criteria=(
        Criterion(
            "truthfulness",
            "Every named person was actually read on a page, and `evidence_url` is that "
            "page. No invented names, no guessed job titles, and above all no profile URL "
            "assembled from a name — `linkedin.com/in/firstname-lastname` is the single "
            "most plausible-looking fabrication available here, and the candidate would "
            "message a stranger. Caps the overall score.",
            weight=2.0,
        ),
        Criterion(
            "targeting",
            "These are people who could actually move THIS application: whoever owns the "
            "requisition, whoever runs the campus or internship programme, the team the "
            "role sits in, an alumnus of the candidate's own school. Score down hard for a "
            "list of whoever happened to be findable — a VP of Sales at a 5000-person firm "
            "is a name, not a contact.",
            weight=1.5,
        ),
        Criterion(
            "reachability",
            "Each person comes with a `why` a message could actually be built from — the "
            "shared school, the requisition they own, the thing they built, the programme "
            "they run. \"Works at the company\" is a fact, not a reason to write to "
            "somebody, and it is what the Message Writer would have to pad into flattery. "
            "Score down a `why` that would suit anybody at that employer.",
            weight=1.5,
        ),
        Criterion(
            "query_quality",
            "The angles are real LinkedIn people-search queries — multi-word terms quoted, "
            "boolean where it earns its place — and they find people the obvious searches "
            "would miss: the parent company's name, the local subsidiary, the team's own "
            "vocabulary, the school's endonym. An angle that repeats 'company + recruiter' "
            "adds nothing, because the app already built that one.",
            weight=1.5,
        ),
        Criterion(
            "candour",
            "Says plainly what it could not find. A small employer with no findable staff "
            "is an ordinary result, and `people: []` with a note saying so is worth more "
            "than four half-sourced names. Score down for padding the list.",
            weight=1.0,
        ),
        Criterion(
            "language",
            "The notes, the reasons and the approach are in the language the candidate "
            "chose. Proper nouns and the posting's own vocabulary stay untranslated.",
            weight=1.0,
        ),
    ),
)


JOB_RANKING_RUBRIC = Rubric(
    key="job_ranking_v1",
    subject_kind="job_ranking",
    blocking=False,
    criteria=(
        Criterion(
            "relevance",
            "The postings genuinely match the brief's role, seniority, dates and locations.",
            weight=2.0,
        ),
        Criterion(
            "score_discrimination",
            "Scores use the full range and separate strong matches from weak ones. Everything "
            "clustered around one value is a failure.",
            weight=1.5,
        ),
        Criterion(
            "rationale_quality",
            "Each rationale cites specifics from both the posting and the candidate.",
            weight=1.5,
        ),
        Criterion(
            "risk_detection",
            "Eligibility problems, duration mismatches and passed deadlines are surfaced as risks.",
            weight=1.5,
        ),
        Criterion(
            "data_integrity",
            "Postings look real and the URLs plausible; uncertain data is marked low-confidence "
            "rather than presented as fact.",
            weight=2.0,
        ),
    ),
)


BRIEF_RUBRIC = Rubric(
    key="search_brief_v1",
    subject_kind="brief",
    blocking=False,
    criteria=(
        Criterion("coverage", "Role, domain, dates, location and eligibility are all pinned down.", 2.0),
        Criterion("searchability", "The keywords are real, usable job-board queries, including local-language forms.", 1.5),
        Criterion("fidelity", "Reflects what the candidate actually said; inferences are conservative and flagged.", 1.5),
        Criterion("gap_honesty", "Genuinely unknown fields are left empty and listed in open_questions.", 1.0),
    ),
)


PLAYBOOK_RUBRIC = Rubric(
    key="playbook_v1",
    subject_kind="playbook",
    blocking=False,
    criteria=(
        Criterion("specificity", "Advice is concrete and domain-specific, not generic career-blog filler.", 2.0),
        Criterion("source_quality", "Cites real, retrievable URLs with genuine takeaways; no padding or invention.", 2.0),
        Criterion("actionability", "The Investigator and Applying agents could act on this directly.", 1.5),
        Criterion("coverage", "Covers where to search, timing, résumé/letter guidance, ATS terms and outreach.", 1.0),
    ),
)


RUBRICS: dict[str, Rubric] = {
    rubric.subject_kind: rubric
    for rubric in (
        RESUME_RUBRIC,
        COVER_LETTER_RUBRIC,
        INTERVIEW_PREP_RUBRIC,
        CONTACTS_RUBRIC,
        FOLLOW_UP_RUBRIC,
        JOB_RANKING_RUBRIC,
        BRIEF_RUBRIC,
        PLAYBOOK_RUBRIC,
    )
}


def get_rubric(subject_kind: str) -> Rubric | None:
    return RUBRICS.get(subject_kind)
