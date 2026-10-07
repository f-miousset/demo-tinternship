import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { BriefSection } from "../components/account/BriefSection";
import { InterviewSection } from "../components/account/InterviewSection";
import { PlaybookSection } from "../components/account/PlaybookSection";
import { ProfileSection } from "../components/account/ProfileSection";
import { ACCOUNT_SECTIONS, jumpToSection } from "../components/account/sections";
import { Badge, Card, SectionTitle } from "../components/ui";
import { api } from "../lib/api";
import type { AccountInfo, AppConfig } from "../lib/types";

export function AccountPage() {
  // Setup runs itself once it can: the Interrogator decides the interview is
  // over and writes the brief, and this counter carries that across to step 4,
  // which researches the playbook the new brief implies. Counting rather than
  // flagging, so a second interview later starts a second research run.
  const [briefsWritten, setBriefsWritten] = useState(0);

  const { data: account } = useQuery({
    queryKey: ["account"],
    queryFn: () => api.get<AccountInfo>("/api/account"),
  });
  // Progress comes from /api/config rather than /api/account: every mutation in
  // the three sections already invalidates it, so the checklist ticks over the
  // moment a part is done.
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/api/config"),
  });

  const progress = config?.progress;
  const remaining = ACCOUNT_SECTIONS.filter((section) => progress && !progress[section.flag]);
  const complete = progress?.complete ?? false;
  const signedInAs = account?.display_name || account?.username;

  return (
    <div className="space-y-8">
      <SectionTitle
        title="Account"
        subtitle="Who you are, what you are looking for, and how these agents should go about it. You set this up once — come back whenever you want to tune it."
      />

      <Card className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-medium">
              {signedInAs ? `Signed in as ${signedInAs}` : "Not signed in"}
            </h3>
            <p className="mt-0.5 text-sm text-ink-500 dark:text-ink-400">
              {account?.authenticated
                ? "Authelia handles the login; this app never sees a password. Sign out from the portal you logged in through."
                : "No Authelia session in front of this app — you are running it locally, where the only thing standing between you and the data is your own machine."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {account?.email && <Badge tone="info">{account.email}</Badge>}
            {account?.groups.map((group) => (
              <Badge key={group}>{group}</Badge>
            ))}
          </div>
        </div>

        <div className="border-t border-ink-200 pt-4 dark:border-ink-800">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">Setup</h3>
            <Badge tone={complete ? "good" : "warn"}>
              {complete
                ? "complete"
                : `${ACCOUNT_SECTIONS.length - remaining.length} of ${ACCOUNT_SECTIONS.length} done`}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">
            {complete
              ? "Everything the agents need is in place. Jobs and Tracker are open."
              : "Jobs and Tracker stay closed until your base résumés, your profile, the brief and the playbook all exist — searching without them produces results worth nothing. Only the first two are yours to do: the interview writes the brief, and the brief starts the research."}
          </p>
          <ol className="mt-3 space-y-2">
            {ACCOUNT_SECTIONS.map((section, index) => {
              const done = Boolean(progress?.[section.flag]);
              return (
                // Keyed on the flag, not the anchor: two steps share the
                // Profile section — the base résumés and the profile itself —
                // and only the flag is unique.
                <li key={section.flag}>
                  <button
                    onClick={() => jumpToSection(section.id)}
                    className="flex w-full items-start gap-3 rounded-lg border border-ink-200 px-3 py-3 text-left transition hover:border-accent-400 sm:py-2 dark:border-ink-800"
                  >
                    <span
                      className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                        done
                          ? "bg-emerald-500 text-white"
                          : "bg-ink-200 text-ink-600 dark:bg-ink-800 dark:text-ink-300"
                      }`}
                    >
                      {done ? "✓" : index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{section.label}</span>
                      <span className="block text-xs text-ink-500 dark:text-ink-400">
                        {section.todo}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </Card>

      <section id="profile" className="scroll-mt-24">
        <ProfileSection />
      </section>

      <section
        id="interview"
        className="scroll-mt-24 border-t border-ink-200 pt-8 dark:border-ink-800"
      >
        <InterviewSection onBriefReady={() => setBriefsWritten((count) => count + 1)} />
      </section>

      <section id="brief" className="scroll-mt-24 border-t border-ink-200 pt-8 dark:border-ink-800">
        <BriefSection />
      </section>

      <section
        id="playbook"
        className="scroll-mt-24 border-t border-ink-200 pt-8 dark:border-ink-800"
      >
        <PlaybookSection autoRun={briefsWritten} />
      </section>
    </div>
  );
}
