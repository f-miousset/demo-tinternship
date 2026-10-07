/**
 * The light/dark switch, and the invariant underneath it.
 *
 * Only one thing in this app decides what colour anything is: the `data-theme`
 * attribute on `<html>`. Every token block in `index.css` keys on it, and so
 * does Tailwind's `dark:` variant — so a bug that leaves the attribute stale
 * does not show up as one wrong component, it shows up as the whole app in the
 * wrong theme. None of that is visible from a type check, and a stylesheet is
 * not loaded here, which is exactly why the assertions are on the attribute
 * rather than on a colour.
 *
 * The other half is that **"System" has to keep meaning something**. It is the
 * default, and the behaviour the app had before the switch existed; a two-state
 * toggle would have quietly deleted it. So the sun going down mid-session has
 * its own test.
 *
 * The glass slider is here for the same reason and against the same kind of
 * invariant: one custom property on the same element decides how opaque every
 * pane in the app is, and a stylesheet is not loaded here either — so the
 * assertions are on `--glass-alpha` and on what a missing or impossible stored
 * value reads as, not on a colour.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp, stubApi } from "./harness";
import { setSystemDark } from "./setup";
import { GLASS, GLASS_KEY, THEME_KEY, normaliseGlass, setGlass, setThemeChoice } from "../lib/theme";

/** What `<html>` is currently wearing. */
const stamped = () => document.documentElement.dataset.theme;

/** The glass opacity as the stylesheet reads it: one inline custom property. */
const glassOnHtml = () => document.documentElement.style.getPropertyValue("--glass-alpha");

/** The Settings slider, which counts transparency rather than opacity. */
const slider = () => screen.getByRole("slider", { name: /glass transparency/i }) as HTMLInputElement;

