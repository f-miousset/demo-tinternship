import { useQuery } from "@tanstack/react-query";

import { Button, Card, ErrorNote, SectionTitle, Spinner } from "../ui";
import { api } from "../../lib/api";
import type { ChatMessage } from "../../lib/types";
import { PromptPanel } from "./PromptPanel";
import { useBriefWriting, useGenerateBrief } from "./useGenerateBrief";

/**
 * Step 3: what to look for.
 *
 * Written by the Interrogator when it decides the interview is over, so the
 * button here is the manual override — it re-reads the transcript and saves a
 * new version. Unlike the automatic path it does *not* carry on into the HR
 * Expert research: a click is someone taking control, usually to re-write a
 * brief after an edit, and a two-minute grounded run off the back of that would
 * be a surprise rather than a convenience.
 */
export function BriefSection() {
  const finalise = useGenerateBrief();
  const writing = useBriefWriting();

  // Same query key as the interview, so knowing whether there is a transcript
  // to write from costs no extra request.
  const { data: transcript } = useQuery({
    queryKey: ["interview", "history"],
    queryFn: () => api.get<{ messages: ChatMessage[] }>("/api/interview/history"),
  });
  const interviewed = (transcript?.messages ?? []).length >= 2;

  async function writeBrief() {
    if (writing) return;
    try {
      await finalise.mutateAsync();
    } catch {
      // `finalise.error` is rendered below.
    }
  }

  return (
    <div className="space-y-4">
      <SectionTitle
        title="3 · Search brief"
        subtitle="What the Investigator looks for, and what the Applying agents write towards. The Interrogator writes it when the interview above is done; edit it freely, and every save is a new version."
        action={
          <Button
            className="w-full sm:w-auto"
            onClick={() => void writeBrief()}
            disabled={writing || !interviewed}
            title={
              interviewed
                ? "Re-reads the interview and saves a new version of the brief."
                : "Talk to the Interrogator first — the brief is written from the transcript."
            }
          >
            {writing ? "Writing brief…" : "Generate search brief"}
          </Button>
        }
      />

      <ErrorNote error={finalise.error} />
      {writing && (
        <Card>
          <Spinner label="Reading the interview and writing the brief…" />
        </Card>
      )}

      <PromptPanel
        kind="search_brief"
        label="Search brief"
        emptyHint="Talk to the Interrogator above — it writes the brief when it has enough. The button here writes one from the conversation so far."
      />
    </div>
  );
}
