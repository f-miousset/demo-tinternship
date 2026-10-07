"""Listing the models the key can run.

The Settings page asks Google what is available rather than showing a list this
repo maintains. What needs testing is the filtering and the failure paths: the
API answers with speech, image, music and robotics models that all advertise
`generateContent` and none of which can write a résumé, and the page still has
to render when the listing call fails.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tinternship_backend.config import get_settings
from tinternship_backend.services import gemini_models


@dataclass
class FakeModel:
    name: str
    display_name: str = ""
    supported_actions: list[str] | None = None


LISTING = [
    FakeModel("models/gemini-3.6-flash", "Gemini 3.6 Flash", ["generateContent"]),
    FakeModel("models/gemini-2.5-pro", "Gemini 2.5 Pro", ["generateContent"]),
    FakeModel("models/gemini-9-unreleased", "Gemini 9", ["generateContent"]),
    FakeModel("models/gemini-2.5-flash-preview-tts", "TTS", ["generateContent"]),
    FakeModel("models/gemini-3-pro-image", "Nano Banana Pro", ["generateContent"]),
    FakeModel("models/lyria-3-pro-preview", "Lyria 3", ["generateContent"]),
    FakeModel("models/gemini-robotics-er-2-preview", "Robotics", ["generateContent"]),
    FakeModel("models/deep-research-preview-04-2026", "Deep Research", ["generateContent"]),
    FakeModel("models/gemini-embedding-001", "Embedding", ["embedContent"]),
]


@pytest.fixture(autouse=True)
def fresh_cache():
    gemini_models.invalidate()
    yield
    gemini_models.invalidate()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_api_key", "test-key")


@pytest.fixture
def listing(monkeypatch, with_key):
    calls: list[int] = []

    def fake_fetch():
        calls.append(1)
        return [
            gemini_models.ModelOption(
                id=model.name.removeprefix("models/"),
                label=model.display_name,
                priced=False,
            )
            for model in LISTING
            if gemini_models._is_usable(
                model.name.removeprefix("models/"), list(model.supported_actions or [])
            )
        ]

    monkeypatch.setattr(gemini_models, "_fetch", fake_fetch)
    return calls


def usable(models: list[FakeModel]) -> list[str]:
    return [
        model.name.removeprefix("models/")
        for model in models
        if gemini_models._is_usable(
            model.name.removeprefix("models/"), list(model.supported_actions or [])
        )
    ]


def test_only_text_models_are_offered():
    assert usable(LISTING) == ["gemini-3.6-flash", "gemini-2.5-pro", "gemini-9-unreleased"]


def test_a_model_this_repo_has_never_heard_of_is_offered():
    """The filter is a denylist on purpose — a new Gemini must not need a release."""
    assert "gemini-9-unreleased" in usable(LISTING)


def test_without_a_key_it_falls_back_to_the_priced_models(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_api_key", "")

    options = gemini_models.available()

    assert options, "the picker must never be handed an empty list"
    assert all(option.priced for option in options)


def test_a_failed_listing_still_returns_something(monkeypatch, with_key):
    def boom():
        raise RuntimeError("network is down")

    monkeypatch.setattr(gemini_models, "_fetch", boom)

    assert gemini_models.available(), "a failed listing must not empty the picker"


def test_a_failed_listing_keeps_the_last_good_one(monkeypatch, listing):
    good = gemini_models.available()

    def boom():
        raise RuntimeError("network is down")

    monkeypatch.setattr(gemini_models, "_fetch", boom)

    assert gemini_models.available(refresh=True) == good


def test_the_listing_is_cached(listing):
    gemini_models.available()
    gemini_models.available()

    assert len(listing) == 1, "one page view should not mean two API calls"
    assert len(gemini_models.available(refresh=True)) == 3
    assert len(listing) == 2


def test_pricing_is_pulled_for_models():
    from tinternship_backend.observability.pricing import get_model_price

    price_38 = get_model_price("gemini-3.8-flash")
    assert price_38 is not None
    assert price_38 == (0.75, 3.75)

    price_37 = get_model_price("gemini-3.7-flash")
    assert price_37 is not None
    assert price_37 == (0.75, 3.75)

    price_25_pro = get_model_price("gemini-2.5-pro")
    assert price_25_pro is not None
    assert price_25_pro == (1.25, 10.0)

    price_gemma = get_model_price("gemma-4-26b-a4b-it")
    assert price_gemma is not None
    assert price_gemma == (0.0, 0.0)


def test_fallback_models_include_price_fields(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_api_key", "")
    options = gemini_models.available()
    assert options
    for opt in options:
        assert opt.priced is True
        assert opt.input_price is not None
        assert opt.output_price is not None
        data = opt.as_dict()
        assert "input_price" in data
        assert "output_price" in data



def test_on_vertex_it_offers_the_priced_models_without_asking(monkeypatch, with_key):
    """Vertex's catalogue refuses API keys; calling it would only fail every 10 minutes."""
    monkeypatch.setattr(get_settings(), "google_genai_use_vertexai", "TRUE")

    def must_not_call():
        raise AssertionError("the listing was called on Vertex")

    monkeypatch.setattr(gemini_models, "_fetch", must_not_call)

    options = gemini_models.available()

    assert options
    assert all(option.priced for option in options)
