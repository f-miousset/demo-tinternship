import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, ErrorNote, RunProgress, SectionTitle } from "../ui";
import { api } from "../../lib/api";
import type { AgentPrompt, HrExpertResult } from "../../lib/types";
import { useRunStream } from "../../lib/useRunStream";
import { PromptPanel } from "./PromptPanel";
import { jumpToSection } from "./sections";

/**
 * Step 4: how to win these roles.
 *
 * `autoRun` counts the briefs the Interrogator finished the interview on its
 * own. Every increment is a fresh brief that nothing has been researched
 * against yet, so it starts the HR Expert here — the playbook is derived from
 * the brief, and a brief with no playbook is the state the app refuses to open
 * the main screens in.
 */
export function PlaybookSection({ autoRun = 0 }: { autoRun?: number }) {
  const queryClient = useQueryClient();
  const [handedOff, setHandedOff] = useState(false);
  const lastAutoRun = useRef(autoRun);

  const { data: active } = useQuery({
    queryKey: ["prompts", "active"],
    queryFn: () => api.get<Record<string, AgentPrompt | null>>("/api/strategy/prompts/active"),
  });

  const runHrExpert = useRunStream<HrExpertResult>();

  const research = useCallback(async () => {
    await runHrExpert.start("/api/strategy/hr-expert");
    // Whatever happened. The playbook is saved as a new version before the
    // audit runs, so a run that fell over at the last step still wrote one.
    queryClient.invalidateQueries({ queryKey: ["prompts"] });
    queryClient.invalidateQueries({ queryKey: ["config"] });
  }, [runHrExpert, queryClient]);

  useEffect(() => {
    if (autoRun === lastAutoRun.current) return;
    lastAutoRun.current = autoRun;
    setHandedOff(true);
    // The run is two minutes of progress lines the candidate never asked to
    // start; the least it can do is be on screen while it happens.
    jumpToSection("playbook");
    void research();
  }, [autoRun, research]);

  return (
    <div className="space-y-4">
      <SectionTitle
        title="4 · Hiring playbook"
        subtitle="How hiring actually works for this role and region, researched on the open web with citations you can check. It runs itself once the brief exists, and steers every agent after it."
        action={
          <Button
            className="w-full sm:w-auto"
            onClick={() => void research()}
            disabled={runHrExpert.running || !active?.search_brief}
            title={
              active?.search_brief
                ? "Researches the current brief and saves a new version of the playbook."
                : "The HR Expert researches the brief, so there has to be one first."
            }
          >
            {runHrExpert.running ? "Researching…" : "Run HR Expert research"}
          </Button>
        }
      />

      <ErrorNote error={runHrExpert.error} />
      <RunProgress
        phases={runHrExpert.phases}
        running={runHrExpert.running}
        hint={
          runHrExpert.running
            ? handedOff
              ? "Your brief is written, so this started on its own: searching the web for how hiring works in your domain. It takes a minute or two."
              : "Searching the web for how hiring works in your domain — this takes a minute or two."
            : undefined
        }
      />

      <PromptPanel
        kind="playbook"
        label="Hiring playbook"
        emptyHint="This runs on its own as soon as a brief exists. The button here re-runs it against the current brief."
      />
    </div>
  );
}
