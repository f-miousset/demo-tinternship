"""The priority platforms the Scout searches first.

These are prompt-shaped, so the tests pin the contract the prompts rely on:
the configured order, that a `.env` typo degrades to a skip rather than a
crash, and that every query pattern actually targets its own platform.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from tinternship_backend.config import get_settings
from tinternship_backend.services import job_links
from tinternship_backend.services.context_blocks import (
    platform_block,
    platform_domains_block,
)
from tinternship_backend.tools.job_sources import platforms as platforms_module
from tinternship_backend.tools.job_sources.platforms import (
    PLATFORMS,
    platform_labels,
    priority_domains,
    priority_platforms,
)

PLACEHOLDER = re.compile(r"\{([^}]+)\}")

# What the Query Planner is asked to fill in. A pattern using anything else is
# a typo the planner cannot resolve from the brief.
KNOWN_PLACEHOLDERS = {
    "role",
    "role synonym",
    "domain keyword",
    "domain term 1",
    "domain term 2",
    "domain term 3",
    "location",
    "season",
}


@pytest.fixture
def set_platforms(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Override PRIORITY_JOB_PLATFORMS on the cached settings for one test."""

    def _set(value: str) -> None:
        monkeypatch.setattr(get_settings(), "priority_job_platforms", value)

    return _set


def test_default_is_the_three_platforms_in_order() -> None:
    assert [p.key for p in priority_platforms()] == [
        "welcome_to_the_jungle",
        "linkedin",
        "station_f",
    ]


def test_order_follows_the_setting(set_platforms: Callable[[str], None]) -> None:
    set_platforms("station_f, linkedin")
    assert [p.key for p in priority_platforms()] == ["station_f", "linkedin"]


def test_unknown_key_is_skipped_not_raised(
    set_platforms: Callable[[str], None], caplog: pytest.LogCaptureFixture
) -> None:
    set_platforms("linkedin,indeed")
    with caplog.at_level("WARNING", logger=platforms_module.__name__):
        assert [p.key for p in priority_platforms()] == ["linkedin"]
    assert "indeed" in caplog.text


def test_duplicates_collapse(set_platforms: Callable[[str], None]) -> None:
    set_platforms("linkedin,linkedin")
    assert [p.key for p in priority_platforms()] == ["linkedin"]


def test_empty_setting_disables_the_priority_pass(
    set_platforms: Callable[[str], None],
) -> None:
    set_platforms("")
    assert priority_platforms() == []
    assert priority_domains() == []
    assert platform_labels() == []
    # Both blocks must vanish, because `compose` drops empty blocks and the
    # instructions that reference them are phrased conditionally.
    assert platform_block() == ""
    assert platform_domains_block() == ""


def test_every_query_pattern_targets_its_own_platform() -> None:
    for platform in PLATFORMS.values():
        for pattern in platform.query_patterns:
            assert pattern.startswith("site:"), (platform.key, pattern)
            assert any(domain in pattern for domain in platform.domains), (
                platform.key,
                pattern,
            )


def test_query_patterns_only_use_placeholders_the_planner_can_fill() -> None:
    for platform in PLATFORMS.values():
        for pattern in platform.query_patterns:
            unknown = set(PLACEHOLDER.findall(pattern)) - KNOWN_PLACEHOLDERS
            assert not unknown, (platform.key, pattern, unknown)


def test_block_carries_what_the_scout_needs() -> None:
    block = platform_block()
    for platform in priority_platforms():
        assert platform.label in block
        assert platform.url_shape in block
        assert platform.region_note in block
        for pattern in platform.query_patterns:
            assert pattern in block
        for caveat in platform.caveats:
            assert caveat in block


def test_domains_block_lists_every_priority_domain() -> None:
    block = platform_domains_block()
    for domain in priority_domains():
        assert domain in block


def _example_url(url_shape: str) -> str:
    """The URL a platform's prose `url_shape` describes, with the blanks filled."""

    def fill(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        if "|" in placeholder:  # `<fr|en>` — either works, take the first
            return placeholder.split("|")[0]
        return "1234567890" if "id" in placeholder else "example-slug"

    return "https://" + re.sub(r"<([^>]+)>", fill, url_shape)


class TestUrlShapeIsEnforced:
    """The prose in the prompt and the regex in the gate must say one thing.

    `url_shape` goes to the Scout, `posting_path` to `services/job_links.py`,
    which drops a URL on that domain that does not match. Drift between them
    means the app deletes exactly the URLs it asked for.
    """

    def test_every_platform_accepts_the_url_shape_it_advertises(self) -> None:
        for platform in PLATFORMS.values():
            url = _example_url(platform.url_shape)
            assert job_links.is_openable(url), (platform.key, url)

    @pytest.mark.parametrize(
        "url",
        [
            # Each of these is called out as "not a posting" in a platform's own
            # caveats. The caveat is advice; this is the rule.
            "https://www.welcometothejungle.com/fr/companies/agoranov",
            "https://www.linkedin.com/jobs/search?keywords=stage",
            "https://www.linkedin.com/jobs/collections/recommended",
            "https://jobs.stationf.co/startups",
            "https://jobs.stationf.co/search",
        ],
    )
    def test_the_pages_the_caveats_warn_about_are_rejected(self, url: str) -> None:
        assert not job_links.is_openable(url)
