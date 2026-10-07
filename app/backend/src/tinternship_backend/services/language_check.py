"""Catching the other language in a document that was supposed to be in one.

The complaint this exists for (2026-08-28): a French résumé kept arriving with
English still in it — a section heading, a connector, half a bullet — because
the posting, the profile and most of the instructions around the model were in
English, and nothing downstream ever looked. The Critic was asked to score
`language` and did, from impressions, on JSON.

So the check is arithmetic instead. It is a **hard check**, in the same class as
the block budget: not a score, a fact about the text.

## Function words only, and why

The obvious detector — "does this French document contain English words?" —
fires on every good French CV ever written. *Machine Learning*, *Data Science*,
*Software Engineer*, *Product Owner*, *Master of Science*, *cloud*, *pipeline*,
*dashboard*: these are what the field calls itself, and a French posting will
use them verbatim. Rejecting them would push the model to translate exactly the
strings the ATS is searching for, which is worse than the bug being fixed.

What a technical proper noun never contains is a **grammatical function word**.
"Machine Learning" has no *the*, no *and*, no *with*, no *which*. So the marker
lists here hold nothing but articles, pronouns, auxiliaries, conjunctions and
prepositions — the connective tissue you cannot write a sentence without and
cannot get into a job title by accident.

And words that exist in *both* languages are struck out by hand rather than by
rule: `on`, `plus`, `car`, `son`, `sur`, `fin`, `mine`, `note`, `ton`, `pas`,
`as`, `or`, `me`, `sale`, `pain`, `coin`, `point`. That exclusion list is the
whole reason this file is data and not a clever heuristic — and it is why
`including`, `using`, `managed` and `built` are absent too: they are content
words, and `Azure Managed Identity` is a product name a French CV may well
carry.

## Three things on a CV that are not prose (2026-09-10)

The premise above — "a technical proper noun never contains a function word" —
is true of the English terms a French CV carries, and false of everything else
on the page. Both of the candidate's own résumés were flagged, each of them
correctly filed:

* **Placeholder names.** The Account page tells them to leave
  `[list_of_relevant_skills]`, so their French CV carries `of` twice by
  following the instructions. A blank's *name* is not the document's language,
  and what lands in it is checked separately, on the fills, in the language the
  run was asked for.
* **Links.** `linkedin.com/in/alex-martin` is on every CV in both
  languages and tokenises to `in`.
* **Names in the other language.** French institutions are *built* out of
  function words — `Université de Technologie de Lyon`, `Nuits de la
  Recherche` — and an English CV has to spell them the way they are spelled.
  Nine `de` and one `la`, all of them one employer and one event.

So markers are counted only in prose: placeholders and links are cut out, and a
run of markers wedged between two capitalised words is read as part of a name
rather than as a sentence. The cost is that a *title* in the wrong language
("Work Experience and Skills" left on a French CV) now reads as a name and
passes — which is the trade this whole file is built on, since a title is
exactly as likely to be `Bank of America`. A wrong-language *sentence* still
cannot hide: prose puts a lowercase word on at least one side of its markers.

## A threshold, not a tripwire

One marker is not evidence: `Master of Science` is a degree, `of` is a marker,
and a French CV may legitimately carry both. Two *distinct* markers, or three
occurrences, is a sentence — and a sentence in the wrong language is the bug.
`tests/test_language_check.py` pins both directions, including the CV that must
pass.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import docx_template
from .languages import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalise_language

# At least this many distinct markers, or this many occurrences in total, before
# a document is called wrong. Below it, a marker is a loanword or a degree name.
DISTINCT_THRESHOLD = 2
TOTAL_THRESHOLD = 3

# English grammatical words that cannot appear inside a French technical term.
# `of` is in, deliberately and knowingly: "Master of Science" alone stays under
# the threshold, and "a team of five engineers responsible for" does not.
_ENGLISH_MARKERS = frozenset(
    """
    the and of to in is are was were be been being have has had do does did
    will would shall should can could may might must
    with from that which who whom whose what when where why how
    this these those they them their there here our your my his her its
    but or if not no nor so than then because while during through
    about into onto within without across between among against toward towards
    above below under over after before again already always another
    any both each every few many more most other same some such
    also however therefore thus yet still only just very
    i'm it's don't didn't we've we're you're
    """.split()
)

# French grammatical words that cannot appear inside an English technical term.
# `plus`, `on`, `car`, `son`, `note`, `mine`, `fin`, `pas`, `sur`, `dans`, `as`
# and `or` are left out on purpose: every one of them is also an English word.
_FRENCH_MARKERS = frozenset(
    """
    le la les des du de au aux un une et à en ne se si
    avec pour dans par chez vers depuis pendant afin ainsi donc lors selon
    mais où que qui quoi dont lequel laquelle lesquels
    cette ces cet celui celle ceux nous vous ils elles leur leurs
    notre nos votre vos mes tes ses est sont était étaient été
    avoir avons avez ont avait avaient être suis sommes êtes
    peut peuvent doit doivent très bien entre parmi sous même
    plusieurs chaque toutes tous toute tout quelques
    d'un d'une l'un l'une j'ai n'est c'est qu'il qu'elle
    """.split()
)

_MARKERS = {"en": _ENGLISH_MARKERS, "fr": _FRENCH_MARKERS}

# Apostrophes matter: `d'une` and `c'est` are single French markers, and the
# typographic apostrophe is what Word actually inserts.
_TOKEN = re.compile(r"[a-zà-öø-ÿ]+(?:['’][a-zà-öø-ÿ]+)?", re.IGNORECASE)

# An email address, or a URL with or without its scheme. `linkedin.com/in/...`
# has no `https://` on a CV and still is not a sentence containing "in".
_LINK = re.compile(r"\S*(?:@|://|\.[a-z]{2,}/)\S*", re.IGNORECASE)


def _prose(text: str) -> str:
    """The text with everything that is not the candidate's own sentences cut out.

    Placeholders go through `docx_template`, which owns their grammar, rather
    than through a second copy of those patterns here: a blank the candidate
    spelled `{{list_of_relevant_skills}}` is the same non-prose as one they
    spelled `[list_of_relevant_skills]`, and only one file should know that.
    """
    for start, end, _ in reversed(docx_template.placeholder_spans(text)):
        text = f"{text[:start]} {text[end:]}"
    return _LINK.sub(" ", text)


def _words(line: str) -> list[str]:
    """Every word of one line, in the case it was written in.

    The case is what tells a name from a sentence, so it is kept here and lowered
    only where a word is compared against the marker lists. One line at a time
    because that is the unit a name lives in: the word ending the line above is
    not the word before this one.
    """
    normalised = unicodedata.normalize("NFC", line).replace("’", "'")
    return [match.group(0) for match in _TOKEN.finditer(normalised)]


def _inside_a_name(words: list[str], start: int, end: int) -> bool:
    """Whether the markers at `words[start:end]` are the middle of a proper name.

    `Université de Technologie`, `Nuits de la Recherche`, `Bank of America`,
    `Master of Science`: a capitalised word on both sides of the run, with the
    whole run taken together so that `de la` is judged once rather than twice.
    A sentence never looks like this — the words around its connectives are
    ordinary lowercase words.
    """
    if start == 0 or end >= len(words):
        return False
    return words[start - 1][:1].isupper() and words[end][:1].isupper()


def markers_in(text: str, language: str) -> dict[str, int]:
    """Function words of `language` found in the text's prose, with their counts.

    Prose is the operative word: placeholders, links and the insides of proper
    names are not it, and every one of them was a false alarm on a document
    filed in the right language. See the module docstring.

    Two questions are asked of this one scan, and they are the same measurement
    pointed in opposite directions. `foreign_markers` asks how much of the
    *other* language is in a document that was supposed to be in one — the gate.
    `detect` asks which of the two languages has more of itself in a text nobody
    has declared a language for — the guess. Sharing the scan is not a tidiness
    argument: the exclusions are the whole value of this file, and a second
    counter written without them would read every French university name as a
    French sentence and every `Master of Science` as an English one.
    """
    markers = _MARKERS.get(normalise_language(language), frozenset())
    counts: dict[str, int] = {}
    for line in _prose(text).splitlines():
        words = _words(line)
        lowered = [word.lower() for word in words]
        index = 0
        while index < len(words):
            if lowered[index] not in markers:
                index += 1
                continue
            run = index
            while run < len(words) and lowered[run] in markers:
                run += 1
            if not _inside_a_name(words, index, run):
                for word in lowered[index:run]:
                    counts[word] = counts.get(word, 0) + 1
            index = run
    return counts


def foreign_markers(text: str, language: str) -> dict[str, int]:
    """Words of the *other* language found in the text's prose, with their counts.

    Only the two languages the app supports are checked. An unsupported code
    falls back through `normalise_language`, so this can never raise on the path
    that produces a document.
    """
    wanted = normalise_language(language)
    return markers_in(text, "en" if wanted == "fr" else "fr")


# Below this many marker occurrences on the winning side, a text has not said
# which language it is in — it is a title, a fragment, or a language this app
# does not write in. The same reasoning as `TOTAL_THRESHOLD` above: one function
# word is a loanword, a handful of them is a sentence.
DETECT_FLOOR = 3


def detect(text: str) -> str:
    """Which of the two supported languages this text is written in.

    Counts each language's own function words and takes the larger side. That
    works here for the reason the module docstring gives: a technical proper
    noun never contains a function word, so the English terms a French posting
    is full of — *Machine Learning*, *pipeline*, *Product Owner* — contribute
    nothing to the English side, while its own *le*, *des*, *pour* and *vous*
    contribute to the French one. A detector counting words rather than function
    words would call half the French tech market English.

    Falls back to `DEFAULT_LANGUAGE` on a tie and below `DETECT_FLOOR`, which is
    the honest answer to "this text has not told me": a posting in German, or a
    title with no prose under it. There is no third package language to fall
    back to — the candidate uploaded two documents — so the question is only ever
    which of the two, and the default is the one the rest of the app defaults to.
    """
    scores = {code: sum(markers_in(text, code).values()) for code in SUPPORTED_LANGUAGES}
    best = max(scores, key=lambda code: scores[code])
    if scores[best] < DETECT_FLOOR:
        return DEFAULT_LANGUAGE
    # A tie is not an answer. `max` would resolve it by declaration order, which
    # is a coin toss dressed up as a decision.
    if list(scores.values()).count(scores[best]) > 1:
        return DEFAULT_LANGUAGE
    return best


# The posting's own prose, and only that. `company`, `location` and `source` are
# names — "Société Générale" is not evidence that a posting is in French, and
# `_inside_a_name` would mostly discount them anyway. These five fields are what
# the agent that read the posting wrote **in the posting's own language**, which
# is exactly the question being asked.
POSTING_PROSE = ("title", "summary", "description", "requirements", "nice_to_have")


def posting_language(posting: Any) -> str:
    """The language an application package for this posting should be written in.

    You answer a posting in the language it was advertised in — the rule the
    Applying prompts have always stated, now decided rather than asked about. It
    is measured off the saved posting rather than off the page it came from, so
    the answer is the same whichever of the three ways in produced the row, and
    so a posting whose page was 400 KB of navigation chrome is judged on the
    eight fields an agent actually read out of it.

    Takes a `JobPosting` row or the dict a run produced — `getattr` first, then
    `get` — because the two callers hold different shapes of the same posting.

    It is a guess, and it is allowed to be wrong: it lands on
    `application.language`, which is the *default* the language picker opens on.
    Changing it is one control and one button on the application page.
    """
    parts: list[str] = []
    for field in POSTING_PROSE:
        value = getattr(posting, field, None)
        if value is None and isinstance(posting, dict):
            value = posting.get(field)
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return detect("\n".join(parts))


def wrong_language(text: str, language: str) -> str:
    """A sentence naming the leftovers, or `""` when the text is clean.

    The message is written to be handed straight to the agent as gate feedback,
    so it names the actual words rather than saying "there is English in it" —
    a model told *which* words can fix them, and a model told there is a problem
    somewhere rewrites the whole document.
    """
    counts = foreign_markers(text, language)
    if not counts:
        return ""
    total = sum(counts.values())
    if len(counts) < DISTINCT_THRESHOLD and total < TOTAL_THRESHOLD:
        return ""

    wanted = normalise_language(language)
    names = {"en": "English", "fr": "French"}
    worst = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    listed = ", ".join(f'"{word}" ×{count}' if count > 1 else f'"{word}"' for word, count in worst)
    return (
        f"This is supposed to be in {names[wanted]} and still has {names['en' if wanted == 'fr' else 'fr']} "
        f"in it: {listed}. Rewrite every phrase those words are in. Keep proper nouns, product "
        "names, technology names and the posting's own keyword strings exactly as they are — "
        "it is the sentences around them that must be in "
        f"{names[wanted]}."
    )
