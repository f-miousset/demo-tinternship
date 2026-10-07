import { useCallback, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";

export type SearchHistoryItem = {
  id: string;
  text: string;
  timestamp: number;
};

export const SEARCH_HISTORY_KEY = "tinternship.search-history";
const MAX_HISTORY_ITEMS = 50;

function getStorage(): Storage | null {
  try {
    if (typeof window !== "undefined" && "localStorage" in window && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // SecurityError in private browsing or disabled storage
  }
  return null;
}

/**
 * Read stored sent messages from localStorage.
 *
 * Silently returns an empty list if localStorage is unavailable (e.g. private
 * browsing) or holds malformed JSON.
 */
export function readSearchHistory(): SearchHistoryItem[] {
  const storage = getStorage();
  if (!storage) return [];
  try {
    const raw = storage.getItem(SEARCH_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is SearchHistoryItem =>
        Boolean(
          item &&
            typeof item === "object" &&
            typeof item.id === "string" &&
            typeof item.text === "string" &&
            item.text.trim() &&
            typeof item.timestamp === "number",
        ),
    );
  } catch {
    return [];
  }
}

/**
 * Save sent messages to localStorage.
 */
export function saveSearchHistory(items: SearchHistoryItem[]): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(items));
  } catch {
    // Storage quota exceeded or private browsing restrictions
  }
}

/**
 * Add a sent message to history, moving it to the top if already present.
 */
export function addSearchHistoryItem(
  text: string,
  current: SearchHistoryItem[] = readSearchHistory(),
): SearchHistoryItem[] {
  const trimmed = text.trim();
  if (!trimmed) return current;

  // Move duplicates to the top with an updated timestamp
  const filtered = current.filter(
    (item) => item.text.trim().toLowerCase() !== trimmed.toLowerCase(),
  );

  const newItem: SearchHistoryItem = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    text: trimmed,
    timestamp: Date.now(),
  };

  const updated = [newItem, ...filtered].slice(0, MAX_HISTORY_ITEMS);
  saveSearchHistory(updated);
  return updated;
}

/**
 * Remove a specific item from search history.
 */
export function removeSearchHistoryItem(
  id: string,
  current: SearchHistoryItem[] = readSearchHistory(),
): SearchHistoryItem[] {
  const updated = current.filter((item) => item.id !== id);
  saveSearchHistory(updated);
  return updated;
}

/**
 * Clear all search history.
 */
export function clearSearchHistory(): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.removeItem(SEARCH_HISTORY_KEY);
  } catch {
    // Ignore storage errors
  }
}

/**
 * Formats a timestamp into a compact, human-readable relative time label.
 *
 * Stays short enough to never wrap awkwardly on a 375px phone screen.
 */
export function formatHistoryTime(timestamp: number, now = Date.now()): string {
  const elapsed = Math.max(0, now - timestamp);
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/**
 * React hook to read, add, remove, and clear search message history.
 *
 * Search history is account-based, persisted in the backend database so that
 * queries are synchronized across devices (computer, mobile PWA). Local storage
 * serves as initial data and cache.
 */
export function useSearchHistory() {
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["search-history"],
    queryFn: async () => {
      try {
        const res = await api.get<{ items: SearchHistoryItem[] }>("/api/jobs/search/history");
        const items = res?.items ?? [];
        saveSearchHistory(items);
        return items;
      } catch {
        return readSearchHistory();
      }
    },
    initialData: () => readSearchHistory(),
  });

  // Migrate any legacy local storage queries to the account database once on mount
  useEffect(() => {
    const local = readSearchHistory();
    if (local.length > 0) {
      api
        .post<{ items: SearchHistoryItem[] }>("/api/jobs/search/history/sync", {
          items: local.map((item) => ({ text: item.text, timestamp: item.timestamp })),
        })
        .then((res) => {
          if (res?.items) {
            clearSearchHistory();
            queryClient.setQueryData(["search-history"], res.items);
          }
        })
        .catch(() => {
          // Keep local cache on network failure
        });
    }
  }, [queryClient]);

  const add = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      const current =
        queryClient.getQueryData<SearchHistoryItem[]>(["search-history"]) ?? readSearchHistory();
      const updated = addSearchHistoryItem(trimmed, current);
      queryClient.setQueryData(["search-history"], updated);
      saveSearchHistory(updated);

      api
        .post<SearchHistoryItem>("/api/jobs/search/history", { text: trimmed })
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["search-history"] });
        })
        .catch(() => {
          // Keep optimistic/local update
        });
    },
    [queryClient],
  );

  const remove = useCallback(
    (id: string) => {
      const current =
        queryClient.getQueryData<SearchHistoryItem[]>(["search-history"]) ?? readSearchHistory();
      const updated = removeSearchHistoryItem(id, current);
      queryClient.setQueryData(["search-history"], updated);
      saveSearchHistory(updated);

      api
        .del(`/api/jobs/search/history/${id}`)
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["search-history"] });
        })
        .catch(() => {
          // Keep optimistic/local update
        });
    },
    [queryClient],
  );

  const clear = useCallback(() => {
    queryClient.setQueryData(["search-history"], []);
    clearSearchHistory();

    api
      .del("/api/jobs/search/history")
      .then(() => {
        queryClient.invalidateQueries({ queryKey: ["search-history"] });
      })
      .catch(() => {
        // Keep optimistic/local update
      });
  }, [queryClient]);

  return { history: data ?? [], add, remove, clear };
}
