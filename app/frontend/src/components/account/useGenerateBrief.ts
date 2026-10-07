import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { AgentPrompt } from "../../lib/types";

/** What `POST /api/interview/finalise` answers with. */
export interface BriefResult {
  brief: Record<string, any>;
  prompt: AgentPrompt;
  /** The verdict as the run returns it — `{}` when the audit itself failed, so
   *  every field is optional. The stored form, with its criteria, comes back
   *  on the prompt itself from `/api/strategy/prompts`. */
  audit: { overall?: number; reasoning?: string } | null;
  run_id: number;
}

/**
 * The key both callers share.
 *
 * Writing the brief can start in two places — the Interrogator ending the
 * interview by itself, or the button on the brief side of Strategy — and they
 * are the same run reading the same session. Sharing a mutation key is how the
 * interview composer knows to lock while a brief is being written somewhere
 * else on the page: a turn sent mid-write would put a second agent in the
 * session the brief writer is reading.
 */
export const BRIEF_MUTATION_KEY = ["interview", "finalise"] as const;

export function useGenerateBrief() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: BRIEF_MUTATION_KEY,
    mutationFn: () => api.post<BriefResult>("/api/interview/finalise"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["interview", "history"] });
    },
  });
}

/** Whether a brief is being written anywhere on the page. */
export function useBriefWriting(): boolean {
  return useIsMutating({ mutationKey: BRIEF_MUTATION_KEY }) > 0;
}
