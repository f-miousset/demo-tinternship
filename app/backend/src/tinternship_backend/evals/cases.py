"""Golden cases for the offline quality harness.

Each case is a deliberately *flawed* artifact paired with the defects the Critic
is expected to notice. This is a regression test for the audit itself: if you
edit a rubric or the Critic instruction and it stops catching a fabricated
number, `make eval` fails.

Cases are held to a maximum score rather than an exact one — the point is that
bad work scores badly, not that it scores 3.7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    name: str
    subject_kind: str
    artifact: dict[str, Any]
    context: str
    max_overall: float = 10.0
    min_overall: float = 0.0
    # Substrings that must appear somewhere in the Critic's fixes or
    # unsupported-claims list, lowercased.
    must_flag: list[str] = field(default_factory=list)
    expect_unsupported: bool = False


PROFILE_CONTEXT = """
# Candidate master profile

```json
{
  "full_name": "Alex Martin",
  "location": "Lyon, France",
  "education": [{"degree": "MSc Computer Science", "institution": "INSA Lyon"}],
  "experiences": [
    {
      "title": "Software Intern",
      "organisation": "Acme",
      "start_date": "Jun 2025",
      "end_date": "Sep 2025",
      "highlights": ["Built a data ingest script", "Wrote unit tests"]
    }
  ],
  "skills": ["Python", "SQL", "Git"]
}
```
"""

JOB_CONTEXT = """
# Job posting

