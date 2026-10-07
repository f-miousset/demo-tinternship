import { useEffect, useState } from "react";

/**
 * Whether the page has been scrolled off its own top.
 *
 * The header is two shapes on a phone — a slab merged into the top edge while
 * you are at the top of the page, a floating capsule once anything has passed
 * underneath it — and this is the switch between them. See
 * `documentation/design-language.md` § *The header merges with the top edge…*.
 *
 * Two details are load-bearing:
 *
 * - **The threshold is not zero.** `index.css` stops the viewport bouncing at
 *   all (`overscroll-behavior-y: none`), so on a current engine nothing ever
 *   drags the page past its own top — but that property wants Safari 16, and on
 *   an engine without it a rubber-band still leaves `scrollY` a hair positive on
 *   the way back. A header that detached and re-merged on every bounce would be
 *   a flicker rather than a transition, so the guard stays.
 * - **The read is deferred to the next frame.** `scroll` fires far faster than
 *   the compositor paints, and a `setState` per event on a phone mid-flick is
 *   the one place this cheap listener could cost a frame.
 *
 * It knows nothing about *overscroll*, and that is a decision rather than an
 * omission: five attempts at holding or filling the strip a rubber-band opens
 * above the merged slab all failed, and the whole apparatus was removed. The
 * sixth answer was one line of CSS that opens no strip to fill. See
 * `documentation/decisions.md` § *Dragging past the top is not ours to chase*
 * before writing a seventh.
 */
export function useScrolled(threshold = 6): boolean {
  const [scrolled, setScrolled] = useState(() => window.scrollY > threshold);

  useEffect(() => {
    let frame = 0;

    const read = () => {
      frame = 0;
      setScrolled(window.scrollY > threshold);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };

    // The page may already be scrolled on mount — a reload part-way down a
    // list restores the offset before React ever runs.
    read();
    window.addEventListener("scroll", onScroll, { passive: true });
    // A route change can shorten the page under a scrolled viewport; the
    // browser clamps the offset without always firing `scroll` for it.
    window.addEventListener("resize", onScroll, { passive: true });

    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [threshold]);

  return scrolled;
}
