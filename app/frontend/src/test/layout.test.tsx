/**
 * The shell's three jobs: gate the app until the account is set up, say when
 * the API key is missing, and carry the follow-up count.
 *
 * The gate is the one worth guarding. Nothing downstream of it checks again —
 * every screen assumes a profile, a brief and a playbook exist — so if this
 * stops holding, an agent runs with no context and produces confident nonsense
 * instead of an error. See `services/onboarding.py` for the other half.
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { FollowUp } from "../lib/types";
import { CONFIG, renderApp, stubApi } from "./harness";

const INCOMPLETE = {
  ...CONFIG,
  progress: { ...CONFIG.progress, has_brief: false, complete: false },
};

const SILENT_APPLICATION: FollowUp = {
  application_id: 7,
  job_posting_id: 3,
  status: "applied",
  language: "en",
  days_silent: 21,
  last_activity: "2026-08-01T09:00:00Z",
  job: { title: "Data Engineering Intern", company: "Datadog", apply_url: "https://example.test/job" },
  draft: null,
  draft_stale: false,
};

/** Move the window and let the header's rAF-deferred read of it land. */
async function scrollTo(y: number) {
  await act(async () => {
    window.scrollY = y;
    window.dispatchEvent(new Event("scroll"));
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
}

/** The header's segmented control and the phone's tab bar, in that order. */
function navs(): HTMLElement[] {
  const all = Array.from(document.querySelectorAll<HTMLElement>('nav[aria-label="Main"]'));
  expect(all).toHaveLength(2);
  return all;
}

function link(bar: HTMLElement, href: string): HTMLAnchorElement {
  const found = bar.querySelector<HTMLAnchorElement>(`a[href="${href}"]`);
  if (!found) throw new Error(`no link to ${href}`);
  return found;
}

function lens(): HTMLElement {
  const found = document.querySelector<HTMLElement>(".tabbar-lens");
  if (!found) throw new Error("no tab bar lens");
  return found;
}

function rowOf(bar: HTMLElement): HTMLElement {
  const found = bar.querySelector<HTMLElement>(".tabbar-row");
  if (!found) throw new Error("no tab bar row");
  return found;
}

/** jsdom lays nothing out: give the two-tab row 240px, 0–120 and 120–240. */
function giveRowAWidth(row: HTMLElement) {
  row.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 240, height: 62, right: 240, bottom: 62, x: 0, y: 0 }) as DOMRect;
}

