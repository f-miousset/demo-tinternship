import { useCallback, useRef, useState } from "react";

/**
 * Pulling a sheet down to close it.
 *
 * The phone gesture for "I am done with this" is a drag downwards, not a hunt
 * for a 24px cross in a corner the thumb does not reach. This is the same
 * hand-rolled Pointer Events approach as `useSwipe` — one code path for finger,
 * mouse and pen, `setPointerCapture` so a fast flick that leaves the handle
 * still ends on it — narrowed to one direction.
 *
 * Only one direction: a sheet that follows the finger upwards would promise a
 * taller sheet that does not exist. Everything above the origin is clamped to
 * zero, so pulling up does nothing rather than something wrong.
 *
 * **Pointer capture retargets the click.** While a pointer is captured, the
 * browser dispatches `click` to the capturing element instead of the button the
 * finger was actually on — so any control inside the handle must stop
 * `pointerdown` from reaching this, the way `Modal`'s ✕ and the job card's
 * links do. That is the bug this app already had once: the card's `details`
 * button was inside the deck's drag surface and its clicks were being eaten.
 */

/** Below this, a drag is a tap that wandered. */
const DEADZONE = 8;

/**
 * How far the sheet must travel before releasing it closes.
 *
 * A fixed distance rather than a fraction of the sheet: these sheets range from
 * two lines of trash to a full posting, and a threshold that grew with the
 * content would make the long ones feel stuck.
 */
const COMMIT = 88;

/** A fast flick counts even when it is short: px per ms. */
const ESCAPE_VELOCITY = 0.5;

export interface SheetDrag {
  /** How far down the sheet has been pulled, in px. Never negative. */
  dy: number;
  dragging: boolean;
  bind: {
    onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
    onPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
    onPointerUp: (event: React.PointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: React.PointerEvent<HTMLElement>) => void;
  };
}

export function useSheetDrag(onDismiss: () => void): SheetDrag {
  const [dy, setDy] = useState(0);
  const [dragging, setDragging] = useState(false);
  // A ref, not state: it is read on every frame of the drag, and re-rendering
  // to store the origin would fight the gesture it is measuring.
  const origin = useRef<{ y: number; at: number } | null>(null);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLElement>) => {
    // Only the primary button. A right-click drag is a context menu.
    if (event.pointerType === "mouse" && event.button !== 0) return;
    origin.current = { y: event.clientY, at: event.timeStamp };
    // Capture is an optimisation, and it throws `NotFoundError` when the
    // pointer id is no longer active. Losing the whole drag over it would be
    // the wrong trade — see the same guard in `useSwipe`.
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* the drag works without it; only a pointer that leaves the handle is lost */
    }
    setDragging(true);
    setDy(0);
  }, []);

  const onPointerMove = useCallback((event: React.PointerEvent<HTMLElement>) => {
    const from = origin.current;
    if (!from) return;
    setDy(Math.max(0, event.clientY - from.y));
  }, []);

  const end = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const from = origin.current;
      origin.current = null;
      setDragging(false);
      // Home either way: on a release that closes, the sheet unmounts a frame
      // later and would otherwise reopen displaced the next time.
      setDy(0);
      if (!from) return;
      try {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      } catch {
        /* already released, which is the state we wanted anyway */
      }
      const travelled = event.clientY - from.y;
      if (travelled < DEADZONE) return;
      const elapsed = Math.max(1, event.timeStamp - from.at);
      if (travelled >= COMMIT || travelled / elapsed >= ESCAPE_VELOCITY) onDismiss();
    },
    [onDismiss],
  );

  return {
    dy,
    dragging,
    // `onPointerCancel` matters on iOS: the system steals the pointer for its
    // own edge gestures, and without this the sheet would stay where the finger
    // left it with no way back.
    bind: { onPointerDown, onPointerMove, onPointerUp: end, onPointerCancel: end },
  };
}
