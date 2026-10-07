"""Versioned store for the editable system prompts.

The Interrogator and HR Expert each produce a prompt that steers everything
downstream. The user can edit those prompts, and every edit creates a new
version rather than mutating the old one — so a trace can always be replayed
against the exact text that was in force at the time.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from ..db.engine import session_scope
from ..db.models import AgentPrompt, PromptKind


def _next_version(session: Session, kind: str) -> int:
    latest = session.exec(
        select(AgentPrompt).where(AgentPrompt.kind == kind).order_by(AgentPrompt.version.desc())
    ).first()
    return (latest.version + 1) if latest else 1


def save_prompt(
    kind: str,
    *,
    content: str,
    structured: dict[str, Any] | None = None,
    title: str = "",
    author: str = "agent",
    note: str = "",
    invocation_id: str = "",
) -> AgentPrompt:
    """Create a new active version, deactivating whatever was active before."""
    with session_scope() as session:
        for existing in session.exec(
            select(AgentPrompt).where(AgentPrompt.kind == kind, AgentPrompt.is_active)
        ).all():
            existing.is_active = False
            session.add(existing)

        prompt = AgentPrompt(
            kind=kind,
            version=_next_version(session, kind),
            title=title,
            content=content,
            structured=structured or {},
            is_active=True,
            author=author,
            note=note,
            invocation_id=invocation_id,
        )
        session.add(prompt)
        session.flush()
        session.refresh(prompt)
        session.expunge(prompt)
        return prompt


def get_active(kind: str) -> AgentPrompt | None:
    with session_scope() as session:
        prompt = session.exec(
            select(AgentPrompt)
            .where(AgentPrompt.kind == kind, AgentPrompt.is_active)
            .order_by(AgentPrompt.version.desc())
        ).first()
        if prompt is not None:
            session.expunge(prompt)
        return prompt


def list_versions(kind: str | None = None) -> list[AgentPrompt]:
    with session_scope() as session:
        statement = select(AgentPrompt).order_by(
            AgentPrompt.kind, AgentPrompt.version.desc()
        )
        if kind:
            statement = statement.where(AgentPrompt.kind == kind)
        prompts = list(session.exec(statement).all())
        for prompt in prompts:
            session.expunge(prompt)
        return prompts


def activate(prompt_id: int) -> AgentPrompt | None:
    """Roll back to an earlier version by making it active again."""
    with session_scope() as session:
        target = session.get(AgentPrompt, prompt_id)
        if target is None:
            return None
        for existing in session.exec(
            select(AgentPrompt).where(AgentPrompt.kind == target.kind, AgentPrompt.is_active)
        ).all():
            existing.is_active = False
            session.add(existing)
        target.is_active = True
        session.add(target)
        session.flush()
        session.refresh(target)
        session.expunge(target)
        return target


def get_active_structured(kind: str) -> dict[str, Any]:
    prompt = get_active(kind)
    return dict(prompt.structured) if prompt and prompt.structured else {}


# ---------------------------------------------------------------------------
# Rendering structured payloads into instruction text
# ---------------------------------------------------------------------------


def render_search_brief(brief: dict[str, Any]) -> str:
    """Turn a SearchBrief into the instruction block downstream agents receive."""

    def block(label: str, value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, list):
            return f"- **{label}**: " + "; ".join(str(v) for v in value)
        return f"- **{label}**: {value}"

    lines = [
        "# Search brief",
        "",
        brief.get("headline", "") or "",
        "",
    ]
    fields = [
        ("Roles", brief.get("role_titles")),
        ("Domain", brief.get("domain")),
        ("Level", brief.get("seniority")),
        ("Start", brief.get("start_date")),
        ("End", brief.get("end_date")),
        ("Duration", brief.get("duration")),
        ("Locations", brief.get("locations")),
        ("Remote preference", brief.get("remote_preference")),
        ("Relocation", brief.get("relocation")),
        ("Work authorisation", brief.get("work_authorisation")),
        ("Languages", brief.get("languages")),
        ("Employer profile", brief.get("company_profile")),
        ("Target companies", brief.get("target_companies")),
        ("Excluded companies", brief.get("excluded_companies")),
        ("Must have", brief.get("must_haves")),
        ("Nice to have", brief.get("nice_to_haves")),
        ("Deal breakers", brief.get("deal_breakers")),
        ("Candidate skills", brief.get("skills")),
        ("Compensation", brief.get("compensation_expectation")),
        ("Education", brief.get("education")),
        ("Search keywords", brief.get("search_keywords")),
        ("Still unknown", brief.get("open_questions")),
    ]
    lines.extend(line for line in (block(label, value) for label, value in fields) if line)
    return "\n".join(lines).strip()


def render_playbook(playbook: dict[str, Any]) -> str:
    """Turn a HiringPlaybook into the instruction block downstream agents receive."""

    def section(label: str, value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, list):
            items = "\n".join(f"- {v}" for v in value)
            return f"### {label}\n{items}"
        return f"### {label}\n{value}"

    parts = [
        "# Hiring playbook",
        "",
        playbook.get("summary", "") or "",
        section("Domain insights", playbook.get("domain_insights")),
        section("Hiring timeline", playbook.get("hiring_timeline")),
        section("Where to search", playbook.get("where_to_search")),
        section("Search query patterns", playbook.get("search_query_patterns")),
        section("Résumé guidance", playbook.get("resume_guidance")),
        section("ATS keywords", playbook.get("ats_keywords")),
        section("Cover letter guidance", playbook.get("cover_letter_guidance")),
        section("Interview expectations", playbook.get("interview_expectations")),
        section("Outreach strategy", playbook.get("outreach_strategy")),
        section("Common mistakes", playbook.get("common_mistakes")),
        section("Red flags in postings", playbook.get("red_flags_in_postings")),
    ]
    for extra in playbook.get("extra_sections") or []:
        if isinstance(extra, dict):
            parts.append(section(extra.get("title", "Notes"), extra.get("advice")))

    sources = playbook.get("sources") or []
    if sources:
        rendered = "\n".join(
            f"- {s.get('title', '')} — {s.get('url', '')}: {s.get('takeaway', '')}"
            for s in sources
            if isinstance(s, dict)
        )
        parts.append(f"### Sources\n{rendered}")

    return "\n\n".join(p for p in parts if p).strip()


RENDERERS = {
    PromptKind.SEARCH_BRIEF: render_search_brief,
    PromptKind.PLAYBOOK: render_playbook,
}


def render(kind: str, structured: dict[str, Any]) -> str:
    renderer = RENDERERS.get(kind)  # type: ignore[arg-type]
    if renderer is None:
        return json.dumps(structured, indent=2, ensure_ascii=False)
    return renderer(structured)
