/**
 * The Jobs chat: asking the agents for something in particular.
 *
 * The half of the add box that is not the paste field. Everything worth
 * checking here is a claim the backend suite cannot reach, because it is about
 * what the browser sends and what the candidate sees afterwards: that the
 * message reaches `/api/jobs/search` as a focus, that the conversation so far
 * travels with it, that the reply the transcript grows is the run's own result,
 * and that an ordinary "Run Investigator" click still sends no focus at all.
 *
 * Drives the real page through the real `useRunStream`, against a stubbed
 * endpoint answering in the wire format it really uses.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp, sseResponse, stubApi } from "./harness";

/** Every POST body the stubbed search endpoint was handed, in order. */
let sent: unknown[] = [];

function searchRun(events: [string, unknown][]) {
  return (_url: string, init?: RequestInit) => {
    sent.push(init?.body ? JSON.parse(String(init.body)) : null);
    return sseResponse(events);
  };
}

function result(over: Record<string, unknown> = {}) {
  return [
    "result",
    {
      jobs: [{ id: 1, title: "ML Intern", company: "Mistral AI", fit_score: 8 }],
      saved: { saved: 1, created: 1 },
      url_check: { ok: 1 },
      freshness: { week: 1, month: 0, quarter: 0, older: 0, undated: 0 },
      link_drops: {},
      answered_drops: {},
      strategy_notes: "",
      feedback_applied: null,
      audit: null,
      run_id: 4,
      target_results: 15,
      focus: "",
      ...over,
    },
  ] as [string, unknown];
}

async function openChat() {
  fireEvent.click(await screen.findByRole("tab", { name: "Ask the agents" }));
  return screen.getByPlaceholderText(/A company, a kind of role, a city/);
}

