import { type FormEvent, useState } from "react";

import { PasteButton } from "./PasteButton";
import { Button, ErrorNote, RunProgress, inputClass } from "../ui";
import type { ImportResult } from "../../lib/types";
import type { useRunStream } from "../../lib/useRunStream";

/**
 * The other way onto the deck: a link the candidate found themselves.
 *
 * One definition, two placements. On a laptop it is a card under the header; on
 * a phone it is the same form inside the sheet the "+" opens, because a URL
 * field permanently occupying the top of a 375px screen is a third of the space
 * the card needs. Two copies of this markup would drift the moment either one
 * was edited.
 */
export function AddLinkForm({
  run,
  onAdded,
  autoFocus = false,
}: {
  run: ReturnType<typeof useRunStream<ImportResult>>;
  onAdded: (result: ImportResult) => void;
  autoFocus?: boolean;
}) {
  const [url, setUrl] = useState("");

  async function submitUrl(rawUrl: string) {
    const trimmed = rawUrl.trim();
    if (!trimmed || run.running) return;
    const added = await run.start("/api/jobs/import", { url: trimmed });
    if (added) {
      // Clear the field: a run should end on the posting, not on a form still
      // holding the link that produced it.
      setUrl("");
      onAdded(added);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await submitUrl(url);
  }

  async function handlePaste(text: string) {
    const trimmed = text.trim();
    setUrl(trimmed);
    if (trimmed && !run.running) {
      await submitUrl(trimmed);
    }
  }

  return (
    <div className="space-y-2">
      <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={submit}>
        <label className="min-w-0 flex-1">
          {/* The switch above this form is the visible heading now, so a
              second one would say the same thing twice — but the field still
              needs a label a screen reader can announce. */}
          <span className="sr-only">Paste a job posting link</span>
          <input
            type="url"
            inputMode="url"
            autoFocus={autoFocus}
            className={inputClass}
            placeholder="Paste a job posting link"
            value={url}
            disabled={run.running}
            onChange={(event) => setUrl(event.target.value)}
          />
        </label>
        {/* One row on a phone as well as a laptop: a lone "Paste" above a
            full-width "Add posting" reads as a step you have to take, and it
            is an alternative to typing rather than a stage before submitting. */}
        <div className="flex items-start gap-2">
          {/* A URL is the one thing nobody types. On a phone, pasting one by
              hand is a long-press over a field the keyboard is covering. */}
          <PasteButton
            onPaste={handlePaste}
            label="Paste"
            disabled={run.running}
          />
          <Button
            type="submit"
            className="flex-1 sm:flex-none"
            disabled={run.running || !url.trim()}
          >
            {run.running ? "Adding…" : "Add posting"}
          </Button>
        </div>
      </form>
      <p className="text-xs text-ink-500 dark:text-ink-400">
        The agents open the link, read the posting and score it against your brief. You found this
        one, so it goes straight to your Tracker rather than onto the deck — and the card below
        offers to write the package in English or in French there and then. If the link will not
        open for them, paste the posting's text instead.
      </p>
      <ErrorNote error={run.error} />
      <RunProgress
        phases={run.phases}
        running={run.running}
        hint={
          run.running
            ? "Opening the link and reading the posting. Boards behind bot protection are opened in a real browser, which takes a few seconds longer."
            : undefined
        }
      />
    </div>
  );
}