describe("the appearance switch", () => {
  beforeEach(() => {
    stubApi();
    // The module holds one process-wide theme; `localStorage.clear()` in
    // setup.ts wipes the store but not the state built from it.
    setThemeChoice("system");
    setGlass(GLASS.default);
  });

  it("follows the device until it is told not to", () => {
    expect(stamped()).toBe("light");

    setSystemDark(true);
    expect(stamped()).toBe("dark");

    setSystemDark(false);
    expect(stamped()).toBe("light");
  });

  it("takes an override, and keeps it across a reload", async () => {
    renderApp("/settings");
    fireEvent.click(await screen.findByRole("radio", { name: /dark/i }));

    await waitFor(() => expect(stamped()).toBe("dark"));
    // Stored, so the boot script in index.html can stamp it before the first
    // paint of the next visit rather than flashing light and flipping.
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("ignores the device while an override is in force", async () => {
    renderApp("/settings");
    fireEvent.click(await screen.findByRole("radio", { name: /light/i }));
    await waitFor(() => expect(stamped()).toBe("light"));

    // Sunset. The whole point of an override is that this does nothing.
    setSystemDark(true);
    expect(stamped()).toBe("light");

    fireEvent.click(screen.getByRole("radio", { name: /system/i }));
    await waitFor(() => expect(stamped()).toBe("dark"));
    expect(window.localStorage.getItem(THEME_KEY)).toBe("system");
  });

  it("cycles the same three positions from the header, and wraps", async () => {
    renderApp("/settings");
    const button = () => screen.getByRole("button", { name: /^Theme:/ });
    await waitFor(() => button());

    // The corner has room for one 44px target, so the header operates the
    // switch blind: the icon says where you are, the label says where the next
    // tap lands. Which makes the *order* the contract — it has to be the
    // Settings control read left to right, or the two shapes are two controls.
    expect(button().getAttribute("aria-label")).toMatch(/System.*Switch to Light/);

    fireEvent.click(button());
    await waitFor(() => expect(stamped()).toBe("light"));
    expect(button().getAttribute("aria-label")).toBe("Theme: Light. Switch to Dark.");

    fireEvent.click(button());
    await waitFor(() => expect(stamped()).toBe("dark"));
    expect(button().getAttribute("aria-label")).toBe("Theme: Dark. Switch to System.");

    // Back to the start: without the wrap, "follow my device" would be
    // reachable only from the Settings page.
    fireEvent.click(button());
    await waitFor(() => expect(window.localStorage.getItem(THEME_KEY)).toBe("system"));
  });

  it("is one control in two places, not two", async () => {
    renderApp("/settings");
    fireEvent.click(await screen.findByRole("button", { name: /^Theme:/ }));

    // The header and the Settings switch are separate components reading one
    // store. A `useState` in either would let them disagree, and the page that
    // shows you all three positions is the worst place to be wrong.
    const radio = (name: RegExp) => screen.getByRole("radio", { name }) as HTMLInputElement;
    await waitFor(() => expect(radio(/light/i).checked).toBe(true));
    expect(radio(/system/i).checked).toBe(false);
  });

  it("puts the glass opacity on `<html>`, and stores it", async () => {
    // The slider writes one custom property and nothing else: every pane in the
    // app derives its background from `--glass-alpha`, so a component that
    // stopped painting it would take the header, the tab bar and every sheet
    // with it — and none of that is visible from a type check.
    renderApp("/settings");
    await waitFor(() => slider());

    // It counts transparency while the store counts opacity, which is the one
    // place the two can drift: a slider whose number rose as the glass got
    // thicker would be read as broken.
    expect(slider().value).toBe(String(Math.round((1 - GLASS.default) * 100)));

    fireEvent.change(slider(), { target: { value: "60" } });
    await waitFor(() => expect(glassOnHtml()).toBe("0.4"));
    expect(slider().value).toBe("60");
    // Stored, so `theme-boot.js` can stamp it before the first paint of the
    // next visit rather than changing opacity a frame in.
    expect(window.localStorage.getItem(GLASS_KEY)).toBe("0.4");
  });

  it("reads an unset, absent or impossible value as the default", () => {
    // `Number(null)` is 0, and 0 is finite — and 0 is now the end of the range
    // that removes every pane in the app. Read the absent key with `Number` and
    // a fresh install opens with no header, no tab bar and no sheets, looking
    // broken rather than configured.
    expect(normaliseGlass(null)).toBe(GLASS.default);
    expect(normaliseGlass(undefined)).toBe(GLASS.default);
    expect(normaliseGlass("")).toBe(GLASS.default);
    expect(normaliseGlass("opaque")).toBe(GLASS.default);

    // Hand-edited storage, or a range some other version offered. Both ends are
    // clamped rather than honoured — the stored value outlives the input that
    // wrote it — while everything between them is a position the slider has.
    expect(normaliseGlass("-3")).toBe(GLASS.min);
    expect(normaliseGlass(9)).toBe(GLASS.max);
    expect(normaliseGlass("0.02")).toBe(0.02);
    expect(normaliseGlass("0.5")).toBe(0.5);
  });

  it("takes the glass all the way to a window, and drops the filter there", async () => {
    // The far end is the point of the range: no pane at all, not a very faint
    // one. `--glass-strength` in the stylesheet takes the blur, the tint and the
    // rim down with the colour, and `data-glass` is what lets CSS remove the
    // `backdrop-filter` declaration rather than compute an identity one — a
    // custom property cannot do that, which is why this attribute exists at all.
    renderApp("/settings");
    await waitFor(() => slider());

    expect(slider().min).toBe("0");
    expect(slider().max).toBe("100");
    expect(document.documentElement.dataset.glass).toBeUndefined();

    fireEvent.change(slider(), { target: { value: "100" } });
    await waitFor(() => expect(glassOnHtml()).toBe("0"));
    expect(document.documentElement.dataset.glass).toBe("clear");

    // And back: one stop off the end is glass again, so the attribute cannot be
    // left behind on a pane that now has something to blur.
    fireEvent.change(slider(), { target: { value: "95" } });
    await waitFor(() => expect(document.documentElement.dataset.glass).toBeUndefined());
    expect(glassOnHtml()).toBe("0.05");
  });

  it("moves the browser chrome with the theme", async () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
    try {
      renderApp("/settings");
      fireEvent.click(await screen.findByRole("radio", { name: /dark/i }));
      // `--page-bg`, which is also the colour the page itself paints. A chrome
      // band in the other theme's colour is the most visible thing an installed
      // PWA can get wrong.
      await waitFor(() => expect(meta.getAttribute("content")).toBe("#0b090e"));
    } finally {
      meta.remove();
    }
  });
});
