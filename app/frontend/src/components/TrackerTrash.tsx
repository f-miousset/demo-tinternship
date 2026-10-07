import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { DeleteForever } from "./DeleteForever";
import { Badge, Button, EmptyState, ScoreBadge, Spinner } from "./ui";
import { api } from "../lib/api";
import { STATUS_LABEL } from "../lib/statuses";
import type { Application } from "../lib/types";

/**
 * The Tracker's trash — applications you gave up on.
 *
 * The deck's trash and this one answer different questions, which is why there
 * are two. Swiping left is triage: you read a card for four seconds and said
 * no, and the posting never became anything. This is the pile for the ones you
 * *did* say yes to — the ones you saved, maybe generated a résumé and a cover
 * letter for, maybe applied to and heard nothing — and then decided were over.
 *
 * Nothing is destroyed, and "nothing" is meant literally: the status it had
 * reached, its whole timeline, your standing note, the personalisation you
 * typed, and every document, interview brief and contact shortlist ever
 * generated for it are all still on the row. The card below links to it, so an
 * application in the trash still opens exactly as it did on the board — and
 * putting it back returns it to the column it left rather than to the start.
 *
 * What it is *not* is a way back in for the agents: `partition_answered` drops
 * a trashed application's posting from every Investigator run, counted as
 * `trashed` rather than `applied`, whether or not it is sitting here.
 *
 * **Delete forever** is the one exception to "nothing is destroyed", and it is
 * explicit: it takes the application, its timeline, its documents and their
 * files, and leaves only a hidden tombstone of the posting so the agents never
 * propose it again — see `services/trash.py`.
 */
export function TrackerTrash() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["applications", "trashed"],
    queryFn: () => api.get<{ applications: Application[] }>("/api/applications?view=trashed"),
  });

  const restore = useMutation({
    mutationFn: (id: number) => api.post(`/api/applications/${id}/trash?trashed=false`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["applications"] }),
  });

  const purge = useMutation({
    mutationFn: (id: number | "all") =>
      api.del(id === "all" ? "/api/applications/trash" : `/api/applications/${id}`),
    // The posting goes too, and the Jobs page's lists read it.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["applications"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]),
  });

  const applications = data?.applications ?? [];
  const busy = restore.isPending || purge.isPending;

  if (isLoading) return <Spinner label="Loading the trash…" />;
  if (applications.length === 0) {
    return (
      <EmptyState
        title="Nothing thrown away yet"
        hint="Applications you give up on land here, whole — the status they reached, the timeline, your notes and every document generated for them. You can put any of them back."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <DeleteForever
          label={`Empty the trash (${applications.length})`}
          armedLabel={`Tap again to delete all ${applications.length}`}
          onConfirm={() => purge.mutate("all")}
          disabled={busy}
        />
      </div>
      <ul className="space-y-2">
        {applications.map((application) => (
          <li
            key={application.id}
            className="squircle rounded-card border border-ink-200 p-3 dark:border-ink-800"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-semibold">{application.job?.company}</p>
                <p className="truncate text-sm text-ink-600 dark:text-ink-300">
                  {application.job?.title}
                </p>
              </div>
              {application.job?.fit_score ? <ScoreBadge score={application.job.fit_score} /> : null}
            </div>
            {/* What it kept. The status is the column it will go back to, and the
                artifact badges are the point of this pile existing at all: a
                package that took two model runs to write is still on the row. */}
            <div className="mt-2 flex flex-wrap items-center gap-1">
              <Badge>{STATUS_LABEL[application.status]}</Badge>
              {application.artifacts.map((artifact) => (
                <Badge key={artifact.id}>{artifact.kind.replace("_", " ")}</Badge>
              ))}
              {application.trashed_at && (
                <span className="text-xs text-ink-500 dark:text-ink-400">
                  trashed {new Date(application.trashed_at).toLocaleDateString()}
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
              <Link
                to={`/applications/${application.id}`}
                className="text-xs text-ink-500 underline underline-offset-2 hover:text-ink-800 dark:text-ink-400 dark:hover:text-ink-100"
              >
                Open it
              </Link>
              <DeleteForever onConfirm={() => purge.mutate(application.id)} disabled={busy} />
              <Button
                size="sm"
                variant="secondary"
                onClick={() => restore.mutate(application.id)}
                disabled={busy}
              >
                Put back on the board
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