describe("the shell", () => {
  afterEach(() => {
    window.scrollY = 0;
  });

  it("holds the main screens until the account setup is finished", async () => {
    stubApi({ "/api/config": INCOMPLETE });
    renderApp("/jobs");

    expect(await screen.findByRole("heading", { name: "Account" })).toBeTruthy();
    expect(screen.getByText(/Your account setup is not finished/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Job postings" })).toBeNull();
  });

  it.each([
    ["/settings", "Settings"],
    ["/traces", "Traces & audit"],
  ])(
    "leaves %s reachable while the setup is unfinished, because that is where you fix it",
    async (path, heading) => {
      stubApi({ "/api/config": INCOMPLETE });
      renderApp(path);

      expect(await screen.findAllByRole("heading", { name: heading })).not.toHaveLength(0);
      expect(screen.queryByRole("heading", { name: "Account" })).toBeNull();
    },
  );

  it("lets the main screens through once the setup is complete", async () => {
    stubApi();
    renderApp("/jobs");

    expect(await screen.findByRole("heading", { name: "Job postings" })).toBeTruthy();
    expect(screen.queryByText(/Your account setup is not finished/)).toBeNull();
  });

  it("names the app once, in both layouts", async () => {
    // The wordmark used to be two responsive copies — a short one for phones,
    // a long one for laptops — which meant every rename had two places to miss.
    // "Tinternship" is short enough to be the only one.
    stubApi();
    renderApp("/jobs");
    expect(await screen.findAllByText("Tinternship")).toHaveLength(1);
  });

  it("keeps a name on the header's two icon-only links", async () => {
    // Account and Settings are a person and two sliders with no text beside
    // them — that is what buys the segmented control the middle of a 375px row.
    // Drop the aria-label and they become two unnamed links, indistinguishable
    // from each other in the accessibility tree and unreachable by name, with
    // nothing on screen looking any different.
    stubApi();
    renderApp("/jobs");

    await screen.findByRole("heading", { name: "Job postings" });
    expect(screen.getByRole("link", { name: "Account" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Settings" })).toBeTruthy();
  });

  it("draws the corner's two links in the brand ramp, lit on hover and on their page", async () => {
    // Drawings rather than words, so the gradient *is* how they read — and it is
    // what a phone gets, where there is no pointer to reveal a hover with. The
    // halo is CSS (`.nav-lit:hover`), but the two hooks it hangs on are here: the
    // classes, and `aria-current`, which `NavLink` sets and the stylesheet reads
    // rather than duplicating as a class of its own.
    stubApi();
    renderApp("/account");
    await screen.findByRole("heading", { name: "Account" });

    for (const name of ["Account", "Settings"]) {
      const link = screen.getByRole("link", { name });
      expect(link.className).toContain("nav-lit");
      expect(link.className).toContain("nav-flame");
      expect(link.querySelector("svg")?.getAttribute("stroke")).toBe("url(#nav-gradient-flame)");
      // A border that appears on hover would grow the button by two pixels under
      // the pointer; it is declared transparent and only recoloured.
      expect(link.className).toContain("border-transparent");
    }

    expect(screen.getByRole("link", { name: "Account" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("aria-current")).toBeNull();

    // The theme button is the third in the cluster and wears the same class
    // string, from the same constant — three round buttons that drift apart stop
    // reading as a set. The one part it cannot share is `aria-current`: it is a
    // `<button>` that cycles in place, with no page to be current on.
    const theme = screen.getByRole("button", { name: /^Theme:/ });
    expect(theme.className).toContain("nav-lit");
    expect(theme.querySelector("svg")?.getAttribute("stroke")).toBe("url(#nav-gradient-flame)");
    expect(theme.getAttribute("aria-current")).toBeNull();

  });

  it("leaves the Settings page's copy of the theme control in plain ink", async () => {
    // Same icons, different job: three of them sit inside one segmented switch
    // there, where the ink and the raised pill are what say which segment is
    // selected. Painting all three with the brand ramp would say nothing about
    // the selection and everything about the brand.
    stubApi();
    renderApp("/settings");

    const label = (await screen.findByRole("radio", { name: /light/i })).closest("label");
    expect(label?.querySelector("svg")?.getAttribute("stroke")).toBe("currentColor");
  });

  it("merges the header into the top edge until something scrolls under it", async () => {
    // On a phone the header is two shapes — a slab welded to the top of the
    // screen while you are at the top of the page, the floating capsule once
    // content is passing beneath it — and `data-merged` is the whole switch
    // between them. Everything else about the change is CSS, so a listener that
    // stopped firing would leave the header frozen in one shape with nothing in
    // the markup, the console or any other test looking any different.
    stubApi();
    const { container } = renderApp("/jobs");
    await screen.findByRole("heading", { name: "Job postings" });

    const dock = container.querySelector(".header-dock");
    expect(dock?.hasAttribute("data-merged")).toBe(true);

    await scrollTo(200);
    await waitFor(() => expect(dock?.hasAttribute("data-merged")).toBe(false));

    // Back to the top, and past it: nothing reads a bounce as "scrolled". The
    // document scroller clamps at zero so a real one never reports this at all,
    // but the threshold has to hold for the hair above zero it lands on coming
    // back — and for any engine that does report it.
    await scrollTo(-40);
    await waitFor(() => expect(dock?.hasAttribute("data-merged")).toBe(true));
  });

  it("marks the selected tab with a halo in the header and the section's gradient in both bars", async () => {
    // In the header the selected tab is a raised neutral pill with a coloured
    // glow, and the colour is carried by the icon and the label rather than by a
    // fill. Three separate things have to agree for that, and two of them fail
    // *silently*: an icon whose `stroke` still says `currentColor` is grey on a
    // pill with no fill, and a label without the clip class is
    // transparent-on-nothing.
    stubApi();
    renderApp("/jobs");
    await screen.findByRole("heading", { name: "Job postings" });

    const [header, dock] = navs();

    const jobs = link(header, "/jobs");
    expect(jobs.className).toContain("nav-selected");
    expect(jobs.className).toContain("nav-flame");
    expect(jobs.querySelector("svg")?.getAttribute("stroke")).toBe("url(#nav-gradient-flame)");
    expect(jobs.querySelector(".brand-text")?.textContent).toBe("Jobs");

    // The phone's tab bar has no halo — iOS 26's sliding pill carries the
    // selection, and the colour with it: the real row is ink, the tint is the
    // copy inside the pill, and the real face it sits over is faded out so the
    // ink cannot fringe it. Tinting the real row from the route made the colour
    // snap mid-slide.
    const phoneJobs = link(dock, "/jobs");
    expect(phoneJobs.getAttribute("aria-current")).toBe("page");
    expect(phoneJobs.hasAttribute("data-covered")).toBe(true);
    expect(phoneJobs.querySelector("svg")?.getAttribute("stroke")).toBe("currentColor");
    expect(link(dock, "/tracker").hasAttribute("data-covered")).toBe(false);
    const copy = lens().querySelector(".tabbar-lens-row > :first-child");
    expect(copy?.querySelector("svg")?.getAttribute("stroke")).toBe("url(#nav-gradient-flame)");
    expect(copy?.querySelector(".brand-text")?.textContent).toBe("Jobs");

    // The unselected one is plain ink in both: no pill, no glow, no gradient.
    for (const bar of [header, dock]) {
      const tracker = link(bar, "/tracker");
      expect(tracker.className).not.toContain("nav-selected");
      expect(tracker.querySelector("svg")?.getAttribute("stroke")).toBe("currentColor");
      expect(tracker.querySelector(".track-text")).toBeNull();
    }

    // The paint servers themselves. `url(#…)` pointing at nothing is not an
    // error and not a fallback — it paints *no* stroke, so dropping this one
    // element leaves the selected tab's icon invisible with everything else
    // still passing.
    expect(document.querySelector("#nav-gradient-flame")).toBeTruthy();
    expect(document.querySelector("#nav-gradient-track")).toBeTruthy();
  });

  it("slides the tab bar's one pill to the tab you are on, and hides it elsewhere", async () => {
    // One element for every tab, positioned by a number — which is what lets it
    // travel between tabs instead of blinking from one to the other.
    stubApi();
    renderApp("/tracker");
    await waitFor(() => expect(lens().style.getPropertyValue("--lens-pos")).toBe("1"));
    expect(lens().hasAttribute("data-hidden")).toBe(false);

    // Settings is neither tab, so there is nothing for the pill to sit on.
    cleanup();
    renderApp("/settings");
    await waitFor(() => expect(lens().hasAttribute("data-hidden")).toBe(true));
  });

  it("lifts the pill into a lens under a finger and goes where it is let go", async () => {
    // A drag that starts on Jobs and ends over Tracker goes to Tracker — the
    // lens decides, not the link the finger went down on.
    stubApi();
    renderApp("/jobs");
    await screen.findByRole("heading", { name: "Job postings" });
    const row = rowOf(navs()[1]);
    giveRowAWidth(row);

    fireEvent.pointerDown(row, { button: 0, pointerId: 1, clientX: 60 });
    expect(lens().hasAttribute("data-lifted")).toBe(true);
    expect(lens().style.getPropertyValue("--lens-pos")).toBe("0");

    fireEvent.pointerMove(row, { pointerId: 1, clientX: 120 });
    expect(Number(lens().style.getPropertyValue("--lens-pos"))).toBeCloseTo(0.5, 1);
    fireEvent.pointerMove(row, { pointerId: 1, clientX: 180 });
    fireEvent.pointerUp(row, { pointerId: 1, clientX: 180 });

    expect(lens().hasAttribute("data-lifted")).toBe(false);
    expect(await screen.findByRole("heading", { name: "Tracker" })).toBeTruthy();
  });

  it("lifts the pill in place on a press, so a tap to the other tab slides on release", async () => {
    // A press on Tracker used to send the lens there at once, on the quick
    // lifted curve, so the whole switch happened under the finger and the slow
    // slide never ran. It only leaves its tab once the finger drags.
    stubApi();
    renderApp("/jobs");
    await screen.findByRole("heading", { name: "Job postings" });
    const row = rowOf(navs()[1]);
    giveRowAWidth(row);

    fireEvent.pointerDown(row, { button: 0, pointerId: 1, clientX: 180 });
    expect(lens().hasAttribute("data-lifted")).toBe(true);
    expect(lens().style.getPropertyValue("--lens-pos")).toBe("0");
    fireEvent.pointerMove(row, { pointerId: 1, clientX: 183 });
    expect(lens().style.getPropertyValue("--lens-pos")).toBe("0");

    fireEvent.pointerUp(row, { pointerId: 1, clientX: 183 });
    expect(lens().hasAttribute("data-lifted")).toBe(false);
    expect(lens().style.getPropertyValue("--lens-pos")).toBe("1");
    expect(await screen.findByRole("heading", { name: "Tracker" })).toBeTruthy();
  });

  it("swallows the click a tap leaves behind, and leaves a keyboard's alone", async () => {
    // The tap has already navigated on `pointerup`; the click the browser fires
    // after it must not navigate a second time — here, back to where the finger
    // first went down.
    stubApi();
    renderApp("/jobs");
    await screen.findByRole("heading", { name: "Job postings" });
    const dock = navs()[1];
    const row = rowOf(dock);
    giveRowAWidth(row);

    fireEvent.pointerDown(row, { button: 0, pointerId: 1, clientX: 180 });
    fireEvent.pointerUp(row, { pointerId: 1, clientX: 180 });
    await screen.findByRole("heading", { name: "Tracker" });

    const pointerClick = new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 });
    link(dock, "/jobs").dispatchEvent(pointerClick);
    expect(pointerClick.defaultPrevented).toBe(true);

    // Enter on a focused link is a click with `detail` 0, and it navigates.
    fireEvent.click(link(dock, "/jobs"), { detail: 0 });
    expect(await screen.findByRole("heading", { name: "Job postings" })).toBeTruthy();
  });

  it("says when there is no API key, because that is why nothing works", async () => {
    stubApi({
      "/api/config": { ...CONFIG, gemini_configured: false, warnings: ["GOOGLE_API_KEY is not set"] },
    });
    renderApp("/jobs");

    expect(await screen.findByText("no API key")).toBeTruthy();
    expect(screen.getByText("· GOOGLE_API_KEY is not set")).toBeTruthy();
  });

  it("carries the follow-up count on both copies of the Tracker tab", async () => {
    // The desktop row and the phone tab bar are two renders of the same NAV,
    // and the count is the whole notification on a device that will not raise
    // a system one — it has to ride both.
    stubApi({
      "/api/applications/follow-ups": { after_days: 14, follow_ups: [SILENT_APPLICATION] },
    });
    renderApp("/jobs");

    expect(await screen.findAllByText("1")).toHaveLength(2);
  });

  it("shows no count when nothing has gone quiet", async () => {
    stubApi();
    renderApp("/jobs");

    await screen.findByRole("heading", { name: "Job postings" });
    expect(screen.queryByTitle(/application(s?) with no reply/)).toBeNull();
  });
});
