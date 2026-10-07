import { describe, expect, it } from "vitest";

import { formatModelPrice } from "./models";
import type { ModelOption } from "./types";

describe("formatModelPrice", () => {
  it("formats standard priced Gemini models", () => {
    const model: ModelOption = {
      id: "gemini-3.8-flash",
      label: "Gemini 3.8 Flash",
      provider: "gemini",
      local: false,
      remote_host: "",
      priced: true,
      input_price: 0.75,
      output_price: 3.75,
      recommended_for: ["model_primary"],
    };
    expect(formatModelPrice(model)).toBe("$0.75 / $3.75 per 1M");
  });

  it("formats models with differing decimals", () => {
    const model: ModelOption = {
      id: "gemini-2.5-pro",
      label: "Gemini 2.5 Pro",
      provider: "gemini",
      local: false,
      remote_host: "",
      priced: true,
      input_price: 1.25,
      output_price: 10.0,
      recommended_for: [],
    };
    expect(formatModelPrice(model)).toBe("$1.25 / $10.00 per 1M");
  });

  it("formats zero-cost models as free", () => {
    const model: ModelOption = {
      id: "gemma-4-26b-a4b-it",
      label: "Gemma 4 26B A4B IT",
      provider: "gemini",
      local: false,
      remote_host: "",
      priced: true,
      input_price: 0,
      output_price: 0,
      recommended_for: [],
    };
    expect(formatModelPrice(model)).toBe("free");
  });

  it("formats local Ollama models as free", () => {
    const model: ModelOption = {
      id: "ollama/gemma3:4b",
      label: "gemma3:4b",
      provider: "ollama",
      local: true,
      remote_host: "",
      priced: true,
      input_price: 0,
      output_price: 0,
      recommended_for: ["model_fast"],
    };
    expect(formatModelPrice(model)).toBe("free");
  });

  it("returns null for cloud Ollama models", () => {
    const model: ModelOption = {
      id: "ollama/qwen3.5:397b-cloud",
      label: "qwen3.5:397b-cloud",
      provider: "ollama",
      local: false,
      remote_host: "ollama.com",
      priced: false,
      input_price: null,
      output_price: null,
      recommended_for: [],
    };
    expect(formatModelPrice(model)).toBeNull();
  });

  it("returns null for unpriced Gemini models", () => {
    const model: ModelOption = {
      id: "gemini-unknown",
      label: "Unknown",
      provider: "gemini",
      local: false,
      remote_host: "",
      priced: false,
      input_price: null,
      output_price: null,
      recommended_for: [],
    };
    expect(formatModelPrice(model)).toBeNull();
  });
});
