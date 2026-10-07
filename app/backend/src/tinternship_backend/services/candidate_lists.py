"""The two lists the résumé's blanks are filled from, in both languages.

Every course the candidate has taken and every skill they have, written by hand,
one row per item and each row carrying the English **and** the French spelling.

They are the menu two of the candidate's own blanks are selections from —
`[list_of_relevant_courses]` and `[list_of_relevant_skills]` — so the rule
attached to them is absolute: *select, never invent*. An item that is not here
does not go on the page, however well it would have suited the posting.

## Why both languages, per item

They were two free-text boxes until 2026-09-08 (`profile.courses` and
`profile.skills_pool`, one item per line), written once in whichever language
the candidate thought in. Their courses were all French and most of their skills
were English, so *every* run had to translate one list or the other, inside a
blank priced in characters, with nobody able to check the result — "Traitement
automatique de l'information" came back as a different course each time, and
"Recherche opérationnelle, optimisation combinatoire" came back longer than the
line it had to fit in.

Translating a course title is not a language task, it is a fact: it is whatever
that course is actually called on an English transcript, and the candidate is
the only person who knows. So they write both, once, and the run *copies*.

That is why both sides are required. A missing side would have to fall back to
the other one, which puts a French course on an English CV silently — the exact
failure this replaced. `add()` and `update()` refuse it instead.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from ..db.engine import session_scope
from ..db.models import CandidateListItem, CandidateListKind, utcnow

# One item is a course title or a skill name, not a description of one. Long
# enough for "Conception de bases de données relationnelles et non
# relationnelles" (the candidate's own longest, 66 characters) with room to
# spare; short enough that a pasted paragraph is rejected here rather than
# discovered in a blank with a 60-character budget.
MAX_LENGTH = 160


class CandidateListError(ValueError):
    """Something the candidate typed cannot be saved, with the reason why."""


def _normalise_kind(kind: str) -> str:
    try:
        return CandidateListKind(str(kind).strip().lower()).value
    except ValueError as exc:
        raise CandidateListError(
            f"Unknown list {kind!r}. There are two: course and skill."
        ) from exc


def _clean(value: str, *, language: str) -> str:
    """One side of one item, or the reason it cannot be stored.

    Newlines are refused rather than stripped: a value with one in it is almost
    always a whole list pasted into the box for a single item, and silently
    saving it as one item would put "Python\\nSQL\\nDocker" on a résumé line.
    """
    text = str(value or "").strip()
    name = "English" if language == "en" else "French"
    if not text:
        raise CandidateListError(
            f"Write the {name} wording too — an item is only usable in a language it exists in."
        )
    if "\n" in text or "\r" in text:
        raise CandidateListError(
            f"One item at a time: the {name} field has a line break in it. "
            "Add the next one with the button."
        )
    if len(text) > MAX_LENGTH:
        raise CandidateListError(
            f"The {name} wording is {len(text)} characters. "
            f"An item is a title, not a description — keep it under {MAX_LENGTH}."
        )
    return text


def _payload(item: CandidateListItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "en": item.en,
        "fr": item.fr,
        "position": item.position,
    }


def all_items() -> dict[str, list[dict[str, Any]]]:
    """Both lists, in the candidate's own order, as the Account page reads them."""
    lists: dict[str, list[dict[str, Any]]] = {kind.value: [] for kind in CandidateListKind}
    with session_scope() as session:
        rows = session.exec(
            select(CandidateListItem).order_by(
                CandidateListItem.kind, CandidateListItem.position, CandidateListItem.id
            )
        ).all()
        # Serialised inside the session: a committed row is expired, and reading
        # one of its columns afterwards raises `DetachedInstanceError`.
        for row in rows:
            lists.setdefault(row.kind, []).append(_payload(row))
    return lists


def items(kind: str) -> list[dict[str, Any]]:
    return all_items().get(_normalise_kind(kind), [])


def add(kind: str, en: str, fr: str) -> dict[str, Any]:
    """One new item, both spellings, at the end of its list."""
    kind = _normalise_kind(kind)
    english, french = _clean(en, language="en"), _clean(fr, language="fr")

    with session_scope() as session:
        existing = session.exec(
            select(CandidateListItem).where(CandidateListItem.kind == kind)
        ).all()
        _refuse_duplicate(existing, english, french, kind=kind)
        item = CandidateListItem(
            kind=kind,
            en=english,
            fr=french,
            position=max((row.position for row in existing), default=-1) + 1,
        )
        session.add(item)
        session.flush()
        return _payload(item)


def update(item_id: int, en: str, fr: str) -> dict[str, Any]:
    """Correct one item — which is most of what this page is used for.

    The lists arrive already written (the 2026-09-08 migration copied every line
    into both languages) and get fixed one item at a time, so editing is not a
    secondary path here: it is how a seeded item becomes a real one.
    """
    english, french = _clean(en, language="en"), _clean(fr, language="fr")

    with session_scope() as session:
        item = session.get(CandidateListItem, item_id)
        if item is None:
            raise CandidateListError(f"No list item {item_id}.")
        others = [
            row
            for row in session.exec(
                select(CandidateListItem).where(CandidateListItem.kind == item.kind)
            ).all()
            if row.id != item_id
        ]
        _refuse_duplicate(others, english, french, kind=item.kind)
        item.en, item.fr = english, french
        item.updated_at = utcnow()
        session.add(item)
        session.flush()
        return _payload(item)


def remove(item_id: int) -> None:
    with session_scope() as session:
        item = session.get(CandidateListItem, item_id)
        if item is None:
            raise CandidateListError(f"No list item {item_id}.")
        session.delete(item)


def _refuse_duplicate(
    existing: list[CandidateListItem], en: str, fr: str, *, kind: str
) -> None:
    """Refuse an item already on this list, in either language.

    A duplicate is not a harmless extra row: the two lists are what a blank is
    filled from, and the same course twice on one coursework line is a typo
    reaching an employer. Case- and accent-insensitive matching is deliberately
    not attempted — "Analyse de données" and "analyse de donnees" are the same
    course, but deciding that reliably is a different problem, and this catches
    the case that actually happens (adding the same item twice).
    """
    label = "course" if kind == CandidateListKind.COURSE else "skill"
    for row in existing:
        if row.en.casefold() == en.casefold() or row.fr.casefold() == fr.casefold():
            raise CandidateListError(
                f"That {label} is already on the list — “{row.en}” / “{row.fr}”."
            )


def complete() -> bool:
    """Whether both lists have something in them.

    Required to finish setup, not optional: a coursework or skills blank with no
    list behind it leaves the Tailor choosing between an unfinished sentence and
    an invented qualification, and neither is acceptable on a document going to
    an employer.
    """
    lists = all_items()
    return bool(lists.get(CandidateListKind.COURSE) and lists.get(CandidateListKind.SKILL))


def in_language(kind: str, language: str) -> list[str]:
    """One list, as the candidate spelled it in the language of this run.

    The whole point of the table: what comes back is what goes on the page, so a
    run selects from it rather than translating it. An item with nothing on this
    side is skipped rather than substituted from the other one — a blank that is
    one item shorter is recoverable, a French course on an English CV is not.
    """
    side = "fr" if str(language).lower().startswith("fr") else "en"
    return [item[side].strip() for item in items(kind) if item[side].strip()]
