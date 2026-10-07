/**
 * The Tracker board shows one status at a time.
 *
 * Seven columns stacked on a phone made one list as long as the whole board, so
 * the board is a strip of the statuses that have something in them and one
 * status's cards under it. What is worth pinning down is the navigation — the
 * strip, the two arrows, the arrow keys and the swipe all move through the same
 * list in the same order — and the part that fails quietly: a key press while
 * typing in the search field must not change the status out from under you.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { application, job, renderApp, stubApi } from "./harness";

const BOARD = [
  application(1, job(1, "Backend Intern", "Vela Systems"), { status: "saved" }),
  application(2, job(2, "Machine Learning Intern", "Nimbus Labs")),
  application(3, job(3, "Data Intern", "Orbital SA"), { status: "hr_pre_call" }),
];

function tab(name: RegExp) {
  return screen.getByRole("tab", { name });
}

function panel() {
  return screen.getByRole("tabpanel");
}

describe("the Tracker board", () => {
  beforeEach(() => {
    stubApi({
      "/api/applications": (url: string) =>
        new Response(
          JSON.stringify({ applications: url.includes("view=trashed") ? [] : BOARD }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    });
  });

  it("shows the first status that has something in it, and only that one", async () => {
    renderApp("/tracker");

    expect(await screen.findByText("Vela Systems")).toBeTruthy();
    expect(screen.queryByText("Nimbus Labs")).toBeNull();
    expect(screen.queryByText("Orbital SA")).toBeNull();
    // Only non-empty statuses get a tab, each with its count.
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Saved1",
      "Applied1",
      "HR pre-call1",
    ]);
    expect(tab(/Saved/).getAttribute("aria-selected")).toBe("true");
  });

  it("changes status from the strip and from the arrows, stopping at both ends", async () => {
    renderApp("/tracker");
    expect(await screen.findByText("Vela Systems")).toBeTruthy();
    const previous = screen.getByRole("button", { name: "Previous status" }) as HTMLButtonElement;
    const next = screen.getByRole("button", { name: "Next status" }) as HTMLButtonElement;
    expect(previous.disabled).toBe(true);

    fireEvent.click(tab(/HR pre-call/));
    expect(within(panel()).getByText("Orbital SA")).toBeTruthy();
    expect(next.disabled).toBe(true);

    fireEvent.click(previous);
    expect(within(panel()).getByText("Nimbus Labs")).toBeTruthy();
  });

  it("follows the arrow keys, but not while typing in the search field", async () => {
    renderApp("/tracker");
    expect(await screen.findByText("Vela Systems")).toBeTruthy();

    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(await within(panel()).findByText("Nimbus Labs")).toBeTruthy();

    // The caret moving through "nimbus" is not a request to change status.
    fireEvent.keyDown(screen.getByLabelText("Search applications"), { key: "ArrowRight" });
    expect(within(panel()).getByText("Nimbus Labs")).toBeTruthy();

    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(await within(panel()).findByText("Vela Systems")).toBeTruthy();
  });

  it("turns the page on a sideways swipe, and ignores a scroll", async () => {
    renderApp("/tracker");
    expect(await screen.findByText("Vela Systems")).toBeTruthy();

    // Mostly downward: someone scrolling the list.
    fireEvent.touchStart(panel(), { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchEnd(panel(), { changedTouches: [{ clientX: 220, clientY: 400 }] });
    expect(within(panel()).getByText("Vela Systems")).toBeTruthy();

    // Right to left: the next status, as turning a page.
    fireEvent.touchStart(panel(), { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchEnd(panel(), { changedTouches: [{ clientX: 150, clientY: 110 }] });
    expect(await within(panel()).findByText("Nimbus Labs")).toBeTruthy();
  });

  it("orders a status by fit score, best first, with a pin above everything", async () => {
    stubApi({
      "/api/applications": () =>
        new Response(
          JSON.stringify({
            applications: [
              application(11, job(11, "A", "Low", { fit_score: 5 })),
              application(12, job(12, "B", "Unscored", { fit_score: 0 })),
              application(13, job(13, "C", "Pinned", { fit_score: 4 }), { pinned: true }),
              application(14, job(14, "D", "High", { fit_score: 9 })),
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    });
    renderApp("/tracker");
    expect(await screen.findByText("High")).toBeTruthy();

    const order = within(panel())
      .getAllByRole("link")
      .map((card) => card.querySelector("p")?.textContent);
    expect(order).toEqual(["Pinned", "High", "Low", "Unscored"]);
  });

  it("puts the search first, then the charts, then the board", async () => {
    renderApp("/tracker");
    expect(await screen.findByText("Vela Systems")).toBeTruthy();

    const search = screen.getByLabelText("Search applications");
    const charts = screen.getByRole("img", { name: /^By status/ });
    const board = screen.getByRole("tablist");
    const follows = (a: Element, b: Element) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(search, charts)).toBe(true);
    expect(follows(charts, board)).toBe(true);
    // No note on the charts until a search is actually narrowing the board.
    expect(screen.queryByText(/the search narrows the board only/)).toBeNull();
  });

  it("keeps the status in the URL, so coming back lands on it", async () => {
    renderApp("/tracker?status=hr_pre_call");

    expect(await screen.findByText("Orbital SA")).toBeTruthy();
    expect(tab(/HR pre-call/).getAttribute("aria-selected")).toBe("true");
  });

  it("falls through to the first status left when a search empties the chosen one", async () => {
    renderApp("/tracker?status=saved");
    expect(await screen.findByText("Vela Systems")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search applications"), {
      target: { value: "orbital" },
    });

    await waitFor(() => expect(within(panel()).getByText("Orbital SA")).toBeTruthy());
    expect(screen.getAllByRole("tab")).toHaveLength(1);
  });
});
