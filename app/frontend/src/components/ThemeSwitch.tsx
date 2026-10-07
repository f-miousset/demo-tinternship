import type { ReactNode } from "react";

import { GLASS, type ThemeChoice, useTheme } from "../lib/theme";
import { CORNER_BUTTON, NAV_GRADIENT, navStroke } from "./ui";

/**
 * The appearance controls: the theme, in its two shapes, and the glass.
 *
 * `ThemeSwitch` is the three-position segmented control on the Settings page —
 * the whole state, visible at once. `ThemeButton` is the round icon in the
 * header's corner, which is the same three positions cycled one tap at a time.
 *
 * They live in one file because they must not drift: the same icons, the same
 * labels and the same order, or the header shows a shape the Settings page
 * never taught you. `GlassSlider` joins them because it is the other half of
 * the same card and reads the same store.
 */

/**
 * Three positions, in the order they escalate: follow the device, then override
 * it one way, then the other. `System` first because it is the default and the
 * one most people should stay on — a phone that dims itself at sunset is doing
 * a better job than a preference set once in June.
 *
 * The order is also the header button's cycle, so tapping it walks the switch
 * left to right and wraps. That is the whole reason the two shapes can coexist:
 * the button is not a different control, it is this one operated blind.
 */
const THEME_OPTIONS: { value: ThemeChoice; label: string; hint: string; icon: ReactNode }[] = [
  {
    value: "system",
    label: "System",
    hint: "Follow the device, including its own night schedule",
    // A monitor rather than the half-filled circle iOS uses for "Automatic".
    // The circle is a shape you have to be told the meaning of, and in the
    // header this icon has to answer "what is the app doing" on sight, with no
    // label anywhere near it.
    icon: (
      <>
        <rect x="3" y="4" width="18" height="12.5" rx="2.5" />
        <path d="M9 20.5h6M12 16.5v4" />
      </>
    ),
  },
  {
    value: "light",
    label: "Light",
    hint: "Always light, whatever the device is doing",
    icon: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    hint: "Always dark, whatever the device is doing",
    icon: <path d="M20 14.6A8.6 8.6 0 0 1 9.4 4 8.6 8.6 0 1 0 20 14.6Z" />,
  },
];

/**
 * The same stroke geometry every icon in this app uses.
 *
 * `stroke` is a parameter because the two shapes below paint differently: the
 * Settings switch draws three of these inside one control, where the ink says
 * which segment is selected, while the header's button is a lone drawing in a
 * corner and wears the brand ramp like its two neighbours.
 */
function ThemeIcon({
  choice,
  className,
  stroke = "currentColor",
}: {
  choice: ThemeChoice;
  className: string;
  stroke?: string;
}) {
  const option = THEME_OPTIONS.find((candidate) => candidate.value === choice) ?? THEME_OPTIONS[0];
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke={stroke}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {option.icon}
    </svg>
  );
}

/**
 * The appearance control on the Settings page: a three-position segmented
 * switch.
 *
 * Real radio inputs under `sr-only`, not buttons with `aria-checked`. Three
 * radios sharing a name get the keyboard behaviour for free — arrows move the
 * selection, the group is one tab stop — and a screen reader announces
 * "2 of 3" without any of it being written here. The visible pill is the
 * `peer-checked:` sibling.
 *
 * The geometry is the header's segmented control, deliberately: the same
 * recessed track saying "these are the positions of one switch", with concentric
 * geometry: `rounded-xl` (12px) track and `rounded-lg` (8px)
 * segment pills (12px − 4px = 8px). See documentation/design-language.md § the
 * header states one choice.
 *
 * What it does not borrow is the flame: the selected pill is a raised neutral
 * surface. Flame and teal mean Jobs and Tracker in this app, and a gradient
 * here would say this control navigates somewhere.
 */
export function ThemeSwitch() {
  const { choice, setChoice } = useTheme();

  return (
    <div
      className="grid w-full grid-cols-3 gap-1 rounded-xl border border-ink-900/10 bg-ink-900/5 p-1 sm:w-auto dark:border-white/10 dark:bg-white/5"
      role="radiogroup"
      aria-label="Theme"
    >
      {THEME_OPTIONS.map((option) => (
        <label key={option.value} title={option.hint} className="cursor-pointer">
          <input
            type="radio"
            name="theme"
            value={option.value}
            checked={choice === option.value}
            onChange={() => setChoice(option.value)}
            className="peer sr-only"
          />
          <span
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-semibold tracking-tight text-ink-600 transition peer-focus-visible:ring-2 peer-focus-visible:ring-accent-500 peer-checked:bg-white peer-checked:text-ink-900 peer-checked:shadow-sm sm:min-h-9 dark:text-ink-400 dark:peer-checked:bg-ink-700 dark:peer-checked:text-ink-50"
          >
            <ThemeIcon choice={option.value} className="h-4 w-4 shrink-0" />
            {option.label}
          </span>
        </label>
      ))}
    </div>
  );
}

