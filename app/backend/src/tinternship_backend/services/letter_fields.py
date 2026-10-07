"""The blanks in a cover letter that are records rather than writing.

A cover letter's blanks are not all the same kind of question. Three of them are
the letter — the opening, the middle and the closing paragraph — and the rest
are an address block: today's date, the employer's name, the reference of the
posting being answered, the street it is on. This module decides which is which,
and answers the second group in Python before the agent is asked anything.

## Why not simply ask the model for all of them

Two different reasons, and they are the two the whole codebase already runs on:

* **The date is not knowable by a model.** It has no clock. Asked to date a
  letter it writes a plausible one, which is the failure mode that made every
  link get fetched before it is saved. `datetime.now()` costs nothing and cannot
  be wrong.
* **The employer's name is a column on the row the candidate already
  validated.** "Agents produce, Python persists — and joins": a field a model
  copies is a field it can corrupt, and a letter addressed to *Nimbus Labs SAS*
  when the Tracker says *Nimbus Labs* is a letter that reads as a mail merge.

The line between the two groups is narrower than "is it in the database", and
it has to be. **Python answers a blank only when there is exactly one correct
string and nothing to fit it to.** A date and a company name drop into a line
whole. The posting's *reference* does not, and it was moved back to the agent
the first time it was tried here: the French template reads
`Candidature au stage [job_posting_name]`, and a French posting is very often
titled *Stage – Data Scientist (H/F)*, so copying the row verbatim produced
"Candidature au stage Stage – Data Scientist (H/F)". Choosing the words that
complete *the candidate's own sentence* is the judgement the whole fill design
hands to the model, and it is not something a column lookup can do.

What is left over is genuinely the model's, then: the paragraphs, the reference
line, and the team to address — the posting names one or it does not, and
choosing is reading.

## And the ones nobody can answer

A street address and a postal code are on the posting sometimes and nowhere
else ever. The model may copy them when the posting states them, and otherwise
**leaves the line empty**: an empty address line in a letter is normal, and an
invented one is a fabricated fact on a document going to an employer. Every
other blank must come back with real text — an empty paragraph is not
"unknown", it is a broken letter.

`address_keys()` marks that block, and it earns its place twice. Those lines may
be empty, and they are also **not prose**, so the language gate does not read
them: *12 rue de la Paix* is the correct address of a French employer in a
letter written in English, and a check that counted its *de* and its *la* would
fail a run for getting a place name right. Everything else the agent writes is
still read word by word.

## How a blank is recognised

By the name the candidate gave it, normalised: `[current_month_letters]`,
`{{company_name}}` and `<Company Name>` are all `company_name`. That is the same
mechanism the résumé's blanks use — the candidate steers a run by naming a
blank, without touching a prompt — so a name this does not recognise is not an
error: it simply goes to the agent, which reads the name too.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .docx_template import Slot
from .languages import normalise_language

# Month names, in the language the letter is written in. Word does not resolve a
# date field for us — the candidate typed a placeholder, not a `DATE` field — so
# the names live here.
MONTHS: dict[str, tuple[str, ...]] = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "fr": (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ),
}


@dataclass(frozen=True)
class LetterFacts:
    """What Python knows about the letter before anyone writes a word of it."""

    language: str
    company: str = ""
    today: date | None = None

    @property
    def day(self) -> date:
        return self.today or date.today()


def _day_of_month(facts: LetterFacts) -> str:
    """`9`, and `1er` on the first of a French month.

    French writes *le 1er septembre* and *le 2 septembre*: the ordinal exists
    for one day in twelve and looks wrong the rest of the time. English
    templates here write `September 9, 2026`, with no ordinal at all.
    """
    number = facts.day.day
    if number == 1 and normalise_language(facts.language) == "fr":
        return "1er"
    return str(number)


def _month(facts: LetterFacts) -> str:
    return MONTHS[normalise_language(facts.language)][facts.day.month - 1]


def _full_date(facts: LetterFacts) -> str:
    if normalise_language(facts.language) == "fr":
        return f"{_day_of_month(facts)} {_month(facts)} {facts.day.year}"
    return f"{_month(facts)} {facts.day.day}, {facts.day.year}"


# The blanks Python answers, by normalised name. Each entry is every spelling
# worth recognising for one field: the candidate writes their own template and
# nobody should have to look up which synonym this module happened to pick.
KNOWN: dict[str, Callable[[LetterFacts], str]] = {}


def _register(resolver: Callable[[LetterFacts], str], *names: str) -> None:
    for name in names:
        KNOWN[name] = resolver


_register(_day_of_month, "current_date", "current_day", "date_day", "day")
_register(_month, "current_month_letters", "current_month", "month", "month_letters")
_register(lambda facts: str(facts.day.year), "current_year", "year")
_register(_full_date, "current_date_full", "todays_date", "today", "date")
_register(lambda facts: facts.company, "company_name", "company", "employer_name", "employer")

# The address block: where the employer is. Deliberately short, and it is the
# only group with these two exemptions — a fill here may be empty, and it is not
# read by the language gate. A blank not listed here has to come back with real
# text, in the language the run asked for.
ADDRESS_BLOCK = frozenset(
    {
        "address_company",
        "company_address",
        "address",
        "street_company",
        "postal_code_company",
        "company_postal_code",
        "postal_code",
        "zip_code_company",
        "city_company",
        "company_city",
        "city",
    }
)


def field_name(token: str) -> str:
    """The name inside a placeholder, normalised: `[Company Name]` → `company_name`."""
    inner = token.strip().strip("[]{}<>").strip()
    return re.sub(r"[^a-z0-9]+", "_", inner.lower()).strip("_")


def known_fills(slots: list[Slot], facts: LetterFacts) -> dict[str, str]:
    """The blanks Python answers, as `{slot key: text}`.

    A field that resolves to nothing — a posting with no company name on it,
    which happens to a pasted posting — is *not* returned, so the blank stays
    the agent's rather than being filled with an empty string it cannot see.
    """
    fills: dict[str, str] = {}
    for slot in slots:
        resolver = KNOWN.get(field_name(slot.token))
        if resolver is None:
            continue
        value = str(resolver(facts)).strip()
        if value:
            fills[slot.key] = value
    return fills


def resolver(facts: LetterFacts) -> Callable[[list[Slot]], dict[str, str]]:
    """`known_fills` bound to one letter's facts, for `base_documents.plan`."""

    def resolve(slots: list[Slot]) -> dict[str, str]:
        return known_fills(slots, facts)

    return resolve


def address_keys(slots: list[Slot]) -> set[str]:
    """The slots that are a place rather than a sentence.

    Two consequences, both in `agents/applying.py::hard_check`: they may come
    back empty, and they are excluded from the language check.
    """
    return {slot.key for slot in slots if field_name(slot.token) in ADDRESS_BLOCK}
