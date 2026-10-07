import type { AppConfig } from "../../lib/types";

/**
 * The parts of the one-time account setup.
 *
 * Profile, Interview and Strategy were steps 1–3 of the workflow, each on its
 * own route. You do them once — so they are one long page now, under Account.
 * They are still ordered and each still hands off to the next, which is what
 * the anchors are for.
 *
 * Strategy was one step holding two tabs. It is two steps now: the brief and
 * the playbook have different producers, different inputs and different reasons
 * to be re-run, and hiding one behind a tab on the other's step said they were
 * one decision.
 *
 * The base résumés joined the list on 2026-08-28. They share the Profile
 * section — one upload does both jobs — but they are their own checklist line,
 * because "the app knows who you are" and "the app has the document it sends"
 * are different states and only the second one blocks an application.
 *
 * The base cover letters joined on 2026-09-09, when the letter stopped being
 * written from scratch. A separate line again rather than "base documents":
 * an application produces two files, and a checklist that ticks with the CV
 * uploaded and the letter missing would be telling you the setup is done.
 *
 * Courses & skills joined on 2026-08-29, and are a third distinct state for the
 * same reason: the résumé's coursework and skills blanks are filled by
 * *selecting* from lists the candidate wrote, so a profile that knows who they
 * are is still not something those two blanks can be filled from.
 */
export const ACCOUNT_SECTIONS: {
  id: string;
  label: string;
  /** The `/api/config` flag that says this part is done. */
  flag: keyof AppConfig["progress"];
  todo: string;
}[] = [
  {
    id: "profile",
    label: "Base résumés",
    flag: "has_base_resumes",
    todo: "Upload your own Word CV in French and in English.",
  },
  {
    id: "profile",
    label: "Cover letters",
    flag: "has_base_letters",
    todo: "Upload your own Word cover letter in both languages — the run fills its blanks.",
  },
  {
    id: "profile",
    label: "Profile",
    flag: "has_profile",
    todo: "Read from your base résumé, or import a LinkedIn export.",
  },
  {
    id: "profile",
    label: "Courses & skills",
    flag: "has_lists",
    todo: "List your coursework and your skills — the résumé picks from them.",
  },
  {
    id: "interview",
    label: "Interview",
    flag: "has_interview",
    todo: "Talk to the Interrogator until it has what it needs.",
  },
  {
    id: "brief",
    label: "Search brief",
    flag: "has_brief",
    todo: "Written for you when the interview is done.",
  },
  {
    id: "playbook",
    label: "Hiring playbook",
    flag: "has_playbook",
    todo: "Researched for you once the brief exists.",
  },
];

/**
 * Scroll one section into view.
 *
 * Movement inside one page, deliberately without touching the URL: a hash would
 * have to be honoured on load too, and restoring a scroll position into a page
 * whose three sections are all still fetching lands nowhere near the section.
 * Old `/interview` and `/strategy` links go to the top of the Account page,
 * where the checklist points at all three.
 */
export function jumpToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
