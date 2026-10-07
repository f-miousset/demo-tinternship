/**
 * Pasting a posting on the Jobs page — as a link, or as its text.
 *
 * The Investigator's button is one click and nothing to get wrong. These two
 * have a field, a stream and three outcomes each, and every one of them is
 * something the candidate sees rather than something a backend test can reach:
 * the progress lines while it runs, and the sentence saying why a paste was
 * refused.
 *
 * A paste is also a decision — the whole decision. The candidate went and found
 * this posting, so nothing is left for the app to ask: it tracks it, guesses the
 * language off the posting's own prose, and lands them on the application with
 * the package already being written. Which is why most of this file drives **two
 * pages**, and why the assertions that matter are about what crossed between
 * them.
 *
 * The text mode was added on 2026-09-03 for the postings a link cannot reach —
 * the one that arrived as an email or a PDF, and the one on a board that
 * answers every fetch with a challenge. It shares the run hook with the link
 * form, which is what makes one outcome correct for both.
 *
 * Drives the real pages through the real `useRunStream` and the real router,
 * against stubbed `/api/jobs/import` and `/api/jobs/import-text` answering in
 * the wire format the endpoints really use.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderApp, sseResponse, stubApi } from "./harness";

const LINK = "https://boards.greenhouse.io/acme/jobs/4012345";

const JOB = {
  id: 12,
  title: "ML Research Intern",
  company: "Acme",
  fit_score: 8.5,
  fit_rationale: "PyTorch on both sides",
  url: LINK,
  url_status: "ok",
  url_http_status: 200,
  requirements: [],
  nice_to_have: [],
  strengths: [],
  risks: [],
  keywords: [],
};

/** The application a paste lands on. `language` is the guess, made in Python. */
function application(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    job_posting_id: 12,
    status: "saved",
    pinned: false,
    language: "en",
    personalisation: "",
    notes: "",
    next_action: "",
    next_action_date: "",
    applied_at: null,
    trashed_at: null,
    created_at: "2026-09-18T09:00:00+00:00",
    updated_at: "2026-09-18T09:00:00+00:00",
    job: JOB,
    artifacts: [],
    timeline: [],
    ...overrides,
  };
}

function result(overrides: Record<string, unknown> = {}) {
  return {
    job: JOB,
    job_id: 12,
    saved: { saved: 1, created: 1, updated: 0 },
    already_saved: false,
    restored: false,
    untrashed: false,
    application_id: 42,
    tracked: true,
    url_check: { ok: 1 },
    audit: { overall: 8 },
    run_id: 7,
    ...overrides,
  };
}

function importRun(events: [string, unknown][]) {
  // A fresh Response per call: a body may only be read once, and the page is
  // free to run more than one import.
  return () => sseResponse(events);
}

/** The whole path, stubbed: the import, the application it lands on, the run. */
function stubPaste(events: [string, unknown][], app = application()) {
  const generate = vi.fn(() => sseResponse([["result", { artifacts: {}, run_id: 8 }]]));
  stubApi({
    "/api/jobs/import": importRun(events),
    "/api/jobs/import-text": importRun(events),
    "/api/applications/42": app,
    "/api/applications/42/generate": generate,
  });
  return generate;
}

/** What reached `/generate`, which is only visible in what the page **sends**. */
function generateBodies() {
  const sent: string[] = [];
  const inner = globalThis.fetch;
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/generate")) sent.push(String(init?.body ?? ""));
    return inner(input, init);
  }) as typeof fetch;
  return sent;
}

async function paste(url = LINK) {
  const field = await screen.findByPlaceholderText("Paste a job posting link");
  fireEvent.change(field, { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: "Add posting" }));
  return field;
}

describe("adding a posting by link", () => {
  beforeEach(() => {
    stubApi();
  });

  it("streams the run and carries you into the package", async () => {
    const generate = stubPaste([
      ["run", { run_id: 7 }],
      ["phase", { phase: "fetch", message: "Opening the link…" }],
      ["phase", { phase: "reader", message: "Reading the posting…" }],
      ["result", result()],
    ]);
    const { router } = renderApp("/jobs");
    await paste();

    // The posting is not left on a card with a button on it. It was tracked,
    // its language was decided, and the only thing left is what the candidate
    // pasted it for.
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "Acme" })).toBeTruthy();
    await waitFor(() => expect(router.state.location.pathname).toBe("/applications/42"));
  });

  it("opens a posting it has seen before without generating it again", async () => {
    // `tracked: false` — the application was already there, and may already have
    // a résumé and a letter. Two model runs is not what "I pasted that again"
    // means, and the page's own Regenerate button is one tap away.
    const generate = stubPaste([
      [
        "result",
        result({
          saved: { saved: 1, created: 0, updated: 1 },
          already_saved: true,
          tracked: false,
        }),
      ],
    ]);
    const { router } = renderApp("/jobs");
    await paste();

    await waitFor(() => expect(router.state.location.pathname).toBe("/applications/42"));
    expect(generate).not.toHaveBeenCalled();
  });

  it("shows the refusal instead of pretending something was saved", async () => {
    stubApi({
      "/api/jobs/import": importRun([
        [
          "error",
          {
            error:
              "That link does not open a single job posting — this is a careers or job-search page, not one posting.",
          },
        ],
      ]),
    });
    const { router } = renderApp("/jobs");
    await paste("https://acme.com/careers");

    expect(await screen.findByText(/does not open a single job posting/)).toBeTruthy();
    // And it stays put: a refused paste has nowhere to go.
    expect(router.state.location.pathname).toBe("/jobs");
  });

  it("will not start a run with an empty field", async () => {
    renderApp("/jobs");
    // Nothing is stubbed for the import endpoint, so a request would 404 and
    // surface as an error note. The button being disabled is what prevents it.
    expect(
      (await screen.findByRole("button", { name: "Add posting" })).hasAttribute("disabled"),
    ).toBe(true);
  });
});

