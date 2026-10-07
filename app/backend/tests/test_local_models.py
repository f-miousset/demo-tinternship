"""Running the agents on a local Ollama instead of the Gemini API.

The interesting part is not that a model id can be resolved — it is the line
grounding cannot cross. Google Search is a Gemini server-side feature, and ADK
raises `ValueError: Google search tool is not supported for model ollama_chat/…`
when it is attached to anything else. That failure happens deep inside a run,
so the tests here are about catching it long before: at save time for the knob
that must stay Gemini, and at build time for the two agents that carry the tool.
"""

from __future__ import annotations

import httpx
import pytest

from tinternship_backend.agents import models as model_resolver
from tinternship_backend.config import get_settings
from tinternship_backend.services import gemini_models, ollama_models, runtime_config


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    # The Gemini half of the picker is `test_gemini_models.py`'s subject, and
    # letting it reach for the network here would make these slow and flaky.
    monkeypatch.setattr(
        gemini_models,
        "available",
        lambda **_: [gemini_models.ModelOption("gemini-3.6-flash", "Gemini 3.6 Flash", True)],
    )
    runtime_config.clear()
    ollama_models.invalidate()
    yield
    runtime_config.clear()
    ollama_models.invalidate()


def fake_tags(payload: dict):
    """A stand-in for `httpx.get`. The request has to be set for raise_for_status."""

    def get(url: str, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    return get


# --- resolution ------------------------------------------------------------


def test_a_gemini_id_becomes_a_gemini_model_that_retries():
    """Vertex answers a busy shared pool with 429; ADK's default is not to retry."""
    from google.adk.models.google_llm import Gemini

    resolved = model_resolver.resolve("gemini-3.6-flash")

    assert isinstance(resolved, Gemini)
    assert resolved.model == "gemini-3.6-flash"
    assert resolved.retry_options is not None
    assert resolved.retry_options.attempts and resolved.retry_options.attempts > 1


def test_a_local_id_becomes_a_litellm_model():
    resolved = model_resolver.resolve("ollama/qwen3.5:9b")

    assert not isinstance(resolved, str)
    # LiteLLM's `ollama_chat` endpoint, not `ollama` — the former does tools.
    assert resolved.model == "ollama_chat/qwen3.5:9b"


def test_the_local_model_points_at_the_configured_ollama(monkeypatch):
    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://host.docker.internal:11434")

    resolved = model_resolver.resolve("ollama/mistral:7b")

    # LiteLlm keeps anything it does not model itself in `_additional_args`.
    assert resolved._additional_args["api_base"] == "http://host.docker.internal:11434"


def test_thinking_is_turned_off():
    """A thinking model reasons in prose until the output budget is gone.

    For the agents that declare an `output_schema` that prose *is* the response,
    so the run produces no JSON and the audit records a flat 0 — observed on
    qwen3.5:9b against the Critic's rubric before this was set.
    """
    resolved = model_resolver.resolve("ollama/qwen3.5:9b")

    assert resolved._additional_args["think"] is False


def test_the_local_model_gets_a_patient_timeout():
    """A 12B model on a laptop is not a hosted API."""
    resolved = model_resolver.resolve("ollama/gemma4:12b-mlx")

    assert resolved._additional_args["timeout"] == get_settings().ollama_timeout_seconds


def test_is_local_only_matches_the_prefix():
    assert model_resolver.is_local("ollama/gemma3:4b")
    assert not model_resolver.is_local("gemini-3.6-flash")
    # A Gemini model whose name merely contains the word.
    assert not model_resolver.is_local("gemma-4-31b-it")


# --- the grounding line ----------------------------------------------------


def test_the_search_model_refuses_a_local_model():
    with pytest.raises(ValueError, match="Gemini"):
        runtime_config.save({"model_grounded": "ollama/qwen3.5:9b"})


def test_the_other_two_accept_one():
    runtime_config.save({"model_primary": "ollama/qwen3.5:9b", "model_fast": "ollama/gemma3:4b"})

    settings = get_settings()
    assert settings.model_primary == "ollama/qwen3.5:9b"
    assert settings.model_fast == "ollama/gemma3:4b"


def test_the_grounded_agents_stay_on_gemini_when_everything_else_is_local():
    """The whole point: going local must not cost you job discovery."""
    from tinternship_backend.agents.hr_expert import build_hr_researcher
    from tinternship_backend.agents.investigator import build_scout

    runtime_config.save({"model_primary": "ollama/qwen3.5:9b"})

    for agent in (build_scout(10), build_hr_researcher()):
        assert agent.model.model.startswith("gemini"), f"{agent.name} must keep a Gemini model"


def test_a_local_search_model_slipped_past_the_api_is_corrected(monkeypatch):
    """Editing .env directly bypasses the save-time check; the run must not."""
    monkeypatch.setattr(get_settings(), "model_grounded", "ollama/qwen3.5:9b")

    assert model_resolver.grounded() == "gemini-3.6-flash"


def test_the_ungrounded_agents_do_go_local():
    from tinternship_backend.agents.investigator import build_matcher

    runtime_config.save({"model_primary": "ollama/qwen3.5:9b"})

    assert build_matcher(10).model.model == "ollama_chat/qwen3.5:9b"


# --- listing ---------------------------------------------------------------


def test_embedding_models_are_not_offered(monkeypatch):
    monkeypatch.setattr(
        ollama_models.httpx,
        "get",
        fake_tags(
            {
                "models": [
                    {"name": "qwen3.5:9b", "capabilities": ["completion", "tools"]},
                    {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
                ]
            }
        ),
    )

    assert [model.id for model in ollama_models.available(refresh=True)] == ["ollama/qwen3.5:9b"]


def test_a_model_without_tool_support_is_still_offered(monkeypatch):
    """Only the grounded agents carry tools, and Ollama enforces schemas itself."""
    monkeypatch.setattr(
        ollama_models.httpx,
        "get",
        fake_tags({"models": [{"name": "gemma3:4b", "capabilities": ["completion"]}]}),
    )

    assert [model.id for model in ollama_models.available(refresh=True)] == ["ollama/gemma3:4b"]


def test_no_ollama_is_not_an_error(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ollama_models.httpx, "get", refuse)

    assert ollama_models.available(refresh=True) == []
    assert ollama_models.is_reachable() is False
    # And the picker still has its Gemini half.
    assert runtime_config.state()["model_options"]


def test_a_cloud_model_is_not_called_local(monkeypatch):
    """Ollama lists its `…-cloud` models like any other, but they run remotely.

    The UI promises "nothing leaves this machine" about a local model, so that
    promise must not attach to one Ollama is only proxying.
    """
    monkeypatch.setattr(
        ollama_models.httpx,
        "get",
        fake_tags(
            {
                "models": [
                    {"name": "qwen3.5:9b", "capabilities": ["completion"]},
                    {
                        "name": "qwen3.5:397b-cloud",
                        "capabilities": ["completion"],
                        "remote_host": "https://ollama.com:443",
                    },
                ]
            }
        ),
    )
    ollama_models.invalidate()

    options = {option["id"]: option for option in runtime_config.model_options()}

    assert options["ollama/qwen3.5:9b"]["local"] is True
    assert options["ollama/qwen3.5:397b-cloud"]["local"] is False
    assert options["ollama/qwen3.5:397b-cloud"]["remote_host"] == "ollama.com"


def test_recommendations_are_per_field():
    """A good Critic model is not automatically a good writing model."""
    options = {option["id"]: option for option in runtime_config.model_options()}
    starred = {
        key: {model for model, option in options.items() if key in option["recommended_for"]}
        for key in ("model_primary", "model_fast")
    }

    assert starred["model_primary"] != starred["model_fast"]


def test_every_recommendation_names_a_real_knob():
    assert set(runtime_config.RECOMMENDED) <= set(runtime_config.BY_KEY)


def test_the_search_model_is_never_recommended_a_local_model():
    for model_id in runtime_config.RECOMMENDED["model_grounded"]:
        assert not model_resolver.is_local(model_id)


def test_local_options_are_marked_free(monkeypatch):
    monkeypatch.setattr(
        ollama_models.httpx,
        "get",
        fake_tags({"models": [{"name": "qwen3.5:9b", "capabilities": ["completion"]}]}),
    )
    ollama_models.invalidate()

    local = [option for option in runtime_config.model_options() if option["local"]]

    assert local, "the local model should be offered"
    # $0 in the traces is the truth for a local model, not a missing price.
    assert all(option["priced"] for option in local)
    assert all(option["provider"] == "ollama" for option in local)


def test_the_search_knob_advertises_gemini_only():
    fields = {field["key"]: field for field in runtime_config.state()["fields"]}

    assert fields["model_grounded"]["providers"] == ["gemini"]
    assert fields["model_primary"]["providers"] == ["gemini", "ollama"]
