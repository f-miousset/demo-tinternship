import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { useFollowUps } from "../lib/followUps";
import type { AppConfig } from "../lib/types";
import { useOnline } from "../lib/useOnline";
import { useScrolled } from "../lib/useScrolled";
import ParticleWordmark from "./ParticleWordmark";
import { DueCount, TabBar } from "./TabBar";
import { ThemeButton } from "./ThemeSwitch";
import { Badge, CORNER_BUTTON, NAV_GRADIENT, NavGradients, navStroke } from "./ui";

// Jobs and Tracker are the two halves of the app, not an ordered walkthrough —
// each gets its own colour so you can aim at one without reading the label. On a
// phone they are the bottom tab bar, which is the same claim made in the shape a
// thumb can act on.
//
// **The selected one is never a fill.** In the header it is a halo —
// a sibling app's shape: a raised neutral surface with the section's colour left to a
// soft glow around it and to the icon and the label. In the phone's tab bar it
// is iOS 26's sliding neutral pill (`TabBar.tsx`), with no glow. Either way the
// gradient is worn by the icon and the label, never by the pill: a pill filled
// with it was the heaviest object in either bar, and it said "button" where it
// means "you are here".
//
// Both renders — the header's segmented control and the phone's tab bar — read
// the same faces, which is what keeps them one control rather than two with
// their own habits. `selected` is the header's alone. `text` clips the
// gradient to the glyphs; `icon` is a stroke and cannot read a CSS background,
// so it takes the same ramp from `NavGradients` in `ui.tsx`.
const NAV = [
  {
    to: "/jobs",
    label: "Jobs",
    selected: "nav-selected nav-flame",
    text: "brand-text",
    gradient: NAV_GRADIENT.flame,
    // A magnifier rather than the briefcase this tab used to show: the briefcase
    // is the app's own mark now, sitting in the header two centimetres away, and
    // searching is what this screen actually does.
    icon: (
      <>
        <circle cx="11" cy="11" r="6.5" />
        <path d="m16 16 4 4" />
      </>
    ),
  },
  {
    to: "/tracker",
    label: "Tracker",
    selected: "nav-selected nav-track",
    text: "track-text",
    gradient: NAV_GRADIENT.track,
    icon: (
      <>
        <path d="M4 6h.01M4 12h.01M4 18h.01" />
        <path d="M9 6h11M9 12h11M9 18h11" />
      </>
    ),
  },
];

// The unselected half of the header's switch. Plain faint ink and no fill at
// all: the selected tab is a translucent surface rather than a solid colour, so
// a tinted pill beside it would be a second object of the same weight in the
// same colour family. The phone's tab bar draws its idle tabs in full ink
// instead, as iOS does — there the sliding pill carries the selection, not the
// contrast between the two.
const NAV_IDLE =
  "text-ink-500 hover:text-ink-800 dark:text-ink-400 dark:hover:text-ink-100";

// Neither of these is a step of the workflow — you never have to visit one to
// apply anywhere. Account is the one-time setup (profile, interview, brief,
// playbook);
// Settings is the "what is this thing doing" screen, and it is where Traces
// hangs off from. They stay small, and stay out of the bottom bar.
const UTILITY_NAV = [
  {
    to: "/account",
    label: "Account",
    title: "Your profile, search brief and hiring playbook",
    icon: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5.5 20c0-3.4 2.9-5.8 6.5-5.8s6.5 2.4 6.5 5.8" />
      </>
    ),
  },
  {
    to: "/settings",
    label: "Settings",
    title: "Settings, traces and data reset",
    // Sliders rather than a gear: at 20px a gear's teeth collapse into a blob,
    // and the app's own mark two centimetres away is already a shape with a
    // silhouette to remember. Two rows read at any size.
    icon: (
      <>
        <path d="M4 8h8M16.5 8H20M4 16h4.5M13 16h7" />
        <circle cx="14.25" cy="8" r="2.25" />
        <circle cx="10.75" cy="16" r="2.25" />
      </>
    ),
  },
];

/**
 * Reachable before the account setup is finished.
 *
 * Account itself, plus the two screens you might need in order to *fix* a
 * failing setup: Settings says whether the API key is even configured, and
 * Traces says why a run fell over. Everything else waits.
 */
const OPEN_WHILE_INCOMPLETE = /^\/(account|settings|traces)(\/|$)/;

