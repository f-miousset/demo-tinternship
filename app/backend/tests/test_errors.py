"""Provider failures must reach the user as advice, not as a stack trace."""

from __future__ import annotations

import pytest

from tinternship_backend.api.errors import humanise


class QuotaError(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("error", "status", "must_mention"),
    [
        (
            QuotaError("429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"),
            429,
            "quota",
        ),
        (RuntimeError("400 INVALID_ARGUMENT: API key not valid"), 401, "GOOGLE_API_KEY"),
        (RuntimeError("403 PERMISSION_DENIED on model"), 403, "MODEL_PRIMARY"),
        (RuntimeError("Response was blocked due to SAFETY"), 422, "safety"),
        (RuntimeError("504 DEADLINE_EXCEEDED"), 504, "timed out"),
        (RuntimeError("404 NOT_FOUND: model gemini-9 does not exist"), 404, "MODEL_PRIMARY"),
    ],
)
def test_known_failures_map_to_actionable_messages(error, status, must_mention):
    code, message = humanise(error)
    assert code == status
    assert must_mention.lower() in message.lower()


def test_unknown_failures_fall_back_to_500_with_the_type_named():
    code, message = humanise(ValueError("something odd"))
    assert code == 500
    assert "ValueError" in message


def test_messages_never_leak_a_stack_trace():
    _, message = humanise(QuotaError("429 RESOURCE_EXHAUSTED\n  File \"x.py\", line 1\n    raise"))
    assert "File \"" not in message
    assert "Traceback" not in message
