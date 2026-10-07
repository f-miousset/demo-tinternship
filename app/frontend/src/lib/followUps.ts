import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "./api";
import type { FollowUp, FollowUpEmail, FollowUpsResponse } from "./types";

export const FOLLOW_UPS_KEY = ["follow-ups"] as const;

/**
 * The applications that have gone quiet.
 *
 * One shared query key, so the header badge and the Tracker panel are the same
 * fetch: two independent polls of the same endpoint would drift apart and show
 * different counts on the same screen. Five minutes is plenty — the thing being
 * watched changes on the scale of days.
 */
export function useFollowUps() {
  return useQuery({
    queryKey: FOLLOW_UPS_KEY,
    queryFn: () => api.get<FollowUpsResponse>("/api/applications/follow-ups"),
    refetchInterval: 5 * 60_000,
  });
}

const SUBJECT_LABEL: Record<string, string> = { en: "Subject", fr: "Objet" };

/** The message only — never `to_hint` or `send_notes`, which are advice to you. */
export function emailBody(email: FollowUpEmail): string {
  return [email.greeting, ...(email.paragraphs ?? []), email.sign_off, email.signature]
    .map((part) => (part ?? "").trim())
    .filter(Boolean)
    .join("\n\n");
}

/** What lands on the clipboard: the subject line, then the body. */
export function emailText(email: FollowUpEmail): string {
  const subject = (email.subject ?? "").trim();
  const label = SUBJECT_LABEL[email.language] ?? SUBJECT_LABEL.en;
  return (subject ? `${label}: ${subject}\n\n` : "") + emailBody(email);
}

/**
 * A `mailto:` with no recipient.
 *
 * Deliberately: the agent is forbidden from inventing an address, so the app
 * does not have one to fill in. It opens a composed draft in whatever the
 * device treats as its mail client and leaves the To field to you — which is
 * also the moment to reply inside the original thread instead, as `to_hint`
 * usually suggests.
 */
export function mailtoHref(email: FollowUpEmail): string {
  const parameters = new URLSearchParams({
    subject: (email.subject ?? "").trim(),
    body: emailBody(email),
  });
  return `mailto:?${parameters.toString()}`;
}

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notificationPermission(): NotificationPermission | "unsupported" {
  return notificationsSupported() ? Notification.permission : "unsupported";
}

export async function askForNotifications(): Promise<NotificationPermission | "unsupported"> {
  if (!notificationsSupported()) return "unsupported";
  return Notification.requestPermission();
}

// Which silences have already been announced, so reopening the app is not a
// fresh round of notifications. Keyed by application id, valued by the
// `last_activity` the alert was about: when you mark a follow-up as sent that
// timestamp moves, so the *next* silence on the same application notifies
// again while the current one never repeats.
const ANNOUNCED_KEY = "tinternship.follow-ups-announced";

function readAnnounced(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(ANNOUNCED_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    // Private browsing, or a corrupted value. Losing the record means one
    // duplicate notification, which is better than throwing inside an effect.
    return {};
  }
}

function writeAnnounced(value: Record<string, string>) {
  try {
    window.localStorage.setItem(ANNOUNCED_KEY, JSON.stringify(value));
  } catch {
    /* nothing to do — see readAnnounced */
  }
}

/**
 * Raise a system notification for each newly-silent application.
 *
 * **This only fires while the app is open**, which is the honest limit of doing
 * it without a push service: there is no VAPID key, no subscription store and
 * no server pushing to one. Installed to the home screen and opened daily —
 * which is how this app is used — that is enough to be the reminder, and the
 * header badge covers the rest. See documentation/frontend.md.
 */
export function useFollowUpAlerts(followUps: FollowUp[] | undefined) {
  useEffect(() => {
    if (!followUps?.length) return;
    if (!notificationsSupported() || Notification.permission !== "granted") return;

    const announced = readAnnounced();
    const seen = new Set(followUps.map((item) => String(item.application_id)));
    let changed = false;

    for (const item of followUps) {
      const key = String(item.application_id);
      if (announced[key] === item.last_activity) continue;
      announced[key] = item.last_activity;
      changed = true;

      const where = item.job.company || item.job.title || "An application";
      const notification = new Notification(`${where} has gone quiet`, {
        body: item.draft
          ? `${item.days_silent} days with no reply. The follow-up email is written and ready to send.`
          : `${item.days_silent} days with no reply. Open the Tracker to write the follow-up.`,
        icon: "/favicon.svg",
        // One notification per application, so a refresh replaces rather than
        // stacks a second copy of the same reminder.
        tag: `follow-up-${item.application_id}`,
      });
      notification.onclick = () => {
        window.focus();
        window.location.href = "/tracker";
      };
    }

    // Forget applications that have been answered or chased, so the record does
    // not grow forever and a later silence on the same one alerts again.
    for (const key of Object.keys(announced)) {
      if (!seen.has(key)) {
        delete announced[key];
        changed = true;
      }
    }
    if (changed) writeAnnounced(announced);
  }, [followUps]);
}