const PASTED = [
  "ML Research Intern — Acme, Paris",
  "Six-month internship on the research team, starting in January. You will work",
  "on representation learning with the perception group, in PyTorch.",
  "Requirements: enrolled in a Master's programme, PyTorch, written English.",
  "Nice to have: a publication, experience with distributed training.",
].join("\n");

async function openTextMode() {
  fireEvent.click(await screen.findByRole("tab", { name: "Paste the text" }));
  return screen.findByPlaceholderText(/Paste the whole posting/);
}

async function pasteText(text = PASTED) {
  const field = await openTextMode();
  fireEvent.change(field, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Add posting" }));
  return field;
}

describe("adding a posting by pasting its text", () => {
  beforeEach(() => {
    stubApi();
  });

  it("tracks a posting with no link at all, and says it has none", async () => {
    // The one place in the app where a posting may have no URL: the candidate is
    // holding the posting, and refusing it would throw away what they just gave
    // us. What must never happen is it *looking* checked — so the absence is a
    // badge on the posting itself, wherever the posting is shown, rather than a
    // sentence on a card seen once on the way past.
    const linkless = { ...JOB, url: "", url_status: "unchecked", url_http_status: 0 };
    const generate = stubPaste(
      [
        ["run", { run_id: 9 }],
        ["phase", { phase: "reader", message: "Reading the posting…" }],
        ["result", result({ job: linkless, job_id: 13, url_check: { unchecked: 1 }, run_id: 9 })],
      ],
      application({ job: linkless }),
    );
    renderApp("/jobs");
    await pasteText();

    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("no link")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Open posting/ })).toBeNull();
  });

  it("will not start a run on a paste too short to be a posting", async () => {
    const run = vi.fn(() => sseResponse([]));
    stubApi({ "/api/jobs/import-text": run });
    renderApp("/jobs");

    const field = await openTextMode();
    fireEvent.change(field, { target: { value: "ML Research Intern" } });

    // Answered here rather than by a run: the backend refuses this too, but a
    // round trip to be told the paste was short is a round trip wasted.
    expect(await screen.findByText(/18 of 200 characters/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add posting" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(run).not.toHaveBeenCalled();
  });

  it("shows the refusal instead of pretending something was saved", async () => {
    stubApi({
      "/api/jobs/import-text": importRun([
        [
          "error",
          {
            error:
              "That does not read as a single job posting — it looks like a list of roles.",
          },
        ],
      ]),
    });
    const { router } = renderApp("/jobs");
    await pasteText();

    expect(await screen.findByText(/does not read as a single job posting/)).toBeTruthy();
    expect(router.state.location.pathname).toBe("/jobs");
  });

  it("offers all three ways in, on the phone sheet as well as the card", async () => {
    renderApp("/jobs");

    await screen.findByRole("tab", { name: "Paste a link" });
    expect(screen.getByRole("tab", { name: "Paste the text" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Ask the agents" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add a posting, or ask the agents for one" }));
    const sheet = await screen.findByRole("dialog", { name: "Add a posting" });
    expect(within(sheet).getByRole("tab", { name: "Paste the text" })).toBeTruthy();
  });
});

