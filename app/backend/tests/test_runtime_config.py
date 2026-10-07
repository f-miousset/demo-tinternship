"""Settings the UI can change without a restart.

The point of the module is that an override reaches code that never asked for
one: every agent reads `settings.model_primary` off the single cached `Settings`
instance, so what is really being tested here is that saving mutates *that*
object, and that the `.env` baseline survives being shadowed so a reset can put
it back.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.config import get_settings
from tinternship_backend.services import runtime_config
from tinternship_backend.services.runtime_config import Knob


@pytest.fixture(autouse=True)
def restore_env_defaults():
    """Every test starts and ends on the `.env` values, whatever it stored."""
    runtime_config.clear()
    yield
    runtime_config.clear()


@pytest.fixture()
def client() -> TestClient:
    from tinternship_backend.main import app

    return TestClient(app)


def _off_default(knob: Knob, current: Any) -> Any:
    """A value this knob accepts that is *not* what it already holds.

    Equality with the baseline matters: `save()` deletes the row for a value
    equal to `.env`, so a knob that never reached the database would be
    indistinguishable from one saved correctly. Every value here differs from
    the current one, so a stored row is proof the write landed.
    """
    if knob.kind == "model":
        # Any Gemini id is legal for all three model knobs; a local one would be
        # refused on the grounded field.
        return "gemini-2.5-pro" if current != "gemini-2.5-pro" else "gemini-2.5-flash"
    # The declared bounds are themselves valid values, and one of the two ends
    # is always somewhere the knob is not.
    return knob.minimum if current != knob.minimum else knob.maximum


def test_saving_reaches_the_shared_settings_object():
    runtime_config.save({"model_primary": "gemini-2.5-pro"})

    # Not the returned dict — the instance every `build_*` factory reads.
    assert get_settings().model_primary == "gemini-2.5-pro"


def test_numbers_are_coerced_to_their_declared_type():
    runtime_config.save({"audit_pass_threshold": "8.5", "audit_max_revisions": "3"})

    settings = get_settings()
    assert settings.audit_pass_threshold == 8.5
    assert settings.audit_max_revisions == 3
    assert isinstance(settings.audit_max_revisions, int)


def test_clear_goes_back_to_the_env_baseline():
    baseline = get_settings().model_primary
    runtime_config.save({"model_primary": "gemini-2.5-flash"})
    assert get_settings().model_primary == "gemini-2.5-flash"

    runtime_config.clear()

    assert get_settings().model_primary == baseline


def test_saving_the_default_stores_nothing():
    """Otherwise a later edit to .env would be shadowed by a copy of itself."""
    baseline = get_settings().audit_max_revisions

    runtime_config.save({"audit_max_revisions": baseline})

    assert runtime_config.stored() == {}
    field = next(f for f in runtime_config.state()["fields"] if f["key"] == "audit_max_revisions")
    assert field["overridden"] is False


def test_untouched_keys_keep_their_value():
    runtime_config.save({"model_primary": "gemini-2.5-pro"})
    runtime_config.save({"model_fast": "gemini-2.5-flash-lite"})

    assert get_settings().model_primary == "gemini-2.5-pro"
    assert get_settings().model_fast == "gemini-2.5-flash-lite"


@pytest.mark.parametrize(
    "values",
    [
        {"audit_pass_threshold": 11},
        {"audit_pass_threshold": -1},
        {"audit_max_revisions": 0},
        {"audit_max_revisions": 99},
        {"audit_pass_threshold": "not a number"},
        {"model_primary": "   "},
        {"model_primary": "x" * 200},
        {"nonsense": "value"},
    ],
)
def test_bad_values_are_refused(values):
    with pytest.raises(ValueError):
        runtime_config.save(values)


def test_bad_values_leave_the_running_settings_alone():
    before = get_settings().audit_pass_threshold

    with pytest.raises(ValueError):
        runtime_config.save({"audit_pass_threshold": 42})

    assert get_settings().audit_pass_threshold == before


def test_apply_survives_a_row_that_no_longer_validates():
    """A knob's bounds can move after a row was written; .env is the fallback."""
    from tinternship_backend.db.engine import session_scope
    from tinternship_backend.db.models import SettingOverride

    baseline = get_settings().audit_max_revisions
    with session_scope() as session:
        session.add(SettingOverride(key="audit_max_revisions", value="4000"))

    runtime_config.apply()

    assert get_settings().audit_max_revisions == baseline


def test_state_describes_every_knob():
    state = runtime_config.state()

    assert [field["key"] for field in state["fields"]] == [
        "model_primary",
        "model_fast",
        "model_grounded",
        "audit_pass_threshold",
        "audit_max_revisions",
        "follow_up_after_days",
        "posting_half_life_days",
    ]
    threshold = next(f for f in state["fields"] if f["key"] == "audit_pass_threshold")
    assert (threshold["min"], threshold["max"]) == (0, 10)
    # No key in the test environment, so this is the priced-model fallback —
    # the point is that the picker is never handed an empty list.
    assert state["model_options"], "the model picker needs something to offer"
    assert all({"id", "label", "priced"} <= option.keys() for option in state["model_options"])


def test_every_knob_can_actually_be_saved_through_the_api(client: TestClient):
    """The API has to accept every knob the UI is told it may edit.

    `ConfigUpdate` lists its fields by hand and pydantic drops anything it does
    not declare, so a knob added to `KNOBS` without a matching field posts fine,
    answers 200, and is thrown away — the form looks saved and the value snaps
    back on the next render. `model_grounded` and `posting_half_life_days` were
    both in that state and only worked from `.env`.

    This is keyed off `KNOBS` rather than a written-out list so the next knob
    added without an API field fails here instead of silently not saving.
    """
    settings = get_settings()
    payload = {
        knob.key: _off_default(knob, getattr(settings, knob.key))
        for knob in runtime_config.KNOBS
    }

    response = client.put("/api/settings/config", json=payload)

    assert response.status_code == 200, response.text
    # `stored()` reads the rows back out of the database, so this fails for a
    # knob the request layer discarded, not merely one the response echoed.
    assert runtime_config.stored() == payload
    for key, value in payload.items():
        assert getattr(get_settings(), key) == value, f"{key} did not reach the settings"
    served = {field["key"]: field["value"] for field in response.json()["fields"]}
    assert served == payload
