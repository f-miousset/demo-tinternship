"""The interview ends itself.

The Interrogator used to close by telling the candidate to click "Generate
search brief". It now ends that turn with `[[INTERVIEW_COMPLETE]]` instead, and
the app takes it from there: the marker becomes a `complete` event, the browser
writes the brief off the back of it and Strategy researches the playbook.

Two things have to hold for that to be an improvement rather than a leak. The
signal has to survive the shapes a model puts a literal in, and it must never
reach a chat bubble — live or on a reload, where the stored transcript still
carries it.
"""

from __future__ import annotations

from typing import Any

import pytest

from tinternship_backend.agents.interrogator import (
    COMPLETION_MARKER,
    split_completion,
)
from tinternship_backend.services import flows


class TestSplitCompletion:
    def test_the_marker_is_the_signal_and_never_the_prose(self):
        text, complete = split_completion(
            f"I have what I need. I am still unsure about your start date.\n\n{COMPLETION_MARKER}"
        )
        assert complete is True
        assert text == "I have what I need. I am still unsure about your start date."

    @pytest.mark.parametrize(
        "written",
        [
            "`[[INTERVIEW_COMPLETE]]`",
            "**[[INTERVIEW_COMPLETE]]**",
            "[[interview complete]]",
            "[[INTERVIEW-COMPLETE]]",
            "[[ INTERVIEW_COMPLETE ]]",
        ],
    )
    def test_the_shapes_a_model_puts_a_literal_in_all_count(self, written: str):
        text, complete = split_completion(f"Done.\n\n{written}")
        assert (text, complete) == ("Done.", True)

    def test_an_ordinary_turn_is_left_alone(self):
        text, complete = split_completion("Which cities are you open to, and from when?")
        assert complete is False
        assert text == "Which cities are you open to, and from when?"

    def test_a_turn_that_is_only_the_marker_leaves_no_empty_bubble(self):
        """`/history` and the chat both drop an assistant turn with no text."""
        assert split_completion(COMPLETION_MARKER) == ("", True)


@pytest.fixture
def fake_turn(monkeypatch: pytest.MonkeyPatch):
    """An interview turn whose text the test decides."""

    def turn(*texts: str, fail: str = ""):
        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 3, "session_id": "interview", "kind": "interrogator"})
            for text in texts:
                yield ("event", {"author": "interrogator", "text": text, "partial": False})
            if fail:
                yield ("error", {"run_id": 3, "error": fail})
                return
            yield ("state", {})
            yield ("done", {"run_id": 3, "text": "", "invocation_id": "inv-3"})

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows, "build_interrogator", lambda: None)

    return turn


async def events(message: str = "hello") -> list[tuple[str, Any]]:
    return [event async for event in flows.interview_stream(message)]


class TestInterviewStream:
    async def test_a_closing_turn_hands_off_after_the_candidate_has_read_it(self, fake_turn):
        fake_turn(f"That is everything I need. Writing the brief now.\n{COMPLETION_MARKER}")

        produced = await events()
        kinds = [kind for kind, _ in produced]
        texts = [data["text"] for kind, data in produced if kind == "event"]

        assert kinds[-1] == "complete"
        # The goodbye is on screen before the brief starts writing under it.
        assert kinds.index("done") < kinds.index("complete")
        assert texts == ["That is everything I need. Writing the brief now."]

    async def test_an_ordinary_turn_hands_off_nothing(self, fake_turn):
        fake_turn("Which cities, and from when?")

        assert [kind for kind, _ in await events()] == ["run", "event", "state", "done"]

    async def test_a_turn_that_fell_over_hands_off_nothing(self, fake_turn):
        """A brief written from a half-finished turn is worse than no brief."""
        fake_turn(f"I have what I need.\n{COMPLETION_MARKER}", fail="Gemini quota exceeded.")

        produced = await events()

        assert produced[-1] == ("error", {"run_id": 3, "error": "Gemini quota exceeded."})
        assert "complete" not in [kind for kind, _ in produced]

    async def test_the_handoff_is_announced_once_however_many_events_carry_it(self, fake_turn):
        fake_turn(f"I have what I need. {COMPLETION_MARKER}", f"One last thing. {COMPLETION_MARKER}")

        produced = await events()

        assert [kind for kind, _ in produced].count("complete") == 1
        assert all(COMPLETION_MARKER not in data.get("text", "") for _, data in produced)
