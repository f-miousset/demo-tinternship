"""Read/write access to the single master profile."""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from ..agents.schemas import MasterProfile
from ..db.engine import session_scope
from ..db.models import Profile, utcnow


def get_profile() -> Profile | None:
    with session_scope() as session:
        profile = session.exec(select(Profile).order_by(Profile.id)).first()
        if profile is not None:
            session.expunge(profile)
        return profile


def save_profile(master: MasterProfile) -> Profile:
    """Overwrite the master profile with a freshly merged extraction."""
    payload = master.model_dump()
    with session_scope() as session:
        profile = session.exec(select(Profile).order_by(Profile.id)).first()
        if profile is None:
            profile = Profile()
        profile.full_name = master.full_name
        profile.headline = master.headline
        profile.email = master.email
        profile.phone = master.phone
        profile.location = master.location
        profile.linkedin_url = master.linkedin_url or profile.linkedin_url
        profile.github_url = master.github_url or profile.github_url
        profile.portfolio_url = master.portfolio_url or profile.portfolio_url
        profile.summary = master.summary
        profile.data = {
            key: payload[key]
            for key in (
                "experiences",
                "education",
                "projects",
                "skills",
                "languages",
                "certifications",
                "awards",
                "interests",
                "extraction_notes",
            )
        }
        profile.updated_at = utcnow()
        session.add(profile)
        session.flush()
        session.refresh(profile)
        session.expunge(profile)
        return profile


def profile_as_dict() -> dict[str, Any]:
    profile = get_profile()
    if profile is None:
        return {}
    return {
        "full_name": profile.full_name,
        "headline": profile.headline,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
        "summary": profile.summary,
        **(profile.data or {}),
    }


def has_lists() -> bool:
    """Whether both lists the résumé's blanks are filled from have been written.

    They live in their own table since 2026-09-08 (one row per item, carrying
    both languages), so this is one line of delegation kept for its callers:
    `onboarding.REQUIRED` and the setup checklist both ask the profile whether
    the candidate is ready, and the lists are part of that answer wherever they
    happen to be stored. See `services/candidate_lists.py`.
    """
    from . import candidate_lists

    return candidate_lists.complete()


def has_profile() -> bool:
    profile = get_profile()
    if profile is None:
        return False
    data = profile.data or {}
    return bool(profile.full_name or data.get("experiences") or data.get("education"))
