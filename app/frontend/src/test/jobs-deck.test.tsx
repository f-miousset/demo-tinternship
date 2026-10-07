/**
 * The deck, and the four things a verdict has to do.
 *
 * Each gesture writes something different, and none of it is visible from the
 * backend suite: what has to hold here is that the button for a direction calls
 * the endpoint that direction means, that the answered card leaves the deck and
 * the next one arrives, and that the two sheets — the trash and the mobile "+"
 * — open at all.
 *
 * Everything is driven through the buttons rather than through synthetic
 * pointer events. That is deliberate and it mirrors the design: `index.css`
 * kills every transition under `prefers-reduced-motion`, so the deck has to be
 * completely usable without a drag, and the buttons are the interface rather
 * than a fallback for it.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp, stubApi } from "./harness";

function job(id: number, company: string, over: Record<string, unknown> = {}) {
  return {
    id,
    title: `${company} ML Intern`,
    company,
    location: "Paris",
    remote: "hybrid",
    url: `https://${company.toLowerCase()}.example/job`,
    apply_url: "",
    source: "grounded_search",
    description: "A long description. With a second sentence.",
    summary: `Six-month ML internship at ${company}.`,
    requirements: ["Python", "PyTorch"],
    nice_to_have: [],
    contract_type: "internship",
    start_date: "",
    duration: "6 months",
    compensation: "",
    language: "",
    posted_at: "",
    posted_on: "",
    posted_days_ago: 3,
    deadline: "",
    fit_score: 8.5,
    fit_rationale: "Strong match.",
    strengths: ["PyTorch on both sides"],
    risks: ["Deadline is tight"],
    keywords: ["PyTorch"],
    confidence: "high",
    url_status: "ok",
    url_http_status: 200,
    dismissed: false,
    deferred_at: null,
    run_id: 1,
    invocation_id: "inv-1",
    discovered_at: "2026-08-20T10:00:00+00:00",
    application_id: null,
    ...over,
  };
}

/** Records every write the page makes, so a test can name the one it expects. */
function deckApi(deck: unknown[], discarded: unknown[] = []) {
  const calls: string[] = [];
  stubApi({
    "/api/jobs": (url: string) =>
      new Response(
        JSON.stringify({
          jobs: url.includes("view=discarded") ? discarded : deck,
          sources: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    "/api/jobs/1/defer": () => {
      calls.push("defer:1");
      return new Response(JSON.stringify({ id: 1, deferred_at: "now" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    "/api/jobs/1/dismiss": (url: string) => {
      calls.push(url.includes("dismissed=true") ? "dismiss:1" : "restore:1");
      return new Response(JSON.stringify({ id: 1, dismissed: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    "/api/jobs/1": (_url: string, init?: RequestInit) => {
      calls.push(init?.method === "DELETE" ? "delete:1" : "get:1");
      return new Response(JSON.stringify({ deleted: 1, files: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    "/api/jobs/trash": (_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") calls.push("empty");
      return new Response(JSON.stringify({ deleted: 1, files: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    "/api/applications": () => {
      calls.push("apply:1");
      return new Response(JSON.stringify({ id: 99, pinned: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });
  return calls;
}

const ACTIONS = {
  discard: "Discard it — it goes to the trash, and no run brings it back",
  later: "Undecided — back of the deck",
  pin: "Save it and pin it — top of its Tracker column",
  save: "Save it — it goes to the Tracker",
};

describe("the swipe deck", () => {
  beforeEach(() => {
    stubApi();
  });

  it("shows one posting at a time, company first", async () => {
    deckApi([job(1, "Mistral"), job(2, "Criteo")]);
    renderApp("/jobs");

    // Both are in the DOM — the second is the card peeking behind — but only
    // the top one is the card being acted on.
    expect(await screen.findByRole("heading", { name: "Mistral" })).toBeTruthy();
    expect(screen.getByText("Six-month ML internship at Mistral.")).toBeTruthy();
  });

  it("sends a discard to the dismiss endpoint", async () => {
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: ACTIONS.discard }));
    await waitFor(() => expect(calls).toContain("dismiss:1"));
  });

  it("sends an undecided swipe to the defer endpoint", async () => {
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: ACTIONS.later }));
    await waitFor(() => expect(calls).toContain("defer:1"));
  });

  it("validating creates the application and says where it went", async () => {
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: ACTIONS.save }));
    await waitFor(() => expect(calls).toContain("apply:1"));
    // It does not navigate: on a deck, ending the session on every yes would
    // make the gesture cost more than the list it replaced.
    expect(await screen.findByText(/saved to your Tracker/)).toBeTruthy();
  });

  it("pinning creates the application too, and says it is pinned", async () => {
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: ACTIONS.pin }));
    await waitFor(() => expect(calls).toContain("apply:1"));
    expect(await screen.findByText(/pinned/)).toBeTruthy();
  });

  it("answers the arrow keys as well as the buttons", async () => {
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");
    await screen.findByRole("heading", { name: "Mistral" });

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    await waitFor(() => expect(calls).toContain("dismiss:1"));
  });

  it("says so when there is nothing left to swipe", async () => {
    deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    expect(await screen.findByText("Nothing left to swipe")).toBeTruthy();
  });

  it("opens the trash, and offers each posting back", async () => {
    deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    const sheet = await screen.findByRole("dialog", { name: "Discarded postings" });
    expect(sheet).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Put back in the deck" })).toBeTruthy();
  });

  it("puts a discarded posting back", async () => {
    const calls = deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Put back in the deck" }));
    await waitFor(() => expect(calls).toContain("restore:1"));
  });

  it("deletes a discarded posting forever only on a second tap", async () => {
    const calls = deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete forever" }));
    expect(calls).not.toContain("delete:1");
    fireEvent.click(screen.getByRole("button", { name: "Tap again to delete" }));
    await waitFor(() => expect(calls).toContain("delete:1"));
  });

  it("empties the trash", async () => {
    const calls = deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Empty the trash (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Tap again to delete all 1" }));
    await waitFor(() => expect(calls).toContain("empty"));
  });

  it("opens the details sheet with what the card had to leave out", async () => {
    deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "details" }));
    expect(
      await screen.findByRole("dialog", { name: "Mistral — Mistral ML Intern" }),
    ).toBeTruthy();
    expect(screen.getByText("Why this score")).toBeTruthy();
  });

  it("opens the add box from the floating +", async () => {
    // The mobile path. The button is `sm:hidden`, which jsdom does not apply —
    // what this proves is that it opens the same box the desktop card holds,
    // both halves of it: the paste field and the chat that steers a run.
    deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    fireEvent.click(
      await screen.findByRole("button", { name: "Add a posting, or ask the agents for one" }),
    );
    const sheet = await screen.findByRole("dialog", { name: "Add a posting" });
    expect(within(sheet).getByRole("tab", { name: "Paste a link" })).toBeTruthy();
    expect(within(sheet).getByRole("tab", { name: "Ask the agents" })).toBeTruthy();
  });

  it("opens the details sheet from a pointer that started on the button", async () => {
    // The desktop bug this guards. The deck captures the pointer on
    // `pointerdown` so a flick that leaves the card still ends on it — and a
    // captured pointer makes the browser fire `click` at the capturing element
    // instead of at the button, which is why "details" did nothing with a
    // mouse and worked fine with a finger (a touch pointer captures to its own
    // target implicitly). The button stops `pointerdown` from reaching the
    // deck, so the sequence below must reach no verdict at all.
    const calls = deckApi([job(1, "Mistral")]);
    renderApp("/jobs");

    const details = await screen.findByRole("button", { name: "details" });
    fireEvent.pointerDown(details, { pointerId: 1, clientX: 10, clientY: 10 });
    // Far enough right to be a "save" if the deck were seeing this drag.
    fireEvent.pointerMove(details, { pointerId: 1, clientX: 210, clientY: 10 });
    fireEvent.pointerUp(details, { pointerId: 1, clientX: 210, clientY: 10 });
    fireEvent.click(details);

    expect(
      await screen.findByRole("dialog", { name: "Mistral — Mistral ML Intern" }),
    ).toBeTruthy();
    expect(calls).toEqual([]);
  });

  it("closes a sheet when it is pulled down", async () => {
    // The phone gesture: a panel that rose from the bottom edge goes back to it.
    // Fired on the title, which sits inside the grab handle, so this also
    // proves the handle covers the header and not only the grabber.
    deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    const sheet = await screen.findByRole("dialog", { name: "Discarded postings" });
    const title = within(sheet).getByRole("heading", { name: "Discarded postings" });

    fireEvent.pointerDown(title, { pointerId: 1, clientY: 100 });
    fireEvent.pointerMove(title, { pointerId: 1, clientY: 240 });
    fireEvent.pointerUp(title, { pointerId: 1, clientY: 240 });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Discarded postings" })).toBeNull(),
    );
  });

  it("keeps a sheet open when the pull was a tap that wandered", async () => {
    // The deadzone. Without it every tap on the header — reaching for the ✕ —
    // would close the sheet, which is the same outcome by accident.
    deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    const sheet = await screen.findByRole("dialog", { name: "Discarded postings" });
    const title = within(sheet).getByRole("heading", { name: "Discarded postings" });

    fireEvent.pointerDown(title, { pointerId: 1, clientY: 100 });
    fireEvent.pointerMove(title, { pointerId: 1, clientY: 104 });
    fireEvent.pointerUp(title, { pointerId: 1, clientY: 104 });

    expect(screen.getByRole("dialog", { name: "Discarded postings" })).toBeTruthy();
  });

  it("closes a sheet on Escape", async () => {
    // A dialog that only closes by mouse traps a keyboard user on a page whose
    // whole point is that the keyboard works.
    deckApi([], [job(1, "Mistral", { dismissed: true })]);
    renderApp("/jobs");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    await screen.findByRole("dialog", { name: "Discarded postings" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Discarded postings" })).toBeNull(),
    );
  });
});
