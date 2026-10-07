import type { ModelOption } from "./types";

/**
 * Format a human-readable price tag for an option in the model selector.
 * E.g. "$0.75 / $3.75 per 1M" or "free".
 */
export function formatModelPrice(model: ModelOption): string | null {
  if (model.provider === "ollama") {
    return model.local ? "free" : null;
  }
  if (model.input_price === 0 && model.output_price === 0) {
    return "free";
  }
  if (model.input_price != null && model.output_price != null) {
    const fmt = (n: number) => {
      const s2 = n.toFixed(2);
      return parseFloat(s2) === n ? `$${s2}` : `$${n}`;
    };
    return `${fmt(model.input_price)} / ${fmt(model.output_price)} per 1M`;
  }
  return null;
}
