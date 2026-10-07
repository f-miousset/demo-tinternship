"""Rough token-cost estimation, so the traces UI can show what a run cost.

Prices are USD per 1M tokens, from ai.google.dev pricing as of August 2026.
They are deliberately kept in one small table: if Google moves prices, this is
the only thing to edit, and an unknown model degrades to zero rather than
guessing wildly.
"""

from __future__ import annotations

# model prefix -> (input $/1M, output $/1M)
_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro": (2.00, 12.00),
    "gemini-3-flash": (0.50, 3.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-flash-latest": (0.30, 2.50),
    "gemini-flash-lite-latest": (0.10, 0.40),
    "gemini-pro-latest": (1.25, 10.00),
    "gemma-4": (0.0, 0.0),
}


def get_model_price(model: str) -> tuple[float, float] | None:
    """Return (input $/1M, output $/1M) for a model, or None if unknown."""
    if not model:
        return None
    normalised = model.split("/")[-1].removeprefix("models/")

    # 1. Pull dynamically from litellm model cost map
    try:
        import litellm

        for candidate in (normalised, f"gemini/{normalised}", f"vertex_ai/{normalised}"):
            if candidate in litellm.model_cost:
                entry = litellm.model_cost[candidate]
                in_cost = entry.get("input_cost_per_token")
                out_cost = entry.get("output_cost_per_token")
                if in_cost is not None and out_cost is not None:
                    return (round(in_cost * 1_000_000, 4), round(out_cost * 1_000_000, 4))
    except Exception:
        pass

    # 2. Fall back to curated prefix table
    match = max(
        (prefix for prefix in _PRICES if normalised.startswith(prefix)),
        key=len,
        default=None,
    )
    if match is not None:
        return _PRICES[match]
    return None


def priced_models() -> list[str]:
    """The models this table knows a price for.

    Doubles as the suggestion list on the Settings page: picking one of these
    keeps the cost column in the traces meaningful, and picking anything else
    still works but reads $0.
    """
    return sorted(_PRICES)


def estimate_cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    """Best-effort cost for one model call. Returns 0.0 for unknown models."""
    price = get_model_price(model)
    if price is None:
        return 0.0
    price_in, price_out = price
    return (prompt_tokens * price_in + output_tokens * price_out) / 1_000_000


def is_priced(model: str) -> bool:
    return get_model_price(model) is not None
