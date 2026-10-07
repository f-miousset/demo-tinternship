import { beforeEach, describe, expect, it } from "vitest";

import {
  SEARCH_HISTORY_KEY,
  addSearchHistoryItem,
  clearSearchHistory,
  formatHistoryTime,
  readSearchHistory,
  removeSearchHistoryItem,
} from "./searchHistory";

describe("searchHistory", () => {
  const store = new Map<string, string>();
  const mockStorage: Storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  };

  beforeEach(() => {
    store.clear();
    Object.defineProperty(window, "localStorage", {
      value: mockStorage,
      writable: true,
      configurable: true,
    });
  });

  it("reads empty list when nothing is stored", () => {
    expect(readSearchHistory()).toEqual([]);
  });

  it("adds and persists a new history item", () => {
    const updated = addSearchHistoryItem("Mistral AI in Paris");
    expect(updated).toHaveLength(1);
    expect(updated[0].text).toBe("Mistral AI in Paris");

    const read = readSearchHistory();
    expect(read).toHaveLength(1);
    expect(read[0].text).toBe("Mistral AI in Paris");
  });

  it("ignores whitespace-only inputs", () => {
    const updated = addSearchHistoryItem("   ");
    expect(updated).toEqual([]);
    expect(readSearchHistory()).toEqual([]);
  });

  it("deduplicates identical queries and brings the newest to the top", () => {
    addSearchHistoryItem("First query");
    addSearchHistoryItem("Second query");
    const updated = addSearchHistoryItem("first query"); // case-insensitive deduplication

    expect(updated).toHaveLength(2);
    expect(updated[0].text).toBe("first query");
    expect(updated[1].text).toBe("Second query");
  });

  it("removes an individual item by id", () => {
    const items = addSearchHistoryItem("To keep");
    const withSecond = addSearchHistoryItem("To delete", items);
    const idToDelete = withSecond[0].id;

    const remaining = removeSearchHistoryItem(idToDelete, withSecond);
    expect(remaining).toHaveLength(1);
    expect(remaining[0].text).toBe("To keep");
  });

  it("clears all search history", () => {
    addSearchHistoryItem("Query 1");
    addSearchHistoryItem("Query 2");
    expect(readSearchHistory()).toHaveLength(2);

    clearSearchHistory();
    expect(readSearchHistory()).toHaveLength(0);
  });

  it("handles malformed JSON gracefully", () => {
    mockStorage.setItem(SEARCH_HISTORY_KEY, "{ broken json [");
    expect(readSearchHistory()).toEqual([]);
  });

  it("formats relative timestamps cleanly", () => {
    const now = 1700000000000;
    expect(formatHistoryTime(now - 10000, now)).toBe("Just now");
    expect(formatHistoryTime(now - 5 * 60000, now)).toBe("5m ago");
    expect(formatHistoryTime(now - 3 * 3600000, now)).toBe("3h ago");
    expect(formatHistoryTime(now - 25 * 3600000, now)).toBe("Yesterday");
    expect(formatHistoryTime(now - 3 * 86400000, now)).toBe("3d ago");
  });
});
