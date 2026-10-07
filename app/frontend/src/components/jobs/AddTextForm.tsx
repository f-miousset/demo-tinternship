import { type FormEvent, useState } from "react";

import { PasteButton } from "./PasteButton";
import { Button, ErrorNote, RunProgress, inputClass } from "../ui";
import type { ImportResult } from "../../lib/types";
import type { useRunStream } from "../../lib/useRunStream";

/** Below this the backend refuses, and it can say so before a run is started. */
const MIN_TEXT = 200;

/**
 * The third way onto the deck: the posting's text, when there is no link worth
 * pasting.
 *
 * Postings arrive as emails, as PDFs, as a screenshot's worth of text in a
 * message from someone who saw it on their phone — and some arrive on boards
 * whose bot protection answers our HTTP client, and then our browser, with a
 * challenge instead of the page. Every one of those used to end the same way:
 * the candidate had the posting open in front of them and no way to get it into
 * the app.
 *
 * It ends where the pasted link ends — read, scored on the same scale, saved as
 * a `JobPosting` and tracked, because pasting a posting is the candidate saying
 * yes to it. The one difference is that the row may carry no link, which is the
 * only place in the app that is allowed: here the candidate already has the
 * posting.
 */
export function AddTextForm({
  run,
  onAdded,
  autoFocus = false,
}: {
  run: ReturnType<typeof useRunStream<ImportResult>>;
  onAdded: (result: ImportResult) => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const trimmed = text.trim();
  // Only once they have started: an empty field is not a mistake, it is the
  // state the form opens in.
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_TEXT;

  async function submitText(rawText: string) {
    const trimmedValue = rawText.trim();
    if (trimmedValue.length < MIN_TEXT || run.running) return;
    const added = await run.start("/api/jobs/import-text", { text: trimmedValue });
    if (added) {
      setText("");
      onAdded(added);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await submitText(text);
  }

  async function handlePaste(pasted: string) {
    setText(pasted);
    const trimmedValue = pasted.trim();
    if (trimmedValue.length >= MIN_TEXT && !run.running) {
      await submitText(trimmedValue);
    }
  }

  return (
    <div className="space-y-2">
      <form className="space-y-2" onSubmit={submit}>
        <label className="block">
          {/* The switch above is the visible heading; this is what a screen
              reader announces. */}
          <span className="sr-only">Paste the text of a job posting</span>
          <textarea
            rows={6}
            autoFocus={autoFocus}
            className={`${inputClass} min-h-32 resize-y`}
            placeholder="Paste the whole posting — the title, the company, and what the role actually is."
            value={text}
            disabled={run.running}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <div className="flex items-start gap-2">
          <PasteButton onPaste={handlePaste} label="Paste" disabled={run.running} />
          <Button
            type="submit"
            className="flex-1 sm:ml-auto sm:flex-none"
            disabled={run.running || trimmed.length < MIN_TEXT}
          >
            {run.running ? "Adding…" : "Add posting"}
          </Button>
        </div>
      </form>
      <p className="text-xs text-ink-500 dark:text-ink-400">
        {tooShort
          ? `${trimmed.length} of ${MIN_TEXT} characters — paste the posting itself, not just its title.`
          : "For a posting that came by email, as a PDF, or on a site that will not open for us. The agents read it, score it against your brief and put it straight on your Tracker, ready for the package. It keeps a link only if the text contains one that opens the posting."}
      </p>
      <ErrorNote error={run.error} />
      <RunProgress
        phases={run.phases}
        running={run.running}
        hint={run.running ? "Reading what you pasted and scoring it against your brief." : undefined}
      />
    </div>
  );
}