/**
 * How much of the page shows through the glass, from none of it to all of it.
 *
 * **Both ends are real.** At 0% the panes are solid; at 100% there is no pane —
 * the blur, the tint, the rim and the sheen go with the colour, so the header
 * becomes its own controls floating over the page you are reading. Neither end
 * is a state the design would pick, and picking is not the design's to do.
 *
 * **The slider counts transparency, the store counts opacity**, and the
 * inversion is deliberate rather than an oversight: a control labelled
 * "transparency" whose number fell as you dragged right would be read as broken
 * by everyone who has ever used a volume slider. `--glass-alpha` stays the
 * opacity because that is what `rgb()` wants, so the conversion happens here, at
 * the one place a human looks at the number.
 *
 * It moves **both grades at once**. `.glass-heavy` — the header, the one pane
 * with text scrolling under it — is derived in CSS as a notch above whatever
 * this sets, so the rule that it is the more opaque of the two survives
 * wherever the slider is left. Two sliders would let a user invert that and
 * make the header the *thinner* surface, which is the one arrangement the
 * design has no answer for.
 *
 * There is no live preview to build: the header and the tab bar are on screen
 * while you drag, and the variable they derive from is the one this writes.
 */
export function GlassSlider() {
  const { glass, setGlass } = useTheme();

  // Both ends come from the store's range, so the track cannot offer a value
  // the setter would clamp away.
  const asPercent = (alpha: number) => Math.round((1 - alpha) * 100);
  const transparency = asPercent(glass);

  return (
    <label className="flex items-center gap-3" title="How much of the page shows through the header, the tab bar and the sheets">
      <span className="w-28 shrink-0 text-xs text-ink-500 dark:text-ink-400">
        Transparency{" "}
        <span className="font-semibold tabular-nums text-ink-700 dark:text-ink-200">
          {transparency}%
        </span>
      </span>
      <input
        type="range"
        aria-label="Glass transparency"
        min={asPercent(GLASS.max)}
        max={asPercent(GLASS.min)}
        step={GLASS.step * 100}
        value={transparency}
        onChange={(event) => setGlass(1 - Number(event.target.value) / 100)}
        className="h-11 w-full accent-accent-600 sm:h-9 sm:w-48"
      />
    </label>
  );
}

/**
 * The same control in the header's corner: one round 44px button that walks the
 * three positions and wraps.
 *
 * **A cycle rather than a menu**, because the corner has room for one 44px
 * target and not for a popover — and because the state it would show you is
 * already on the button. The icon *is* the readout: monitor, sun or moon says
 * which position you are on, and the label says which one the next tap lands
 * on. The Settings switch remains the place to see all three at once and pick
 * one directly.
 *
 * It sits at the **left** of the corner cluster, which is the only place it
 * could go without moving something: Account and Settings keep their distance
 * from the right edge, and a thumb that already knows where Settings is is
 * still right.
 *
 * **It is drawn like its two neighbours** — `CORNER_BUTTON`, so the brand ramp
 * at rest and the selected tab's halo on hover or focus. Three round buttons in
 * one cluster that drift apart stop reading as a set, and the shape is what says
 * "corner control" while the icon says which one.
 *
 * A `<button>` and not a `NavLink` all the same, and the one part of the scheme
 * it cannot wear is the one that comes from being a link: `.nav-lit` lights
 * `[aria-current="page"]`, and this goes nowhere to be current on. It lights
 * under the pointer and under the keyboard, and the rest of the time its icon —
 * monitor, sun, moon — is the readout.
 */
export function ThemeButton() {
  const { choice, theme, setChoice } = useTheme();

  const index = THEME_OPTIONS.findIndex((option) => option.value === choice);
  const current = THEME_OPTIONS[index] ?? THEME_OPTIONS[0];
  const next = THEME_OPTIONS[(index + 1) % THEME_OPTIONS.length];

  // `System` names what it follows rather than what it is, so the label says
  // what that came out as — otherwise the one position whose meaning changes
  // under you is the one that tells you least.
  const label =
    current.value === "system"
      ? `Theme: System, following your device (${theme}). Switch to ${next.label}.`
      : `Theme: ${current.label}. Switch to ${next.label}.`;

  return (
    <button
      type="button"
      onClick={() => setChoice(next.value)}
      title={label}
      aria-label={label}
      className={CORNER_BUTTON}
    >
      <ThemeIcon
        choice={current.value}
        className="h-5 w-5"
        stroke={navStroke(NAV_GRADIENT.flame)}
      />
    </button>
  );
}
