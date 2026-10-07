import { useCallback, useRef, useState } from "react";

/**
 * Dragging one card, in four directions.
 *
 * Hand-rolled on Pointer Events rather than pulling in a gesture library, for
 * the same reason the SSE parser and the service worker here are hand-rolled:
 * the whole behaviour is fifty lines, and a dependency in this position is one
 * more thing Renovate offers a major of.
 *
 * Pointer Events rather than touch + mouse: one code path covers finger, mouse
 * and pen, and `setPointerCapture` means a drag that leaves the card still ends
 * on it — without it, flicking a card off the screen loses the `pointerup` and
 * the card stays stuck mid-flight.
 */
export type SwipeDirection = "left" | "right" | "up" | "down";

/** Below this, a drag is a tap that wandered. */
const DEADZONE = 12;

/**
 * How far a card must travel to count as a decision.
 *
 * A fraction of the card so the gesture feels the same on a phone and on a
 * laptop, capped so a wide card does not demand an arm movement.
 */
function commitDistance(width: number): number {
  return Math.min(90, Math.max(48, width / 3));
}

/** A fast flick counts even when it is short: px per ms. */
const ESCAPE_VELOCITY = 0.6;

export interface SwipeState {
  dx: number;
  dy: number;
  /** The direction this drag would commit to right now, or null while inside the deadzone. */
  direction: SwipeDirection | null;
  dragging: boolean;
  /** 0–1, how close this drag is to committing. Drives the stamp's opacity. */
  progress: number;
}

const IDLE: SwipeState = { dx: 0, dy: 0, direction: null, dragging: false, progress: 0 };

/**
 * The axis a drag is on.
 *
 * Whichever offset is larger wins outright rather than being blended: a card
 * being pulled diagonally has to resolve to one of four answers, and a
 * threshold that let both axes count would fire two decisions at once.
 */
function axisOf(dx: number, dy: number): SwipeDirection {
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? "right" : "left";
  return dy > 0 ? "down" : "up";
}

export function useSwipe(onCommit: (direction: SwipeDirection) => void) {
  const [state, setState] = useState<SwipeState>(IDLE);
  // A ref, not state: it is read inside the move handler on every frame and
  // re-rendering to store the origin would fight the drag it is measuring.
  const origin = useRef<{ x: number; y: number; at: number; width: number } | null>(null);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLElement>) => {
    // Only the primary button. A right-click drag is a context menu, not a swipe.
    if (event.pointerType === "mouse" && event.button !== 0) return;
    origin.current = {
      x: event.clientX,
      y: event.clientY,
      at: event.timeStamp,
      width: event.currentTarget.getBoundingClientRect().width,
    };
    // Capture is an optimisation — it keeps a fast flick that leaves the card
    // reporting to it — and it throws `NotFoundError` when the pointer id is no
    // longer active, which a fast release can produce. Losing the whole drag
    // over it would be the wrong trade.
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* the drag works without it; only a pointer that leaves the card is lost */
    }
    setState({ ...IDLE, dragging: true });
  }, []);

  const onPointerMove = useCallback((event: React.PointerEvent<HTMLElement>) => {
    const from = origin.current;
    if (!from) return;
    const dx = event.clientX - from.x;
    const dy = event.clientY - from.y;
    const travelled = Math.hypot(dx, dy);
    const direction = travelled < DEADZONE ? null : axisOf(dx, dy);
    const reach = direction === "left" || direction === "right" ? Math.abs(dx) : Math.abs(dy);
    setState({
      dx,
      dy,
      direction,
      dragging: true,
      progress: direction ? Math.min(1, reach / commitDistance(from.width)) : 0,
    });
  }, []);

  const end = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const from = origin.current;
      origin.current = null;
      setState(IDLE);
      if (!from) return;
      try {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      } catch {
        /* already released, which is the state we wanted anyway */
      }
      const dx = event.clientX - from.x;
      const dy = event.clientY - from.y;
      if (Math.hypot(dx, dy) < DEADZONE) return;

      const direction = axisOf(dx, dy);
      const reach = direction === "left" || direction === "right" ? Math.abs(dx) : Math.abs(dy);
      const elapsed = Math.max(1, event.timeStamp - from.at);
      if (reach >= commitDistance(from.width) || reach / elapsed >= ESCAPE_VELOCITY) {
        onCommit(direction);
      }
    },
    [onCommit],
  );

  return {
    ...state,
    // `onPointerCancel` matters on iOS: the system steals the pointer for its
    // own edge gestures, and without this the card would stay where the finger
    // left it with no way back.
    bind: { onPointerDown, onPointerMove, onPointerUp: end, onPointerCancel: end },
  };
}
