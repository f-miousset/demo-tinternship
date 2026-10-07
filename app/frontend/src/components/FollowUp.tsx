import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import {
  FOLLOW_UPS_KEY,
  askForNotifications,
  emailText,
  mailtoHref,
  notificationPermission,
  useFollowUpAlerts,
  useFollowUps,
} from "../lib/followUps";
import type {
  Application,
  Artifact,
  FollowUp,
  FollowUpEmail,
  FollowUpResult,
} from "../lib/types";
import { useRunStream } from "../lib/useRunStream";
import { Badge, BulletList, Button, Card, ErrorNote, Spinner } from "./ui";

/**
 * The applications that have gone quiet, and the email that chases each one.
 *
 * This is the notification. A count in the header says how many, this says
 * which — and it opens with the email already written, because the reason a
 * follow-up does not get sent is never that the candidate forgot it existed. It
 * is that there is nothing obvious to say two weeks later, and a blank compose
 * window at that moment is where the intention dies. See
 * `services/follow_up.py`.
 */
export function FollowUpsPanel() {
  const { data, isLoading } = useFollowUps();
  const followUps = data?.follow_ups ?? [];
  const [open, setOpen] = useState<number | null>(null);

  useFollowUpAlerts(followUps);

  if (isLoading || followUps.length === 0) return null;

  // The longest silence is first and opens by default: with three due, reading
  // one email is the job, and scrolling past three collapsed rows to get to it
  // is friction on the exact action this panel exists to cause.
  const expanded = open ?? followUps[0].application_id;

  return (
    <Card className="space-y-3 border-amber-300 bg-amber-50/60 dark:border-amber-900/60 dark:bg-amber-950/30">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold tracking-tight">
            {followUps.length === 1
              ? "One application is waiting on a reply"
              : `${followUps.length} applications are waiting on a reply`}
          </h3>
          <p className="mt-0.5 text-sm text-ink-600 dark:text-ink-300">
            Nothing has happened on {followUps.length === 1 ? "it" : "these"} for{" "}
            {data?.after_days ?? 14} days or more. Each email below is already written — read
            it, send it, then mark it sent so the clock restarts.
          </p>
        </div>
        <AlertToggle />
      </div>

      <ul className="space-y-2">
        {followUps.map((followUp) => (
          <li key={followUp.application_id}>
            <FollowUpRow
              followUp={followUp}
              expanded={expanded === followUp.application_id}
              onToggle={() =>
                setOpen(expanded === followUp.application_id ? -1 : followUp.application_id)
              }
            />
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Asking for notification permission, at the only moment it makes sense.
 *
 * Not in Settings and not on first load: a browser that is asked to notify
 * before there is anything to notify about gets refused, and the refusal is
 * permanent per origin. Here the user is looking at the thing the alert would
 * have told them about, so the offer explains itself.
 */
function AlertToggle() {
  const [permission, setPermission] = useState(notificationPermission);

  if (permission === "unsupported" || permission === "granted") return null;
  if (permission === "denied") {
    return (
      <Badge tone="neutral" title="Re-enable notifications for this site in your browser settings">
        alerts blocked
      </Badge>
    );
  }

  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={() => void askForNotifications().then(setPermission)}
      title="Get a notification when an application goes quiet, while the app is open"
    >
      Alert me
    </Button>
  );
}

function FollowUpRow({
  followUp,
  expanded,
  onToggle,
}: {
  followUp: FollowUp;
  expanded: boolean;
  onToggle: () => void;
}) {
  const queryClient = useQueryClient();
  const draft = useRunStream<FollowUpResult>();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: FOLLOW_UPS_KEY });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    queryClient.invalidateQueries({ queryKey: ["application", followUp.application_id] });
    queryClient.invalidateQueries({ queryKey: ["artifacts", followUp.application_id] });
  };

  const markSent = useMutation({
    mutationFn: () =>
      api.post(`/api/applications/${followUp.application_id}/follow-up/sent`),
    onSuccess: invalidate,
  });

  // The other honest answer. Some postings have nobody behind them — an agency
  // listing, a portal that answers nothing, a form with no name — and marking
  // that one "sent" would put a lie in the timeline the next draft is written
  // from. See `services/follow_up.py::NO_CONTACT_NOTE`.
  const markUnreachable = useMutation({
    mutationFn: () =>
      api.post(`/api/applications/${followUp.application_id}/follow-up/no-contact`),
    onSuccess: invalidate,
  });

  async function rewrite() {
    await draft.start(`/api/applications/${followUp.application_id}/follow-up`);
    invalidate();
  }

  const email = followUp.draft?.content;

  return (
    <div className="squircle rounded-card border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
      <button
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-2 p-3 text-left"
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium">
            {followUp.job.company || "Unknown company"}
          </span>
          <span className="block truncate text-xs text-ink-500">{followUp.job.title}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <Badge tone="warn">silent {followUp.days_silent}d</Badge>
          {email ? (
            followUp.draft_stale ? (
              <Badge tone="neutral" title="Written before the last note on this application">
                draft outdated
              </Badge>
            ) : (
              <Badge tone="good">email ready</Badge>
            )
          ) : (
            <Badge tone="neutral">no draft yet</Badge>
          )}
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-ink-200 p-3 dark:border-ink-800">
          <ErrorNote error={draft.error} />
          <ErrorNote error={markSent.error} />
          <ErrorNote error={markUnreachable.error} />

          {draft.running ? (
            <Spinner
              label={draft.phases[draft.phases.length - 1]?.message ?? "Starting the run…"}
            />
          ) : email ? (
            <EmailSheet email={email} />
          ) : (
            <p className="text-sm text-ink-500 dark:text-ink-400">
              No email has been written for this one yet. The app drafts these in the
              background as they come due; write it now if you do not want to wait.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {email && <CopyButton email={email} />}
            {email && (
              <a
                href={mailtoHref(email)}
                className="inline-flex min-h-9 items-center rounded-lg border border-ink-200 px-2.5 text-xs hover:bg-ink-50 sm:min-h-0 sm:py-1 dark:border-ink-700 dark:hover:bg-ink-800"
              >
                Open in mail
              </a>
            )}
            <Button
              size="sm"
              variant={email ? "primary" : "secondary"}
              onClick={() => markSent.mutate()}
              disabled={markSent.isPending}
              title="Records it in the timeline and restarts the clock"
            >
              {markSent.isPending ? "Saving…" : "Mark as sent"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => markUnreachable.mutate()}
              disabled={markUnreachable.isPending}
              title="No address and no name anywhere — records that and stops the nudge for now"
            >
              {markUnreachable.isPending ? "Saving…" : "Failed to contact anyone"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void rewrite()}
              disabled={draft.running}
            >
              {draft.running ? "Writing…" : email ? "Rewrite" : "Write it now"}
            </Button>
            <Link
              to={`/applications/${followUp.application_id}`}
              className="text-xs text-accent-600 underline"
            >
              open application
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The follow-up on the application's own page.
 *
 * Not a fourth tab: the plan, résumé and cover letter are one package produced
 * by one run, and this is written weeks later by a different agent for a
 * different reason. It sits under the status bar, next to the timeline that
 * says why it exists.
 *
 * **Always offered, never only when overdue.** The 14-day sweep is the app
 * noticing on your behalf; it is not permission to write one. Plenty of good
 * reasons to chase early exist — a deadline you have learned about, a
 * conversation at a careers fair, a referral who asked to be told — and none of
 * them should require waiting for a threshold to pass first. The one case with
 * nothing to offer is an application that has not been sent, and that says so
 * rather than hiding.
 */
export function ApplicationFollowUp({
  application,
  artifact,
}: {
  application: Application;
  artifact?: Artifact;
}) {
  const queryClient = useQueryClient();
  const draft = useRunStream<FollowUpResult>();

  const applicationId = application.id;
  const silence = application.silence;
  const email = artifact?.content as FollowUpEmail | undefined;
  // Undefined only on an older cached payload; treat that as "go ahead" rather
  // than greying out a button over a field that has not arrived yet.
  const sendable = silence?.sendable ?? true;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: FOLLOW_UPS_KEY });
    queryClient.invalidateQueries({ queryKey: ["artifacts", applicationId] });
    queryClient.invalidateQueries({ queryKey: ["application", applicationId] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
  };

  const markSent = useMutation({
    mutationFn: () => api.post(`/api/applications/${applicationId}/follow-up/sent`),
    onSuccess: invalidate,
  });

  async function write() {
    await draft.start(`/api/applications/${applicationId}/follow-up`);
    invalidate();
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-tight">Follow-up email</h3>
          <p className="text-xs text-ink-500 dark:text-ink-400">
            <SilenceLine silence={silence} hasDraft={Boolean(email)} />
            {artifact && ` Draft v${artifact.version}.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {email && <CopyButton email={email} />}
          {email && (
            <a
              href={mailtoHref(email)}
              className="inline-flex min-h-9 items-center rounded-lg border border-ink-200 px-2.5 text-xs hover:bg-ink-50 sm:min-h-0 sm:py-1 dark:border-ink-700 dark:hover:bg-ink-800"
            >
              Open in mail
            </a>
          )}
          {email && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => markSent.mutate()}
              disabled={markSent.isPending}
              title="Records it in the timeline and restarts the clock"
            >
              {markSent.isPending ? "Saving…" : "Mark as sent"}
            </Button>
          )}
          <Button
            size="sm"
            variant={email ? "ghost" : "primary"}
            onClick={() => void write()}
            disabled={draft.running || !sendable}
            title={
              sendable
                ? "Writes the email now — you do not have to wait for the nudge"
                : "Mark this application as applied first; there is nothing to follow up on yet"
            }
          >
            {draft.running ? "Writing…" : email ? "Write a new one" : "Write the email"}
          </Button>
          {artifact?.run_id && (
            <Link to={`/traces/${artifact.run_id}`} className="text-xs text-accent-600 underline">
              trace
            </Link>
          )}
        </div>
      </div>

      <ErrorNote error={draft.error} />
      <ErrorNote error={markSent.error} />
      {draft.running ? (
        <Spinner label={draft.phases[draft.phases.length - 1]?.message ?? "Starting the run…"} />
      ) : email ? (
        <EmailSheet email={email} />
      ) : null}
    </Card>
  );
}

/** One line saying where this application stands, in the words that fit it. */
function SilenceLine({
  silence,
  hasDraft,
}: {
  silence: Application["silence"];
  hasDraft: boolean;
}) {
  if (!silence) return <>Ask for one whenever you want.</>;
  if (!silence.sendable) {
    return <>This application has not been sent yet, so there is nothing to chase.</>;
  }
  const quiet = `Nothing has happened here for ${silence.days} day${silence.days === 1 ? "" : "s"}.`;
  if (silence.due) return <>{quiet}</>;
  if (!silence.waiting) return <>{quiet} Nobody owes you a reply on this one.</>;
  return (
    <>
      {quiet} {hasDraft ? "Written early — " : ""}The Tracker raises it at{" "}
      {silence.after_days}, but you do not have to wait.
    </>
  );
}

function CopyButton({ email }: { email: FollowUpEmail }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(emailText(email));
      setCopied(true);
      setFailed(false);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // No clipboard permission, or an insecure origin. The text is on screen
      // and selectable, so say so rather than failing silently.
      setFailed(true);
    }
  }

  return (
    <Button size="sm" variant="secondary" onClick={() => void copy()}>
      {copied ? "Copied" : failed ? "Select it above" : "Copy email"}
    </Button>
  );
}

/**
 * The message, drawn as the thing it is.
 *
 * The border matters: `to_hint` and `send_notes` are notes to the candidate,
 * and an email that arrives at a recruiter with "reply in the recruiter's
 * thread" pasted into it is the failure this layout exists to prevent. Inside
 * the sheet is what gets sent; outside it never does.
 */
function EmailSheet({ email }: { email: FollowUpEmail }) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-ink-200 bg-ink-50/50 p-3 dark:border-ink-700 dark:bg-ink-950/40">
        {email.subject && (
          <p className="mb-2 border-b border-ink-200 pb-2 text-sm font-medium dark:border-ink-800">
            {email.subject}
          </p>
        )}
        {/* Pre-wrapped rather than paragraphs of markup: this is the exact text
            that goes on the clipboard, so what is read is what is sent. */}
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {[email.greeting, ...(email.paragraphs ?? []), email.sign_off, email.signature]
            .map((part) => (part ?? "").trim())
            .filter(Boolean)
            .join("\n\n")}
        </p>
      </div>

      <div className="space-y-2 text-xs text-ink-500 dark:text-ink-400">
        <p className="border-t border-dashed border-ink-200 pt-2 dark:border-ink-800">
          {email.word_count > 0 && <span>{email.word_count} words. </span>}
          Nothing below this line is part of the email.
        </p>
        {email.to_hint && (
          <p className="text-ink-600 dark:text-ink-300">
            <span className="font-medium">Send it to:</span> {email.to_hint}
          </p>
        )}
        {email.send_notes?.length > 0 && <BulletList items={email.send_notes} />}
      </div>
    </div>
  );
}