async function ask(text: string) {
  const field = await openChat();
  fireEvent.change(field, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  return field;
}

describe("asking the agents for a posting", () => {
  beforeEach(() => {
    sent = [];
    stubApi();
  });

  it("switches between the paste field and the chat", async () => {
    renderApp("/jobs");
    // The box opens on the paste field — the behaviour this page always had.
    expect(await screen.findByPlaceholderText("Paste a job posting link")).toBeTruthy();

    await openChat();
    expect(screen.queryByPlaceholderText("Paste a job posting link")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Paste a link" }));
    expect(screen.getByPlaceholderText("Paste a job posting link")).toBeTruthy();
  });

  it("sends the message as the run's focus and answers with what it found", async () => {
    stubApi({ "/api/jobs/search": searchRun([["run", { run_id: 4 }], result()]) });
    renderApp("/jobs");
    const field = await ask("Anything at Mistral AI");

    // The question goes up immediately — a run takes minutes, and a chat that
    // showed nothing until it ended would look like it lost the message.
    expect(await screen.findByText("Anything at Mistral AI")).toBeTruthy();
    await waitFor(() => expect((field as HTMLTextAreaElement).value).toBe(""));

    expect(sent).toEqual([{ focus: "Anything at Mistral AI", earlier: [] }]);
    expect(await screen.findByText("1 posting added to your deck.")).toBeTruthy();
  });

  it("carries the earlier turns so a follow-up resolves against them", async () => {
    stubApi({ "/api/jobs/search": searchRun([result()]) });
    renderApp("/jobs");
    await ask("Computer vision in Paris");
    await screen.findByText("1 posting added to your deck.");

    await ask("and also in Berlin");
    await waitFor(() => expect(sent.length).toBe(2));
    // Only what the candidate said, oldest first, and the new ask is not in it
    // twice — it travels as the focus.
    expect(sent[1]).toEqual({
      focus: "and also in Berlin",
      earlier: ["Computer vision in Paris"],
    });
  });

  it("passes the Matcher's own notes through as the reply", async () => {
    stubApi({
      "/api/jobs/search": searchRun([
        result({ strategy_notes: "Nothing open at Mistral that matches the brief." }),
      ]),
    });
    renderApp("/jobs");
    await ask("Anything at Mistral AI");

    // Twice on the page, deliberately: once as the reply in the conversation
    // that asked, and once in the run's own result card below the deck.
    expect(
      await screen.findAllByText("Nothing open at Mistral that matches the brief."),
    ).toHaveLength(2);
  });

  it("says so plainly when the run came back with nothing", async () => {
    stubApi({ "/api/jobs/search": searchRun([result({ jobs: [], saved: { saved: 0, created: 0 } })]) });
    renderApp("/jobs");
    await ask("Anything at a company that does not exist");

    expect(await screen.findByText(/Nothing came back for that/)).toBeTruthy();
  });

  it("reports a failed chat run inside the conversation, once", async () => {
    stubApi({
      "/api/jobs/search": searchRun([["error", { error: "The scoring came back empty twice." }]]),
    });
    renderApp("/jobs");
    await ask("Anything at Mistral AI");

    // The transcript must not be left hanging on a question nothing answered…
    expect(await screen.findByText(/That run did not finish/)).toBeTruthy();
    // …the reason is inside the panel, because on a phone that panel is a sheet
    // over the page and a note underneath it is one you must close the sheet to
    // read — and it is there exactly once, not also below the deck.
    expect(screen.getAllByText("The scoring came back empty twice.")).toHaveLength(1);
  });

  it("still reports a button run's failure on the page, chat open or not", async () => {
    // The other half of the same rule: one run stream serves both controls, so
    // a failure has to land beside the one that started it. With the chat tab
    // showing, a button run's error still belongs on the page — on a phone the
    // panel it would otherwise hide in is behind a "+" the candidate never
    // touched.
    stubApi({ "/api/jobs/search": searchRun([["error", { error: "Scouting fell over." }]]) });
    renderApp("/jobs");
    await openChat();
    // Two of them on an empty deck — the header's and the empty state's. Either
    // starts the same run; this test is about where its failure lands.
    fireEvent.click(screen.getAllByRole("button", { name: "Run Investigator" })[0]);

    expect(await screen.findAllByText("Scouting fell over.")).toHaveLength(1);
    // …and it did not put a turn in a conversation nobody was having.
    expect(screen.queryByText(/That run did not finish/)).toBeNull();
  });

  it("leaves the plain Investigator run unsteered", async () => {
    stubApi({ "/api/jobs/search": searchRun([result()]) });
    renderApp("/jobs");
    fireEvent.click(await screen.findByRole("button", { name: "Run Investigator" }));

    await waitFor(() => expect(sent.length).toBe(1));
    // No body at all — the endpoint's focus is optional, and the button asks
    // for exactly the run it always did.
    expect(sent[0]).toBeNull();
  });

  it("will not send an empty message", async () => {
    renderApp("/jobs");
    await openChat();
    // Nothing is stubbed for the search endpoint, so a request would 404 and
    // surface as an error note. The button being disabled is what prevents it.
    expect(screen.getByRole("button", { name: "Search" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows the history of sent messages and loads a selected message into the composer", async () => {
    stubApi({ "/api/jobs/search": searchRun([result()]) });
    renderApp("/jobs");

    // Initially open the chat
    const field = await openChat();
    const historyBtn = screen.getByRole("button", { name: /History/i });
    expect(historyBtn).toBeTruthy();

    // Click history when empty
    fireEvent.click(historyBtn);
    expect(await screen.findByText(/No sent messages yet/i)).toBeTruthy();

    // Close history
    fireEvent.click(screen.getByRole("button", { name: "Close history" }));
    expect(screen.queryByText(/No sent messages yet/i)).toBeNull();

    // Send a message
    fireEvent.change(field, { target: { value: "Mistral AI internships in Paris" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText("1 posting added to your deck.");

    // Open history again: the sent message should be listed in history
    fireEvent.click(screen.getByRole("button", { name: /History/i }));
    const matches = await screen.findAllByText("Mistral AI internships in Paris");
    expect(matches.length).toBeGreaterThanOrEqual(2);

    // Click "Use" on the history item to load it into the composer
    fireEvent.click(screen.getByRole("button", { name: "Use" }));
    expect((field as HTMLTextAreaElement).value).toBe("Mistral AI internships in Paris");
    // And history panel closed on selection
    expect(screen.queryByText("Sent messages")).toBeNull();

    // Open history again and clear all
    fireEvent.click(screen.getByRole("button", { name: /History/i }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(await screen.findByText(/No sent messages yet/i)).toBeTruthy();
  });

  it("synchronises account-based search query history recorded from another device", async () => {
    // History recorded on a computer exists in the account database
    stubApi({
      "/api/jobs/search/history": {
        items: [
          {
            id: "42",
            text: "check for internships at lovable ai, databricks, datadog",
            timestamp: Date.now() - 60000,
          },
        ],
      },
    });

    renderApp("/jobs");
    const field = await openChat();

    // The query badge shows 1 item from account history
    const historyBtn = screen.getByRole("button", { name: /History/i });
    expect(await screen.findByText("1")).toBeTruthy();

    // Opening history shows the query recorded on the computer
    fireEvent.click(historyBtn);
    expect(
      await screen.findByText("check for internships at lovable ai, databricks, datadog"),
    ).toBeTruthy();

    // Clicking "Use" loads it into the composer on the phone / client
    fireEvent.click(screen.getByRole("button", { name: "Use" }));
    expect((field as HTMLTextAreaElement).value).toBe(
      "check for internships at lovable ai, databricks, datadog",
    );
  });
});

