import { useState } from "react";

import { Button } from "../ui";

/**
 * Fill a field from the clipboard and launch the process, for the one screen
 * where that is the point.
 *
 * On a phone, pasting is a long-press, a wait for a bubble, and a tap on a
 * target the size of a word — over a field that already has a keyboard covering
 * half the screen. This is the same action as one 44px button, and it is the
 * only thing anyone does with these two fields: the entire Jobs add box exists
 * because the candidate has something on their clipboard.
 *
 * **It renders nothing when the browser cannot read the clipboard**, which is a
 * real case rather than a defensive flourish: `readText` is Chromium and Safari
 * only — Firefox exposes it to extensions and not to pages — and any browser
 * refuses it outside a secure context. A button that silently does nothing is
 * worse than no button, and the field is still there to paste into by hand.
 *
 * `onPaste` receives the text, so the caller decides what to do with it — the
 * link form trims it into one field and launches the import, the text form
 * replaces its whole draft and launches if it meets the character floor.
 */
export function PasteButton({
  onPaste,
  label = "Paste",
  disabled = false,
}: {
  onPaste: (text: string) => void | Promise<void>;
  label?: string;
  disabled?: boolean;
}) {
  const [refused, setRefused] = useState(false);
  const available =
    typeof navigator !== "undefined" && typeof navigator.clipboard?.readText === "function";
  if (!available) return null;

  return (
    <div className="flex flex-col items-start">
      <Button
        type="button"
        variant="secondary"
        disabled={disabled}
        title="Paste what is on your clipboard into the field and add the posting"
        onClick={async () => {
          let text: string;
          try {
            text = await navigator.clipboard.readText();
            setRefused(false);
          } catch {
            // Safari and Firefox can prompt for permission and be denied, and a
            // page that is not focused throws outright. Say so once rather than
            // appearing to have done nothing: the field still works.
            setRefused(true);
            return;
          }
          if (text) {
            await onPaste(text);
          }
        }}
      >
        {label}
      </Button>
      {refused && (
        <span className="mt-1 text-xs text-amber-600 dark:text-amber-400">
          Your browser would not hand over the clipboard — paste into the field instead.
        </span>
      )}
    </div>
  );
}
