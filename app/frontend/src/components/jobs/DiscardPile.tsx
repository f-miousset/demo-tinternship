import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DeleteForever } from "../DeleteForever";
import { Button, EmptyState, ScoreBadge, Spinner } from "../ui";
import { api } from "../../lib/api";
import { oneLiner } from "./oneLiner";
import type { Job } from "../../lib/types";

/**
 * The trash.
 *
 * Swiping left is a verdict, not a deletion: nothing is destroyed, the row keeps
 * its score and its link check, and one tap puts it back in the deck. That is
 * the whole reason discarding is safe enough to do quickly — which is what a
 * deck asks you to do.
 *
 * What it is *not* is a way back for the agents: a discarded posting stays
 * excluded from every run whether or not it is sitting here. Only the candidate
 * restores it.
 *
 * **Delete forever** is the step past discarding, one posting at a time or the
 * whole pile. It erases the posting but leaves a hidden tombstone, so a deleted
 * posting is still excluded from every run — see `services/trash.py`.
 */
export function DiscardPile() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["jobs", "discarded"],
    queryFn: () => api.get<{ jobs: Job[] }>("/api/jobs?view=discarded"),
  });

  const restore = useMutation({
    mutationFn: (id: number) => api.post(`/api/jobs/${id}/dismiss?dismissed=false`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const purge = useMutation({
    mutationFn: (id: number | "all") =>
      api.del(id === "all" ? "/api/jobs/trash" : `/api/jobs/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const jobs = data?.jobs ?? [];
  const busy = restore.isPending || purge.isPending;

  if (isLoading) return <Spinner label="Loading the trash…" />;
  if (jobs.length === 0) {
    return (
      <EmptyState
        title="Nothing discarded yet"
        hint="Postings you swipe left land here. Nothing is deleted unless you delete it — you can put any of them back."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <DeleteForever
          label={`Empty the trash (${jobs.length})`}
          armedLabel={`Tap again to delete all ${jobs.length}`}
          onConfirm={() => purge.mutate("all")}
          disabled={busy}
        />
      </div>
      <ul className="space-y-2">
        {jobs.map((job) => (
          <li
            key={job.id}
            className="squircle rounded-card border border-ink-200 p-3 dark:border-ink-800"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-semibold">{job.company}</p>
                <p className="truncate text-sm text-ink-600 dark:text-ink-300">{job.title}</p>
              </div>
              <ScoreBadge score={job.fit_score} />
            </div>
            {oneLiner(job) && (
              <p className="mt-1 line-clamp-2 text-xs text-ink-500 dark:text-ink-400">
                {oneLiner(job)}
              </p>
            )}
            <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
              <DeleteForever onConfirm={() => purge.mutate(job.id)} disabled={busy} />
              <Button
                size="sm"
                variant="secondary"
                onClick={() => restore.mutate(job.id)}
                disabled={busy}
              >
                Put back in the deck
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
