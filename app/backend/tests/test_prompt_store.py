"""Prompt versioning: edits must never destroy the version that a trace refers to."""

from __future__ import annotations

from tinternship_backend.db.models import PromptKind
from tinternship_backend.services import prompt_store


def test_each_save_creates_a_new_version_and_deactivates_the_old():
    first = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="v1 text", author="agent")
    second = prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="v2 text", author="user")

    assert (first.version, second.version) == (1, 2)
    assert prompt_store.get_active(PromptKind.SEARCH_BRIEF).content == "v2 text"

    versions = prompt_store.list_versions(PromptKind.SEARCH_BRIEF)
    assert len(versions) == 2
    assert sum(1 for version in versions if version.is_active) == 1


def test_rolling_back_reactivates_an_earlier_version():
    first = prompt_store.save_prompt(PromptKind.PLAYBOOK, content="original")
    prompt_store.save_prompt(PromptKind.PLAYBOOK, content="regrettable edit")

    restored = prompt_store.activate(first.id)
    assert restored.content == "original"
    assert prompt_store.get_active(PromptKind.PLAYBOOK).content == "original"
    # Rolling back must not delete the version we rolled away from.
    assert len(prompt_store.list_versions(PromptKind.PLAYBOOK)) == 2


def test_kinds_are_versioned_independently():
    prompt_store.save_prompt(PromptKind.SEARCH_BRIEF, content="brief")
    playbook = prompt_store.save_prompt(PromptKind.PLAYBOOK, content="playbook")
    assert playbook.version == 1


def test_search_brief_renders_only_populated_fields():
    rendered = prompt_store.render_search_brief(
        {
            "headline": "Summer 2027 ML internship in Paris",
            "role_titles": ["ML Engineer Intern", "Stagiaire ML"],
            "locations": ["Paris"],
            "must_haves": [],
            "domain": "",
        }
    )
    assert "Summer 2027 ML internship in Paris" in rendered
    assert "Stagiaire ML" in rendered
    assert "Must have" not in rendered
    assert "Domain" not in rendered


def test_playbook_renders_sources_with_urls():
    rendered = prompt_store.render_playbook(
        {
            "summary": "Apply early.",
            "where_to_search": ["Welcome to the Jungle"],
            "sources": [
                {"title": "WTTJ guide", "url": "https://example.com/a", "takeaway": "Apply in Oct"}
            ],
        }
    )
    assert "Welcome to the Jungle" in rendered
    assert "https://example.com/a" in rendered
    assert "Apply in Oct" in rendered