export function Layout() {
  const location = useLocation();
  const online = useOnline();
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/api/config"),
    refetchInterval: 30_000,
  });

  // Undefined until /api/config answers — assume complete until told otherwise,
  // so a first paint never flashes the Account page at someone who is set up.
  const setupComplete = config?.progress.complete ?? true;
  const gated = !setupComplete && !OPEN_WHILE_INCOMPLETE.test(location.pathname);

  // Applications nobody answered. This is the whole notification on a device
  // that will not raise a system one — a count on the tab that leads to the
  // panel — so it rides both copies of NAV rather than only the desktop row.
  const { data: followUps } = useFollowUps();
  const dueCount = followUps?.follow_ups.length ?? 0;

  // A new screen starts at its own top, so the header starts merged. The page
  // itself is the scroller — the shell does not nest one — so this is the
  // window's offset and nothing else's, and it is only worth touching when the
  // window is actually somewhere else.
  useEffect(() => {
    if (window.scrollY !== 0) window.scrollTo(0, 0);
  }, [location.pathname]);

  // Which of the header's two phone shapes to wear. Nothing has scrolled under
  // it yet, so it is still part of the top of the screen rather than a layer
  // floating above the page. Above `sm` the attribute is inert — the CSS that
  // reads it lives inside a `max-width: 639px` query.
  const merged = !useScrolled();

  return (
    <div className="flex min-h-dvh flex-col">
      <NavGradients />
      {/* A card floating clear of all four edges rather than a bar welded to
          the top one — the same object the tab bar is, at the other end of the
          screen, and docked on the same insets by `.header-dock`. It is
          `.glass-heavy` rather than `.glass` because it is the one surface with
          body text scrolling *underneath* it: at 62% the words stayed legible
          through the pane, which reads as a rendering fault rather than as
          depth. See documentation/design-language.md for which surfaces may
          wear either.

          Two elements rather than one: `.header-dock` is the sticky box and
          `.header-pane` the glass inside it, which is what lets a phone merge
          the card into the top edge — the float moves from the dock's padding
          to the pane's, so the shell never changes height while the shape does.
          `data-merged` is the switch, and it is only read below `sm`.

          `overflow-hidden` so the strips below the row clip to the radius, and
          `relative z-10` on the content because `.glass-heavy`'s sheen paints
          above the pane and would otherwise wash across the top of the row. */}
      <header className="header-dock" data-merged={merged ? "" : undefined}>
        <div className="header-pane glass-heavy squircle overflow-hidden rounded-sheet">
          <div className="relative z-10">
            <div className="gutter relative flex h-14 items-center gap-3">
              <div className="flex shrink-0 items-center gap-2">
                {/* The icon file itself, not a copy of it: the mark in the header and
                    the mark on the home screen are then the same drawing, and it is
                    already in the browser's cache as the favicon. */}
                <img src="/favicon.svg" alt="" className="h-7 w-7 shrink-0 rounded-lg" />
                {/* The wordmark gathers out of a field of particles on load and on a
                    tap; under reduced motion it is the plain gradient text. */}
                <ParticleWordmark text="Tinternship" className="text-2xl font-extrabold tracking-tighter" />
              </div>

              {/* The two main screens, as one segmented control on a recessed
                  track — the macOS shape, which states that these are the two
                  positions of a single switch rather than two of the several
                  things in the bar. Centred against the row and not against the
                  card, because the card grows downward when a strip appears and
                  the switch must not drift with it.

                  A translucent fill, never a second `.glass`: a backdrop filter
                  nested inside another one costs a full recomposite of the pane
                  behind it every frame, for a difference nobody can see at this
                  size.

                  Desktop segmented control geometry:
                  outer track has `rounded-xl` (12px) with 4px padding (`p-1`),
                  and inner segment buttons have `rounded-lg` (8px) for exact
                  concentric curvature (12px − 4px = 8px).

                  Below `sm` this is the floating dock at the bottom of the
                  screen; up here it would cost a third of a small viewport's
                  height before any content. */}
              <nav
                className="absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 items-center gap-1 rounded-xl border border-ink-900/10 bg-ink-900/5 p-1 sm:flex dark:border-white/10 dark:bg-white/5"
                aria-label="Main"
              >
                {NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    title={setupComplete ? undefined : "Finish your account setup first"}
                    className={({ isActive }) =>
                      `inline-flex items-center gap-1.5 rounded-lg border border-transparent px-3 py-1.5 text-sm font-semibold tracking-tight transition ${
                        isActive ? item.selected : NAV_IDLE
                      } ${setupComplete ? "" : "opacity-40"}`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <svg
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                          className="h-4 w-4"
                          fill="none"
                          stroke={isActive ? navStroke(item.gradient) : "currentColor"}
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          {item.icon}
                        </svg>
                        {/* The gradient is clipped to the glyphs, so the label
                            needs its own box — a span around the badge as well
                            would clip that to nothing too. */}
                        <span className={isActive ? item.text : undefined}>{item.label}</span>
                        {item.to === "/tracker" && dueCount > 0 && <DueCount count={dueCount} />}
                      </>
                    )}
                  </NavLink>
                ))}
              </nav>

              {/* Round 44px targets in the corner both reference headers keep for
                  their one utility control. Icon-only is what buys the segmented
                  control the middle of a 375px row; the label survives as the
                  accessible name and as the tooltip, and neither of the two
                  links is a screen you navigate to by reading the bar — Account
                  is visited once, and the setup strip below links to it by name
                  until it is.

                  Three of them now, and the first is not a link at all: the
                  theme cycles in place. It leads the cluster so that adding it
                  moved nothing — Account and Settings keep their distance from
                  the right edge, which is the edge a thumb measures from. It
                  earns a corner despite the row being the tightest 56px in the
                  app because it is the one control here you reach for *because
                  of where you are* — a train at night — rather than once, and
                  Settings → Appearance is two taps and a scroll away. Measured
                  at 375px: the row's 319px of content carries a 125px wordmark
                  and a 140px cluster, so the third button spends 48 of the 101
                  that were spare and the capsule stays exactly 56px tall.

                  **All three wear the flame and take the same halo** — on
                  hover, on focus, and for the two links on their own page — with
                  the brand ramp on the icon at all times, which is what a phone
                  gets instead of a hover. `CORNER_BUTTON` in `ui.tsx` is the one
                  copy of that, worn here and by `ThemeButton`, because three
                  round buttons in one cluster that drift apart is three round
                  buttons that stop reading as a set. */}
              <div className="ml-auto flex shrink-0 items-center gap-1">
                <ThemeButton />
                {UTILITY_NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    title={item.title}
                    aria-label={item.label}
                    className={CORNER_BUTTON}
                  >
                    <svg
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                      className="h-5 w-5"
                      fill="none"
                      stroke={navStroke(NAV_GRADIENT.flame)}
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      {item.icon}
                    </svg>
                  </NavLink>
                ))}
              </div>
            </div>

            {/* Everything on every screen is a view of data the API holds, so one
                honest badge beats the same fetch error repeated five times.
                Which model runs, which job boards are wired up and whether Canva
                is connected are all settled once and then true forever — Settings
                is where you go to read them. Only the broken cases earn header
                space.

                They sit on their own strip rather than in the row because the row
                is a fixed 56px capsule at every width, and that is what makes it
                read as one floating object; two badges squeezed in beside the
                wordmark on a 375px screen would break it. */}
            {(!online || (config && !config.gemini_configured)) && (
              <div className="gutter flex flex-wrap items-center gap-2 border-t border-ink-900/10 py-2 dark:border-white/10">
                {!online && (
                  <Badge tone="warn" title="Nothing will load until the connection is back">
                    offline
                  </Badge>
                )}
                {config && !config.gemini_configured && (
                  <Badge tone="bad" title="Set GOOGLE_API_KEY — no agent can run without it">
                    no API key
                  </Badge>
                )}
              </div>
            )}

            {!setupComplete && (
              <div className="gutter flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-accent-500/30 bg-accent-500/10 py-2 text-xs">
                <span className="text-ink-700 dark:text-ink-200">
                  Your account setup is not finished — the agents have no profile, brief or playbook
                  to work from yet.
                </span>
                <NavLink to="/account" className="font-medium text-accent-700 underline dark:text-accent-400">
                  Finish it →
                </NavLink>
              </div>
            )}

            {config?.warnings?.length ? (
              /* One unresolvable dependency can be a paragraph long, and four of
                 them would be the whole of a phone screen before any content.
                 They scroll in place there instead of pushing the app down.

                 A translucent amber wash rather than the solid `amber-50` this
                 used to be: an opaque slab inside the card would cut it in two,
                 and the strip is part of the same piece of glass as the row. */
              <ul className="gutter max-h-24 space-y-0.5 overflow-y-auto border-t border-amber-500/30 bg-amber-500/10 py-2 text-xs text-amber-900 sm:max-h-none sm:overflow-visible dark:text-amber-300">
                {config.warnings.map((warning) => (
                  <li key={warning}>· {warning}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      </header>

      {/* The document is the scroller, deliberately: a `<main>` with its own
          `overflow-y-auto` inside a `100dvh` shell stops the URL bar collapsing
          on iOS and hands the header a bounce the page never has.
          `min-h-[calc(100lvh-var(--header-float,4rem))]` on phones keeps the
          scroller tall enough so Safari never forces its bottom toolbar open on
          short pages (like Jobs with an empty deck), keeping the dock pinned at
          the identical level across all routes. */}
      <main className="gutter pb-tabbar mx-auto w-full max-w-6xl flex-1 pt-5 sm:pt-6 min-h-[calc(100lvh-var(--header-float,4rem))] sm:min-h-0">
        {gated ? <Navigate to="/account" replace /> : <Outlet />}
      </main>

      {/* Floated off the bottom edge rather than welded to it: that is what
          makes it read as a layer above the deck rather than as frame. The
          three insets that dock it are `.tabbar-dock` in index.css, because the
          "+" button's offset is measured from the same numbers.

          Drawn after iOS 26's tab bar — one sliding pill that lifts into a lens
          under a finger — and explained in `TabBar.tsx`. Still `.glass` and not
          the header's `.glass-heavy`: this is the one pane with a card being
          dragged at 60fps directly beneath it. */}
      <TabBar items={NAV} setupComplete={setupComplete} dueCount={dueCount} />
    </div>
  );
}
