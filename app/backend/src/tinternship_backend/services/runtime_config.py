"""The few settings the Settings page can change without a restart.

`.env` still holds everything else, and everything else in it stays a file you
edit and restart for. But the knobs worth actually turning — which model does
the thinking, which does the cheap passes, how good a document has to be, how
many rewrites it gets to become that, how long an application may go unanswered
before it is raised, and how hard a stale posting is pushed down the ranking —
are the ones you want to try a value of, look at a run, and try another.
Redeploying between each attempt is a bad trade, so those are also rows in
`setting_override`, and the stored row wins over the default.

The mechanism is deliberately small. `get_settings()` is `lru_cache`d, so all
~40 call sites share a single `Settings` instance, and every agent reads
`settings.model_primary` inside its `build_*` factory rather than at import
time. Assigning onto that one instance is therefore enough: the next agent
built — the next run — sees the new value, with no restart and no plumbing
through forty signatures.

`_BASELINE` is the catch. Assigning overwrites where the value started, so it
is snapshotted the first time this module touches the settings, before anything
is applied. That snapshot is what "restore defaults" puts back, and what
`save()` compares against to decide a row is redundant.

The baseline is the field default on `Settings` — *not* `.env`, which no longer
carries these seven. An environment variable still overrides that default if one
is set, which is the bootstrap path for a machine that has to come up on
something else; it is not how you change a setting day to day. Saying "`.env`"
where this really means "the starting value" is what made the UI claim `.env`
said things it does not mention. See documentation/configuration.md.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlmodel import delete, select

from ..agents.models import is_local
from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import SettingOverride, utcnow
from . import gemini_models, ollama_models

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Knob:
    """One editable setting: the field on `Settings`, plus what the UI needs."""

    key: str
    label: str
    help: str
    kind: Literal["model", "number"]
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    integer: bool = False
    # Which providers this model knob accepts. Grounding is Gemini-only, so one
    # of the three is narrower than the others.
    providers: tuple[str, ...] = ("gemini", "ollama")


KNOBS: tuple[Knob, ...] = (
    Knob(
        key="model_primary",
        label="Reasoning model",
        help=(
            "Runs the interview, the matcher, and everything that writes a document. "
            "The expensive half of the bill, and the one worth running locally."
        ),
        kind="model",
    ),
    Knob(
        key="model_fast",
        label="Fast model",
        help=(
            "Runs the cheap passes — query planning, cleaning up raw leads, and the "
            "Critic that scores each draft."
        ),
        kind="model",
    ),
    Knob(
        key="model_grounded",
        label="Search model",
        help=(
            "Runs the Scout and the HR researcher, the two agents that search the web. "
            "Google Search is a Gemini feature, so this one stays on the API even when "
            "the others are local."
        ),
        kind="model",
        providers=("gemini",),
    ),
    Knob(
        key="audit_pass_threshold",
        label="Quality threshold",
        help=(
            "The score out of 10 a generated document has to reach before the quality "
            "gate lets it through. Higher means more rewrites and a longer run."
        ),
        kind="number",
        minimum=0,
        maximum=10,
        step=0.5,
    ),
    Knob(
        key="audit_max_revisions",
        label="Max auto-revisions",
        help=(
            "How many times a document may be rewritten trying to clear the threshold. "
            "The last attempt is kept even if it never got there."
        ),
        kind="number",
        minimum=1,
        maximum=5,
        step=1,
        integer=True,
    ),
    Knob(
        key="follow_up_after_days",
        label="Follow up after",
        help=(
            "Days of silence on an application you are waiting on before the Tracker "
            "raises it and writes the chase email for you. Two weeks is the usual "
            "advice; raise it for sectors that hire slowly."
        ),
        kind="number",
        minimum=3,
        maximum=90,
        step=1,
        integer=True,
    ),
    Knob(
        key="posting_half_life_days",
        label="Freshness half-life",
        help=(
            "How many days it takes a posting to be worth half as much as an identical "
            "one published today. Lower pushes this week's openings to the top harder; "
            "higher lets an older but better match through."
        ),
        kind="number",
        minimum=3,
        maximum=120,
        step=1,
        integer=True,
    ),
)

BY_KEY: dict[str, Knob] = {knob.key: knob for knob in KNOBS}

# Which models get a star in the picker, per knob. A good Critic model is not a
# good writing model — the evidence below says so outright — which is why this
# is per-field rather than one "good models" list.
#
# The local entries come from running the golden cases in `evals/cases.py` (the
# four `make eval` holds the Critic to) once per candidate, on 2026-08-15:
#
#     gemma3:4b              4/4   105s      mistral-nemo:latest    4/4   191s
#     qwen3.5:9b             4/4   266s      qwen2.5:7b             3/4   151s
#     gemma3:12b             3/4   383s      llama3.1:latest        2/4   112s
#     mistral:7b             2/4   124s      gemma4:12b-mlx         0/4   126s
#
# `model_fast` is the Critic's seat, so the three that went 4/4 are starred
# there. `model_primary` writes the documents, which is a different job and was
# measured separately: each of those three wrote a cover letter through the real
# agent against a seeded profile and posting. gemma3:4b addressed it to an
# invented hiring manager — a different fabricated name on each run — which the
# honesty rules forbid outright, and none of the three cleared a 7.5 quality
# gate when scored. So nothing local is starred for the writing tier: it works,
# but the evidence does not support recommending it.
#
# Star nothing you have not run. A model missing here is untested, not rejected;
# re-run the sweep after `ollama pull` rather than trusting this list forever.
RECOMMENDED: dict[str, tuple[str, ...]] = {
    "model_primary": ("gemini-3.6-flash",),
    "model_fast": (
        "gemini-3.5-flash-lite",
        "ollama/mistral-nemo:latest",
        "ollama/qwen3.5:9b",
        "ollama/gemma3:4b",
    ),
    "model_grounded": ("gemini-3.6-flash",),
}

# Long enough for any real model id, short enough that a pasted essay is caught.
MAX_MODEL_LENGTH = 100

_BASELINE: dict[str, Any] = {}


def _coerce(knob: Knob, raw: Any) -> Any:
    """Validate one incoming value, or say why it is not usable."""
    if knob.kind == "model":
        value = str(raw).strip()
        if not value:
            raise ValueError(f"{knob.label} cannot be empty.")
        if len(value) > MAX_MODEL_LENGTH:
            raise ValueError(f"{knob.label} is not a model name.")
        if is_local(value) and "ollama" not in knob.providers:
            # Caught here rather than deep inside a run, where it surfaces as
            # "Google search tool is not supported for model ollama_chat/…".
            raise ValueError(
                f"{knob.label} has to be a Gemini model — Google Search grounding is "
                "part of the Gemini API and does not work on a local model."
            )
        return value

    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{knob.label} must be a number.") from exc
    if number != number:  # NaN survives float() as "nan"
        raise ValueError(f"{knob.label} must be a number.")
    if knob.minimum is not None and number < knob.minimum:
        raise ValueError(f"{knob.label} cannot be below {_plain(knob.minimum)}.")
    if knob.maximum is not None and number > knob.maximum:
        raise ValueError(f"{knob.label} cannot be above {_plain(knob.maximum)}.")
    return int(round(number)) if knob.integer else number


def _plain(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else str(number)


def _baseline() -> dict[str, Any]:
    """Where each knob started, captured before the first override is applied.

    The `Settings` field default, unless the environment overrode it at boot.
    """
    global _BASELINE
    if not _BASELINE:
        settings = get_settings()
        _BASELINE = {knob.key: getattr(settings, knob.key) for knob in KNOBS}
    return _BASELINE


def stored() -> dict[str, Any]:
    """The overrides in the database. Rows that no longer coerce are ignored."""
    with session_scope() as session:
        # Read the columns out inside the session: the commit on the way out
        # expires the instances, and touching one afterwards is a detached load.
        rows = [(row.key, row.value) for row in session.exec(select(SettingOverride))]

    values: dict[str, Any] = {}
    for key, raw in rows:
        knob = BY_KEY.get(key)
        if knob is None:
            continue
        try:
            values[key] = _coerce(knob, raw)
        except ValueError:
            # A knob whose bounds moved since the row was written. Falling back
            # to the default beats refusing to boot over a stale number.
            logger.warning("Ignoring unusable override %s=%r", key, raw)
    return values


def apply() -> dict[str, Any]:
    """Push the stored overrides onto the shared `Settings` instance.

    Called at startup and after every write. Keys with no override are reset to
    the baseline, so clearing one row is enough to undo it.
    """
    baseline = _baseline()
    settings = get_settings()
    overrides = stored()
    for knob in KNOBS:
        setattr(settings, knob.key, overrides.get(knob.key, baseline[knob.key]))
    if overrides:
        logger.info("Applied %d setting override(s): %s", len(overrides), sorted(overrides))
    return overrides


def save(values: Mapping[str, Any]) -> dict[str, Any]:
    """Store the given knobs and apply them. Returns the effective values.

    A value equal to the baseline deletes its row rather than storing a
    duplicate of it, so "overridden" keeps meaning "differs from the default"
    and a later change to that default is picked up again.
    """
    baseline = _baseline()

    cleaned: dict[str, Any] = {}
    for key, raw in values.items():
        knob = BY_KEY.get(key)
        if knob is None:
            raise ValueError(f"{key} is not an editable setting.")
        if raw is None:
            continue
        cleaned[key] = _coerce(knob, raw)

    if not cleaned:
        raise ValueError("Nothing to save.")

    with session_scope() as session:
        for key, value in cleaned.items():
            row = session.get(SettingOverride, key)
            if value == baseline[key]:
                if row is not None:
                    session.delete(row)
                continue
            if row is None:
                session.add(SettingOverride(key=key, value=str(value)))
            else:
                row.value = str(value)
                row.updated_at = utcnow()
                session.add(row)

    return apply()


def clear() -> dict[str, Any]:
    """Drop every override and go back to the defaults."""
    with session_scope() as session:
        session.exec(delete(SettingOverride))
    return apply()


def model_options() -> list[dict[str, Any]]:
    """Both providers in one list, each option saying which one it came from.

    Local models are `priced: True` in the sense the UI cares about — their runs
    cost nothing, so the $0 in the traces is the truth rather than a gap in the
    price table.
    """
    options: list[dict[str, Any]] = [
        {
            **option.as_dict(),
            "provider": "gemini",
            "local": False,
            "remote_host": "",
            "recommended_for": _recommended_for(option.id),
        }
        for option in gemini_models.available()
    ]
    options += [
        {
            "id": model.id,
            "label": model.name,
            "provider": "ollama",
            "local": model.on_this_machine,
            "remote_host": model.remote_host,
            "priced": model.on_this_machine,
            "input_price": 0.0 if model.on_this_machine else None,
            "output_price": 0.0 if model.on_this_machine else None,
            "recommended_for": _recommended_for(model.id),
        }
        for model in ollama_models.available()
    ]
    return options


def _recommended_for(model_id: str) -> list[str]:
    return [knob.key for knob in KNOBS if model_id in RECOMMENDED.get(knob.key, ())]


def state() -> dict[str, Any]:
    """Everything the Settings page needs to render and edit the form."""
    settings = get_settings()
    baseline = _baseline()
    overrides = stored()
    return {
        "fields": [
            {
                "key": knob.key,
                "label": knob.label,
                "help": knob.help,
                "kind": knob.kind,
                "min": knob.minimum,
                "max": knob.maximum,
                "step": knob.step,
                "providers": list(knob.providers),
                "value": getattr(settings, knob.key),
                "default": baseline[knob.key],
                "overridden": knob.key in overrides,
            }
            for knob in KNOBS
        ],
        # Asked of Google and of the local Ollama, not kept in this repo.
        "model_options": model_options(),
        "ollama": {
            "base_url": settings.ollama_base_url,
            "reachable": ollama_models.is_reachable(),
            "in_use": any(is_local(getattr(settings, knob.key)) for knob in KNOBS
                          if knob.kind == "model"),
        },
    }