```json
{
  "title": "Machine Learning Intern",
  "company": "Nimbus Labs",
  "location": "Paris, France",
  "requirements": ["PyTorch", "Distributed training", "Published research"],
  "duration": "6 months",
  "start_date": "March 2027"
}
```
"""

CONTEXT = f"{PROFILE_CONTEXT}\n\n{JOB_CONTEXT}"


FABRICATED_RESUME = EvalCase(
    name="resume_with_fabricated_metrics",
    subject_kind="resume",
    context=CONTEXT,
    max_overall=5.0,
    expect_unsupported=True,
    must_flag=["pytorch", "publi"],
    artifact={
        "full_name": "Alex Martin",
        "contact": ["alex@example.com"],
        "experiences": [
            {
                "title": "Senior ML Engineer",
                "organisation": "Acme",
                "start_date": "Jun 2025",
                "end_date": "Sep 2025",
                "bullets": [
                    {
                        "text": "Trained distributed PyTorch models on 64 GPUs, cutting training 78%",
                        "evidence": "",
                    },
                    {"text": "Published two papers at NeurIPS", "evidence": ""},
                ],
            }
        ],
        "education": [{"institution": "INSA Lyon", "degree": "MSc Computer Science"}],
        "skills": [{"heading": "Technical", "entries": ["PyTorch", "JAX", "Ray"]}],
        "language": "en",
        "keywords_covered": ["PyTorch", "Distributed training", "Published research"],
        "keywords_missing": [],
        "gap_analysis": [],
        "changes_made": ["Emphasised ML experience"],
    },
)


# The letter stopped being written from scratch on 2026-09-09: the artifact is
# now the blanks of the candidate's own .docx, filled in. The case moved with it
# rather than being retired, because the defect it tests for did not change —
# an opening that could be pasted into any application, adjectives where the
# evidence should be — and the Critic still has to catch it in whatever shape
# the letter arrives.
GENERIC_COVER_LETTER = EvalCase(
    name="cover_letter_generic_and_clichéd",
    subject_kind="cover_letter",
    context=CONTEXT,
    max_overall=6.0,
    must_flag=["specific", "generic", "cliché", "cliche", "nimbus"],
    artifact={
        "document_title": "Cover letter",
        "fills": [
            {"slot": "s0", "text": "Recruiting"},
            {"slot": "s1", "text": "the advertised position"},
            {
                "slot": "s2",
                "text": (
                    "I am writing to express my strong interest in the position advertised "
                    "on your website. I believe I would be a great fit for your company and "
                    "its mission."
                ),
            },
            {
                "slot": "s3",
                "text": (
                    "I am a hard worker, a fast learner, and a team player with excellent "
                    "skills. Your company is a leader in its field and I would love to work "
                    "there."
                ),
            },
            {
                "slot": "s4",
                "text": (
                    "Thank you for your time and consideration. I look forward to hearing "
                    "from you."
                ),
            },
        ],
        "facts_used": [],
        "changes_made": ["Wrote the three paragraphs"],
    },
)


UNSOURCED_INTERVIEW_PREP = EvalCase(
    name="interview_prep_with_invented_company_facts",
    subject_kind="interview_prep",
    context=CONTEXT,
    max_overall=6.0,
    expect_unsupported=True,
    must_flag=["source", "unsupported", "invent", "cite"],
    artifact={
        "company_brief": (
            "Nimbus Labs is a fast-growing AI company that raised a $40M Series B in "
            "March and now employs around 250 people across three offices."
        ),
        "recent_developments": [
            "Acquired a computer-vision startup last quarter.",
            "Named one of the top 10 places to work in France.",
        ],
        "pitch": "I am a passionate, hard-working student who loves machine learning.",
        "strengths_to_lead_with": ["Strong communicator", "Fast learner", "Team player"],
        "gaps": [
            {
                "gap": "No PyTorch experience",
                "honest_answer": "Say you have used many frameworks and can pick it up quickly.",
            }
        ],
        "likely_questions": [
            {"question": "Tell me about yourself.", "answer_outline": ["Be enthusiastic."]}
        ],
        "questions_to_ask": ["What does a typical day look like?", "What is the culture like?"],
        "sources": [],
        "language": "en",
    },
)


GOOD_RESUME = EvalCase(
    name="resume_honest_and_targeted",
    subject_kind="resume",
    context=CONTEXT,
    min_overall=6.0,
    artifact={
        "full_name": "Alex Martin",
        "contact": ["alex@example.com", "Lyon, France"],
        "experiences": [
            {
                "title": "Software Intern",
                "organisation": "Acme",
                "location": "Lyon, France",
                "start_date": "Jun 2025",
                "end_date": "Sep 2025",
                "bullets": [
                    {
                        "text": "Built a Python data ingest script feeding the analytics pipeline",
                        "evidence": "profile: 'Built a data ingest script'",
                    },
                    {
                        "text": "Wrote the unit test suite covering the ingest paths",
                        "evidence": "profile: 'Wrote unit tests'",
                    },
                ],
            }
        ],
        "education": [
            {
                "institution": "INSA Lyon",
                "location": "Lyon, France",
                "degree": "MSc Computer Science",
                "end_date": "Expected 2027",
            }
        ],
        "skills": [{"heading": "Technical", "entries": ["Python", "SQL", "Git"]}],
        "language": "en",
        "keywords_covered": ["Python"],
        "keywords_missing": ["PyTorch", "Distributed training", "Published research"],
        "gap_analysis": [
            "No PyTorch experience on record — worth completing a small training project before applying.",
            "No publications; the posting lists published research as a requirement.",
        ],
        "changes_made": [
            "Reframed the Acme bullets around data pipeline work, which is the closest match to the posting.",
            "Did not claim any ML framework experience, as the profile contains none.",
        ],
    },
)


FABRICATED_CONTACTS = EvalCase(
    name="contacts_with_assembled_profile_urls",
    subject_kind="contacts",
    context=CONTEXT,
    max_overall=5.0,
    expect_unsupported=True,
    must_flag=["evidence", "url", "invent", "source"],
    artifact={
        # The failure mode this rubric exists for, and it is a quiet one: every
        # line of this reads like a good shortlist. Two of the three people have
        # no page behind them, and every profile URL is the person's name with a
        # hyphen in it — the single most plausible fabrication available here,
        # and the one that sends the candidate to message a stranger.
        "people": [
            {
                "name": "Sophie Lambert",
                "role": "Head of Talent",
                "category": "recruiter",
                # Generic on purpose too: a `why` that would suit anybody at
                # this employer is exactly what `reachability` scores down, and
                # what leaves the Message Writer nothing but flattery to send.
                "why": "She would own this requisition.",
                "linkedin_url": "https://www.linkedin.com/in/sophie-lambert",
                "evidence_url": "",
                "confidence": "high",
            },
            {
                "name": "Thomas Bernard",
                "role": "VP Sales",
                "category": "other",
                "why": "Senior person at the company.",
                "linkedin_url": "https://www.linkedin.com/in/thomas-bernard",
                "evidence_url": "",
                "confidence": "medium",
            },
        ],
        # And the angles repeat the searches the app already builds, so they add
        # nothing the candidate did not already have.
        "angles": [
            {"label": "Recruiters", "keywords": "Nimbus Labs recruiter", "why": "They recruit."},
        ],
        "company_linkedin_slug": "nimbus-labs",
        "approach": ["Be professional.", "Follow up if they do not answer."],
        "notes": "",
        "sources": [],
        "language": "en",
    },
)


CASES: list[EvalCase] = [
    FABRICATED_RESUME,
    GENERIC_COVER_LETTER,
    UNSOURCED_INTERVIEW_PREP,
    FABRICATED_CONTACTS,
    GOOD_RESUME,
]
