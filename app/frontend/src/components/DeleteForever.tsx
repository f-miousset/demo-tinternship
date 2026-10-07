import { useEffect, useState } from "react";

import { Button } from "./ui";

/**
 * The one irreversible button in either trash, armed by a first tap and fired
 * by a second.
 *
 * Both trashes exist so that throwing something away is safe enough to do
 * quickly — and this is the button that ends that safety. A modal "Are you
 * sure?" would be a third surface stacked on the trash's own sheet, and
 * `window.confirm` is a browser dialog an installed PWA renders badly; a button
 * that has to be pressed twice, in place, asks the same question where the
 * finger already is. It disarms itself after a few seconds, so a stray tap
 * left armed is not a trap for the next one.
 */
const ARMED_FOR_MS = 4000;

export function DeleteForever({
  onConfirm,
  disabled,
  label = "Delete forever",
  armedLabel = "Tap again to delete",
}: {
  onConfirm: () => void;
  disabled?: boolean;
  label?: string;
  armedLabel?: string;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), ARMED_FOR_MS);
    return () => window.clearTimeout(timer);
  }, [armed]);

  return (
    <Button
      size="sm"
      variant={armed ? "danger" : "ghost"}
      disabled={disabled}
      onClick={() => {
        if (armed) {
          setArmed(false);
          onConfirm();
        } else {
          setArmed(true);
        }
      }}
    >
      {armed ? armedLabel : label}
    </Button>
  );
}
