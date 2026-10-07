import type { ApplicationStatus } from "./types";

/**
 * Every status's name as a person reads it, in pipeline order — the Tracker's
 * columns, the application page's buttons and the search all read this one map,
 * so a status cannot be "HR pre-call" in one place and `hr_pre_call` in another.
 */
export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  saved: "Saved",
  preparing: "Preparing",
  applied: "Applied",
  hr_pre_call: "HR pre-call",
  hr_interview: "HR interview",
  technical_test: "Technical test",
  manager_interview: "Manager interview",
  offer: "Offer",
  rejected: "Rejected",
  ghosted: "Ghosted",
  withdrawn: "Withdrawn",
};

/**
 * The interview rounds, which replaced the single `interview` status on
 * 2026-10-05. Reaching any of them starts the interview brief — once, whichever
 * comes first, because a process may skip any round. The backend's
 * `INTERVIEW_STATUSES` is the same four.
 */
export const INTERVIEW_STATUSES: readonly ApplicationStatus[] = [
  "hr_pre_call",
  "hr_interview",
  "technical_test",
  "manager_interview",
];

export function isInterview(status: ApplicationStatus): boolean {
  return INTERVIEW_STATUSES.includes(status);
}
