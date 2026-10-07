/**
 * What every visitor is told before anything else: this is a demo, and how.
 *
 * Shown once per browser session, as a sheet over the app (the app's own
 * `Modal`, so it is the same glass, drags closed on a phone and returns focus).
 * After that a small "Demo" pill stays on screen to reopen it — which is also
 * where "Reset the demo" lives — and a toast explains each auto-filled prompt.
 *
 * Mounted in its own React root beside the app's, so the app's tree is the
 * real one, untouched.
 */
import { useCallback, useEffect, useState } from "react";

import { Button, Modal } from "../../../app/frontend/src/components/ui";
import { reset } from "../mock/store";
import { installAutofill } from "./autofill";

export const REPO_URL = "https://github.com/f-miousset/demo-tinternship";
export const GUIDE_URL = "https://f-miousset.github.io/demo-tinternship/";
const SEEN = "demo-tinternship:notice-seen";

function seenThisSession(): boolean {
  try {
    return sessionStorage.getItem(SEEN) === "1";
  } catch {
    return false;
  }
}

function markSeen(): void {
  try {
    sessionStorage.setItem(SEEN, "1");
  } catch {
    /* private mode: the notice simply shows again next load */
  }
}

export function DemoNotice() {
  const [open, setOpen] = useState(() => !seenThisSession());
  const [hint, setHint] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const close = useCallback(() => {
    markSeen();
    setOpen(false);
    setConfirming(false);
  }, []);

  useEffect(() => installAutofill(setHint), []);

  useEffect(() => {
    if (!hint) return;
    const timer = window.setTimeout(() => setHint(null), 5000);
    return () => window.clearTimeout(timer);
  }, [hint]);

  async function startOver() {
    await reset();
    window.location.assign("/jobs");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="demo-pill glass squircle rounded-full px-3 text-xs font-semibold text-ink-800 dark:text-ink-100"
        aria-label="About this demo"
      >
        <span aria-hidden="true" className="demo-pill-dot" /> Demo
      </button>

      {hint && (
        <div role="status" className="demo-toast glass squircle rounded-control px-4 py-3 text-sm text-ink-800 dark:text-ink-100">
          {hint}
        </div>
      )}

      <Modal open={open} onClose={close} title="This is a demo of Tinternship">
        <div className="space-y-4 text-sm leading-relaxed text-ink-700 dark:text-ink-200">
          <p>
            Tinternship is a team of AI agents that finds internships and fills in your own CV and cover letter for each
            one. <strong>Here, no AI is called.</strong> Every agent answer — searches, scores, documents, interview
            briefs, traces — was written in advance, and runs are replayed so you can watch them.
          </p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>
              <strong>Tap a text box</strong> that talks to the agents and it fills in a prompt the demo has an answer
              for. Press send.
            </li>
            <li>
              <strong>Your changes stay in this browser.</strong> Nothing you do is sent anywhere; nobody else sees it,
              and you see nobody else's.
            </li>
            <li>
              <strong>Everyone in it is fictional</strong> — the candidate Alex Martin, every company, every link.
            </li>
          </ul>
          <p>
            The real agents' code is published for review, with a guide to running it yourself with your own API key:{" "}
            <a className="text-accent-600 underline dark:text-accent-400" href={REPO_URL} target="_blank" rel="noreferrer">
              source code
            </a>{" "}
            ·{" "}
            <a className="text-accent-600 underline dark:text-accent-400" href={GUIDE_URL} target="_blank" rel="noreferrer">
              set it up for yourself
            </a>
            .
          </p>
          <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-between">
            {confirming ? (
              <Button variant="danger" onClick={() => void startOver()}>
                Yes, erase my changes
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => setConfirming(true)}>
                Reset the demo
              </Button>
            )}
            <Button onClick={close}>Start exploring</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
