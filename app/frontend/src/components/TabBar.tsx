import { type CSSProperties, type MouseEvent, type PointerEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { navStroke } from "./ui";

/** One tab: the faces `NAV` in `Layout.tsx` gives both of its renders. */
export type TabItem = {
  to: string;
  label: string;
  /** The section's gradient, clipped to the label's glyphs. */
  text: string;
  /** The same ramp as an SVG paint-server id, for the icon's stroke. */
  gradient: string;
  icon: ReactNode;
};

/**
 * How many applications are waiting on a reply.
 *
 * Deliberately not `Badge`: this sits inside a nav pill, and a badge with its
 * own background would be a second chip inside a chip.
 *
 * One neutral disc, on every surface it can land on — the section's colour
 * would say "Tracker" where it means "someone owes you a reply".
 *
 * `decorative` is the copy inside the tab bar's lens. It has to take exactly the
 * room the real one takes, or the magnified row stops lining up with the row
 * under it, but it must not be a second "3" to a screen reader or to a test
 * looking for the count — so the number is drawn by CSS from an attribute
 * rather than written as text.
 */
export function DueCount({ count, decorative = false }: { count: number; decorative?: boolean }) {
  const shape =
    "ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full bg-ink-900/10 px-1.5 py-0.5 text-xs font-semibold leading-none text-ink-700 dark:bg-white/15 dark:text-ink-100";
  if (decorative) {
    return <span data-count={count} className={`${shape} before:content-[attr(data-count)]`} />;
  }
  return (
    <span
      title={`${count} application${count === 1 ? "" : "s"} with no reply — the follow-up email is waiting on the Tracker`}
      className={shape}
    >
      {count}
    </span>
  );
}

// A press that travels further than this is a drag: the lens follows the finger
// and the tab is chosen where it is let go, rather than where it went down.
const DRAG_SLOP = 6;

// How long a drag's first move glides to the finger before the lens locks on
// to it. It starts over the tab it was resting on, up to half a tab away from
// the finger, and snapping that gap in one frame reads as a jump. Matches the
// lifted `--lens-slide` in `index.css`.
const CATCH_UP_MS = 180;

// The click a browser fires after a pointer sequence arrives within a frame or
// two of `pointerup`. Anything later is a keyboard's, and belongs to the link.
const CLICK_AFTER_POINTER_MS = 500;

/**
 * The phone's tab bar, drawn after iOS 26's.
 *
 * **One pill, not one per tab.** The selection is a single element that slides
 * between the tabs, which is what lets it *travel* when the tab changes rather
 * than disappear from one and appear on the other. Its position is one number,
 * `--lens-pos` — the index it sits over, fractional under a finger — and
 * `index.css` turns it into a `translate` the compositor animates, so the slide
 * does not stall while the main thread renders the page it is sliding to.
 *
 * **Under a finger it becomes a lens.** Pressing lifts the pill into a larger,
 * clearer piece of glass that overhangs the bar, follows the finger, and settles
 * on the tab it is let go over. What makes it read as a lens and not as a bigger
 * pill is what is *inside* it: a second copy of the row, drawn in every tab's
 * selected colours and aligned exactly with the real one, which the pill clips.
 * At rest that copy is the selected tab's colour showing through the pill; lifted,
 * the pill's `scale` magnifies it about the lens's centre — the icons swell and
 * take their tint as the lens passes over them, which is the effect in Apple's
 * own bar. A page cannot sample and bend what is behind it in Safari (see
 * `.glass-refract`), but it can magnify what it drew itself.
 *
 * Navigation on a pointer is done here rather than by the link's click, because
 * the lens decides the tab — a drag that ends over Tracker goes to Tracker,
 * whichever link it started on — and the click that follows is swallowed. A
 * keyboard's click has no pointer sequence in front of it and reaches the link
 * untouched.
 *
 * **The colour lives only in the pill.** The real row is always plain ink; the
 * tint on the selected tab is the copy showing through the pill, so when the
 * pill slides the colour travels with it, a wipe rather than a swap. The real
 * face under a resting pill fades out (`data-covered`) so its ink does not
 * fringe the tinted copy drawn over it. It follows the pill's destination, not
 * the route, so it starts fading on the tap rather than when the page arrives.
 * The first cut tinted the real row from the route, and the new tab snapped
 * to colour mid-slide while the old one snapped to ink.
 *
 * The route changes two frames *after* the pill is told to move. Mounting a
 * page is the heaviest thing this app does on a tap, and done in the same task
 * it delays the first frame of the slide by however long the render takes —
 * the lag the first cut had. Two frames in, the slide is already running on
 * the compositor and the render cannot hold it up.
 */
export function TabBar({
  items,
  setupComplete,
  dueCount,
}: {
  items: TabItem[];
  setupComplete: boolean;
  dueCount: number;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const rowRef = useRef<HTMLDivElement>(null);
  const press = useRef<{ x: number; dragged: boolean } | null>(null);
  const catchUp = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastPointerUp = useRef(0);

  // Where the lens is while a finger holds it, as a fractional tab index.
  const [lens, setLens] = useState<number | null>(null);
  // Past the slop: the lens tracks the finger with no easing at all.
  const [dragging, setDragging] = useState(false);
  // The tab a release chose, held until the route catches up — otherwise the
  // pill sets off back to the old tab for the frame before it turns around.
  const [chosen, setChosen] = useState<number | null>(null);

  const active = items.findIndex(
    (item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`),
  );

  useEffect(() => setChosen(null), [location.pathname]);
  useEffect(() => () => clearTimeout(catchUp.current), []);

  const position = lens ?? chosen ?? active;

  /** The fractional tab index under a point, clamped to the row. */
  const indexAt = (clientX: number): number | null => {
    const row = rowRef.current;
    if (!row) return null;
    const box = row.getBoundingClientRect();
    if (box.width === 0) return null;
    const style = getComputedStyle(row);
    const left = box.left + (parseFloat(style.paddingLeft) || 0);
    const width = box.width - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0);
    const raw = ((clientX - left) / width) * items.length - 0.5;
    return Math.min(items.length - 1, Math.max(0, raw));
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const at = indexAt(event.clientX);
    if (at === null) return;
    press.current = { x: event.clientX, dragged: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    // Lift in place. A press on the *other* tab used to send the lens there at
    // once, on the lifted curve, so a tap spent its whole slide in 0.18 s while
    // the finger was still down, and the slow slide never ran. The lens only
    // leaves its tab once the finger actually drags; a tap slides on release.
    setLens(position >= 0 ? position : at);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = press.current;
    if (!current) return;
    if (!current.dragged) {
      if (Math.abs(event.clientX - current.x) <= DRAG_SLOP) return;
      current.dragged = true;
      catchUp.current = setTimeout(() => setDragging(true), CATCH_UP_MS);
    }
    const at = indexAt(event.clientX);
    if (at !== null) setLens(at);
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (!press.current) return;
    press.current = null;
    lastPointerUp.current = event.timeStamp || performance.now();
    const at = indexAt(event.clientX) ?? lens;
    setLens(null);
    clearTimeout(catchUp.current);
    setDragging(false);
    if (at === null) return;
    const target = Math.round(at);
    setChosen(target);
    if (target === active) return;
    const to = items[target].to;
    requestAnimationFrame(() => requestAnimationFrame(() => navigate(to)));
  };

  const onPointerCancel = () => {
    press.current = null;
    setLens(null);
    clearTimeout(catchUp.current);
    setDragging(false);
  };

  const onClickCapture = (event: MouseEvent) => {
    // `detail` is 0 for a click synthesised from Enter or Space.
    if (event.detail === 0) return;
    const since = (event.timeStamp || performance.now()) - lastPointerUp.current;
    if (since >= 0 && since < CLICK_AFTER_POINTER_MS) event.preventDefault();
  };

  const face = (item: TabItem, lit: boolean, decorative: boolean) => (
    <>
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-6 w-6"
        fill="none"
        stroke={lit ? navStroke(item.gradient) : "currentColor"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {item.icon}
      </svg>
      <span className="flex items-center">
        <span className={lit ? item.text : undefined}>{item.label}</span>
        {item.to === "/tracker" && dueCount > 0 && <DueCount count={dueCount} decorative={decorative} />}
      </span>
    </>
  );

  const cell = "tabbar-cell flex flex-col items-center justify-center gap-0.5 rounded-full px-2 text-[11px] font-semibold tracking-tight";

  return (
    <nav className="tabbar-dock tabbar glass w-fit mx-auto rounded-full sm:hidden" aria-label="Main">
      <div
        ref={rowRef}
        className="tabbar-row"
        style={{ "--tab-count": items.length } as CSSProperties}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onClickCapture={onClickCapture}
      >
        <span
          className="tabbar-lens"
          data-lifted={lens !== null ? "" : undefined}
          data-dragging={dragging ? "" : undefined}
          data-hidden={position < 0 ? "" : undefined}
          style={{ "--lens-pos": Math.max(position, 0) } as CSSProperties}
          aria-hidden="true"
        >
          <span className={`tabbar-lens-row ${setupComplete ? "" : "opacity-40"}`}>
            {items.map((item) => (
              <span key={item.to} className={cell}>
                {face(item, true, true)}
              </span>
            ))}
          </span>
        </span>

        {items.map((item, index) => (
          <NavLink
            key={item.to}
            to={item.to}
            title={setupComplete ? undefined : "Finish your account setup first"}
            draggable={false}
            data-covered={lens === null && index === position ? "" : undefined}
            className={`${cell} text-ink-800 dark:text-ink-100 ${setupComplete ? "" : "opacity-40"}`}
          >
            {face(item, false, false)}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