describe("clicking the paste button", () => {
  let originalClipboard: PropertyDescriptor | undefined;

  beforeEach(() => {
    stubApi();
    originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  });

  afterEach(() => {
    if (originalClipboard) {
      Object.defineProperty(navigator, "clipboard", originalClipboard);
    } else {
      // @ts-expect-error test cleanup
      delete navigator.clipboard;
    }
  });

  it("automatically launches import when clicking Paste on a link", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue(LINK),
      },
      configurable: true,
    });

    const generate = stubPaste([
      ["run", { run_id: 7 }],
      ["phase", { phase: "fetch", message: "Opening the link…" }],
      ["result", result()],
    ]);
    const { router } = renderApp("/jobs");

    const pasteBtn = await screen.findByRole("button", { name: "Paste" });
    fireEvent.click(pasteBtn);

    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "Acme" })).toBeTruthy();
    await waitFor(() => expect(router.state.location.pathname).toBe("/applications/42"));
  });

  it("does not launch when clipboard is empty", async () => {
    const run = vi.fn(() => sseResponse([]));
    stubApi({ "/api/jobs/import": run });

    Object.defineProperty(navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue("   "),
      },
      configurable: true,
    });

    renderApp("/jobs");
    const pasteBtn = await screen.findByRole("button", { name: "Paste" });
    fireEvent.click(pasteBtn);

    expect(run).not.toHaveBeenCalled();
  });

  it("automatically launches text import when clicking Paste on text if long enough", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue(PASTED),
      },
      configurable: true,
    });

    const linkless = { ...JOB, url: "", url_status: "unchecked", url_http_status: 0 };
    const generate = stubPaste(
      [
        ["run", { run_id: 9 }],
        ["result", result({ job: linkless, job_id: 13, run_id: 9 })],
      ],
      application({ job: linkless }),
    );

    renderApp("/jobs");
    fireEvent.click(await screen.findByRole("tab", { name: "Paste the text" }));

    const pasteBtn = await screen.findByRole("button", { name: "Paste" });
    fireEvent.click(pasteBtn);

    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("no link")).toBeTruthy();
  });

  it("does not launch text import when clicking Paste on text that is too short", async () => {
    const run = vi.fn(() => sseResponse([]));
    stubApi({ "/api/jobs/import-text": run });

    Object.defineProperty(navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue("ML Research Intern"),
      },
      configurable: true,
    });

    renderApp("/jobs");
    fireEvent.click(await screen.findByRole("tab", { name: "Paste the text" }));

    const pasteBtn = await screen.findByRole("button", { name: "Paste" });
    fireEvent.click(pasteBtn);

    expect(await screen.findByText(/18 of 200 characters/)).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
  });
});

/**
 * The run a paste starts, and the language it starts it in.
 *
 * The guess itself is Python's — `services/language_check.posting_language`, and
 * `backend/tests/test_language_check.py` owns whether it is *right*. What is
 * only checkable from here is that the browser does not overrule it: `auto`
 * means the application's own language, and the failure worth pinning is the
 * silent one, where a hardcoded `en` is sent for a French posting and two
 * documents come back in a language nobody asked for.
 */
describe("the package a paste starts", () => {
  beforeEach(() => {
    stubApi();
  });

  it("writes in the language the posting was written in", async () => {
    // The application was created carrying `fr`, because the posting it was
    // created from is in French.
    stubPaste([["result", result()]], application({ language: "fr" }));
    const sent = generateBodies();
    renderApp("/jobs");
    await paste();

    await waitFor(() => expect(sent.length).toBe(1));
    expect(JSON.parse(sent[0]).language).toBe("fr");
  });

  it("leaves the personalisation note alone rather than asking for one", async () => {
    stubPaste([["result", result()]]);
    const sent = generateBodies();
    renderApp("/jobs");
    await paste();

    await waitFor(() => expect(sent.length).toBe(1));
    // Null, not "": the backend reads null as "leave whatever is stored alone".
    expect(JSON.parse(sent[0]).personalisation).toBeNull();
    // And the dialog does not open. It is asked on the way to generating because
    // that is the one moment you are thinking about the employer — but a path
    // whose whole point is not stopping cannot stop.
    await screen.findByRole("heading", { name: "Acme" });
    expect(screen.queryByRole("dialog", { name: "Anything they should know?" })).toBeNull();
  });

  it("writes the résumé alone — the letter is a box nobody was there to tick", async () => {
    stubPaste([["result", result()]]);
    const sent = generateBodies();
    renderApp("/jobs");
    await paste();

    await waitFor(() => expect(sent.length).toBe(1));
    expect(JSON.parse(sent[0])).toMatchObject({ resume: true, cover_letter: false });
  });

  it("runs once, and leaves nothing behind that would run it again", async () => {
    const generate = stubPaste([["result", result()]]);
    const { router } = renderApp("/jobs");
    await paste();

    // Once, although the effect's dependencies all change as a result of what it
    // does — the language it reads, the parameter it strips.
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    // And what is left in the history is an ordinary application URL, so a
    // reload or a back button is a reload rather than a second two-minute run
    // over the same posting.
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/applications/42");
      expect(router.state.location.search).toBe("");
    });
  });

  it("still takes an explicit language on the URL", async () => {
    // The named form stays beside `auto`: a link that says what it will do is
    // worth one branch, and it is what any second entry point would use.
    stubPaste([["result", result()]], application({ language: "en" }));
    const sent = generateBodies();
    renderApp("/applications/42?generate=fr");

    await waitFor(() => expect(sent.length).toBe(1));
    expect(JSON.parse(sent[0]).language).toBe("fr");
  });
});
