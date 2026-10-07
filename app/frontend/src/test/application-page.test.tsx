/**
 * Opening an application shows the posting, and asking for a package asks first.
 *
 * Everything that costs a model call on this page is a button, and this file is
 * where that stays true: the package, the shortlist, and — since 2026-09-03 —
 * the message to each person on it.
 *
 * Three behaviours land on this page and none of them is visible from a type
 * check. The posting is rendered by the same component the Jobs deck uses, so
 * the moment you decide to apply is not the moment the app stops telling you
 * what you are applying to. Generating opens a dialog before it starts a run —
 * a contact on the team is the most useful sentence in the whole prompt and it
 * is only in mind at that one moment. And moving the status to Interview starts
 * the Interview Coach on its own, because a brief you have to remember to ask
 * for is a brief you read on the train instead of the night before.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderApp, sseResponse, stubApi } from "./harness";
import type { Application, Artifact, Job } from "../lib/types";

const JOB: Job = {
  id: 4,
  title: "Machine Learning Intern",
  company: "Nimbus Labs",
  location: "Lyon, France",
  remote: "hybrid",
  url: "https://nimbus.test/jobs/4",
  apply_url: "https://nimbus.test/jobs/4/apply",
  source: "google_search",
  description: "Six months on the training platform team.",
  summary: "Build and maintain the training pipelines behind their vision models.",
  requirements: ["Python", "PyTorch"],
  nice_to_have: ["Kubernetes"],
  contract_type: "internship",
  start_date: "March 2027",
  duration: "6 months",
  compensation: "1 300 €/month",
  language: "en",
  posted_at: "3 days ago",
  posted_on: "2026-08-25",
  posted_days_ago: 3,
  deadline: "",
  fit_score: 8.2,
  fit_rationale: "Strong on data engineering, thin on ML frameworks.",
  strengths: ["Python and SQL are already on the profile"],
  risks: ["No PyTorch anywhere in the profile"],
  keywords: ["python", "pytorch"],
  confidence: "high",
  url_status: "ok",
  url_http_status: 200,
  dismissed: false,
  deferred_at: null,
  run_id: 9,
  invocation_id: "inv-9",
  discovered_at: "2026-08-25T09:00:00+00:00",
  application_id: 1,
};

function application(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    job_posting_id: 4,
    status: "saved",
    pinned: false,
    language: "en",
    personalisation: "",
    notes: "",
    next_action: "",
    next_action_date: "",
    applied_at: null,
    trashed_at: null,
    created_at: "2026-08-26T09:00:00+00:00",
    updated_at: "2026-08-26T09:00:00+00:00",
    job: JOB,
    artifacts: [],
    timeline: [],
    ...overrides,
  };
}

const CONTACTS_ARTIFACT: Artifact = {
  id: 21,
  kind: "contacts",
  version: 1,
  revisions: 0,
  rendered_path: "",
  created_at: "2026-08-29T09:00:00+00:00",
  run_id: null,
  invocation_id: "",
  audit: null,
  content: {
    people: [
      {
        name: "Claire Dupont",
        role: "Campus Manager",
        category: "campus",
        why: "She runs the internship programme.",
        opening_line: "Bonjour Claire, INSA Lyon too — I have just applied for the ML internship.",
        confidence: "high",
        linkedin_url: "https://www.linkedin.com/in/claire-dupont",
        evidence_url: "https://nimbus.test/team",
        profile_status: "verified",
        evidence_status: "live",
        search_url: "https://www.linkedin.com/search/results/people/?keywords=Claire",
        web_url: "https://www.google.com/search?q=Claire",
      },
      {
        name: "Marc Petit",
        role: "Tech Lead",
        category: "team",
        why: "He leads the platform team.",
        opening_line: "",
        confidence: "medium",
        linkedin_url: "",
        evidence_url: "https://nimbus.test/blog",
        profile_status: "unproved",
        evidence_status: "live",
        search_url: "https://www.linkedin.com/search/results/people/?keywords=Marc",
        web_url: "https://www.google.com/search?q=Marc",
      },
    ],
    dropped: [{ name: "Ghost Person", role: "", reason: "nothing that could be fetched actually names them" }],
    angles: [
      {
        key: "alumni",
        label: "Nimbus Labs people who went to INSA Lyon",
        why: "A shared school needs no introduction.",
        keywords: '"Nimbus Labs" "INSA Lyon"',
        url: "https://www.linkedin.com/search/results/people/?keywords=alumni",
      },
    ],
    company: {
      slug: "nimbus-labs",
      url: "https://www.linkedin.com/company/nimbus-labs/",
      people_url: "https://www.linkedin.com/company/nimbus-labs/people/",
      recruiters_url: "https://www.linkedin.com/company/nimbus-labs/people/?keywords=recruiter",
    },
    approach: ["Message Claire first, then apply."],
    notes: "",
    sources: [{ title: "Nimbus — team", url: "https://nimbus.test/team", takeaway: "Names the campus manager." }],
    checked: { people_named: 3, profiles_verified: 1, dropped: 1, searches: 6 },
    language: "en",
  },
};

const PREP_ARTIFACT: Artifact = {
  id: 12,
  kind: "interview_prep",
  version: 1,
  revisions: 0,
  rendered_path: "",
  created_at: "2026-08-28T09:00:00+00:00",
  run_id: null,
  invocation_id: "",
  audit: null,
  content: {
    company_brief: "Nimbus Labs builds training infrastructure for computer-vision teams.",
    pitch: "Start with the ingest pipeline at Acme, then why Nimbus.",
    gaps: [{ gap: "No PyTorch", severity: "significant", honest_answer: "Say so, then bridge.", preparation: "" }],
    likely_questions: [
      { question: "Walk me through your ingest pipeline.", asked_by: "hiring manager", why_asked: "", answer_outline: ["Scope", "What broke"], evidence: [] },
    ],
    questions_to_ask: ["How is the platform team split from research?"],
    sources: [{ title: "Nimbus — about", url: "https://nimbus.test/about", takeaway: "What they build." }],
    recent_developments: [],
    interview_process: [],
    strengths_to_lead_with: [],
    technical_topics: [],
    logistics: [],
    red_flags_to_probe: [],
    language: "en",
  },
};

describe("the application page", () => {
  beforeEach(() => {
    stubApi({ "/api/applications/1": application() });
  });

  it("leads with the company, the role and the one-line summary", async () => {
    renderApp("/applications/1");

    expect(await screen.findByRole("heading", { name: "Nimbus Labs" })).toBeTruthy();
    expect(screen.getByText("Machine Learning Intern")).toBeTruthy();
    expect(
      screen.getByText(/Build and maintain the training pipelines/),
    ).toBeTruthy();
  });

  it("shows the same assessment the deck card showed", async () => {
    renderApp("/applications/1");

    // Why this score, the strengths, the risks and the requirements — the
    // things you swiped right on and would otherwise have to go back for.
    expect(await screen.findByText("Why this score")).toBeTruthy();
    expect(screen.getByText(/thin on ML frameworks/)).toBeTruthy();
    expect(screen.getByText("Python and SQL are already on the profile")).toBeTruthy();
    expect(screen.getByText("No PyTorch anywhere in the profile")).toBeTruthy();
    expect(screen.getByText("PyTorch")).toBeTruthy();
  });

  it("no longer offers a Screening status", async () => {
    renderApp("/applications/1");

    await screen.findByRole("heading", { name: "Nimbus Labs" });
    expect(screen.queryByRole("button", { name: "screening" })).toBeNull();
    expect(screen.queryByRole("button", { name: "interview" })).toBeNull();
    expect(screen.getByRole("button", { name: "HR pre-call" })).toBeTruthy();
  });

  it("has no application-plan tab", async () => {
    renderApp("/applications/1");

    await screen.findByRole("heading", { name: "Nimbus Labs" });
    expect(screen.queryByRole("button", { name: /Application plan/ })).toBeNull();
  });

  describe("generating a package", () => {
    /** A résumé on the row: what *Add a cover letter* is offered beside. */
    const RESUME_ARTIFACT: Artifact = {
      id: 41,
      kind: "resume",
      version: 1,
      revisions: 0,
      rendered_path: "",
      created_at: "2026-09-18T09:00:00+00:00",
      run_id: null,
      invocation_id: "",
      audit: null,
      content: { language: "en", blocks: [], slots: [], fills: [] },
    };

    it("asks what you know before it starts the run", async () => {
      const generate = vi.fn(() => sseResponse([["result", { artifacts: {}, run_id: 1 }]]));
      stubApi({ "/api/applications/1": application(), "/api/applications/1/generate": generate });
      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );

      expect(await screen.findByRole("dialog", { name: "Anything they should know?" })).toBeTruthy();
      // Nothing has been asked of the backend yet — the dialog is a gate, not a
      // notification about a run already in flight.
      expect(generate).not.toHaveBeenCalled();
    });

    it("sends what was typed with the run", async () => {
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/generate": () => sseResponse([["result", { artifacts: {}, run_id: 1 }]]),
      });
      const inner = globalThis.fetch;
      globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/generate")) bodies.push(String(init?.body ?? ""));
        return inner(input, init);
      }) as typeof fetch;

      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );
      fireEvent.change(
        await screen.findByRole("textbox", { name: "What you know about this employer" }),
        { target: { value: "I know their data lead." } },
      );
      fireEvent.click(screen.getByRole("button", { name: "Generate résumé" }));

      await waitFor(() => expect(bodies.length).toBe(1));
      expect(JSON.parse(bodies[0]).personalisation).toBe("I know their data lead.");
    });

    it("writes the résumé alone unless the box is ticked", async () => {
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/generate": () => sseResponse([["result", { artifacts: {}, run_id: 1 }]]),
      });
      const inner = globalThis.fetch;
      globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/generate")) bodies.push(String(init?.body ?? ""));
        return inner(input, init);
      }) as typeof fetch;

      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );
      // The box exists, and it is off: the letter is the expensive half of the
      // run and most application forms have nowhere to put one.
      const box = await screen.findByRole("checkbox", { name: /Write a cover letter too/ });
      expect((box as HTMLInputElement).checked).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Generate résumé" }));

      await waitFor(() => expect(bodies.length).toBe(1));
      expect(JSON.parse(bodies[0]).cover_letter).toBe(false);
    });

    it("ticking the box asks for both documents", async () => {
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/generate": () => sseResponse([["result", { artifacts: {}, run_id: 1 }]]),
      });
      const inner = globalThis.fetch;
      globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/generate")) bodies.push(String(init?.body ?? ""));
        return inner(input, init);
      }) as typeof fetch;

      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );
      fireEvent.click(await screen.findByRole("checkbox", { name: /Write a cover letter too/ }));
      fireEvent.click(screen.getByRole("button", { name: "Generate both" }));

      await waitFor(() => expect(bodies.length).toBe(1));
      expect(JSON.parse(bodies[0]).cover_letter).toBe(true);
    });

    it("offers a letter-only run once there is a résumé and no letter", async () => {
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [RESUME_ARTIFACT] },
        "/api/applications/1/generate": () => sseResponse([["result", { artifacts: {}, run_id: 1 }]]),
      });
      const inner = globalThis.fetch;
      globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/generate")) bodies.push(String(init?.body ?? ""));
        return inner(input, init);
      }) as typeof fetch;

      renderApp("/applications/1");

      fireEvent.click(await screen.findByRole("button", { name: "Add a cover letter" }));
      // The same dialog — the question is the same — but with the box replaced
      // by what it will do, because there is nothing left to choose.
      expect(screen.queryByRole("checkbox", { name: /Write a cover letter too/ })).toBeNull();
      fireEvent.click(await screen.findByRole("button", { name: "Write the cover letter" }));

      await waitFor(() => expect(bodies.length).toBe(1));
      // The résumé on the row is the one that was reviewed. Re-writing it to
      // get a letter beside it would spend a run producing the same document.
      expect(JSON.parse(bodies[0])).toMatchObject({ resume: false, cover_letter: true });
    });

    it("does not offer it when there is nothing to add it to, or a letter already", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [] },
      });
      const { unmount } = renderApp("/applications/1");

      await screen.findByRole("button", { name: "Generate application package" });
      expect(screen.queryByRole("button", { name: "Add a cover letter" })).toBeNull();
      unmount();

      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": {
          artifacts: [RESUME_ARTIFACT, { ...RESUME_ARTIFACT, id: 42, kind: "cover_letter" }],
        },
      });
      renderApp("/applications/1");

      await screen.findByRole("button", { name: "Regenerate package" });
      expect(screen.queryByRole("button", { name: "Add a cover letter" })).toBeNull();
    });

    it("saves what the run produced without being asked", async () => {
      // Every one of these is on its way to an attachment field, and the run
      // takes two minutes — coming back to press Download is the step this
      // removes. Résumé first, then the letter.
      const clicks: string[] = [];
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
        this: HTMLAnchorElement,
      ) {
        clicks.push(this.getAttribute("href") ?? "");
      });
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/generate": () =>
          sseResponse([
            [
              "result",
              {
                artifacts: {
                  resume: { id: 51, kind: "resume", version: 1 },
                  cover_letter: { id: 52, kind: "cover_letter", version: 1 },
                },
                run_id: 1,
              },
            ],
          ]),
      });

      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );
      fireEvent.click(await screen.findByRole("checkbox", { name: /Write a cover letter too/ }));
      fireEvent.click(screen.getByRole("button", { name: "Generate both" }));

      await waitFor(() =>
        expect(clicks).toEqual([
          "/api/applications/artifacts/51/export",
          "/api/applications/artifacts/52/export",
        ]),
      );
    });

    it("cancelling starts nothing", async () => {
      const generate = vi.fn(() => sseResponse([["result", { artifacts: {}, run_id: 1 }]]));
      stubApi({ "/api/applications/1": application(), "/api/applications/1/generate": generate });
      renderApp("/applications/1");

      fireEvent.click(
        await screen.findByRole("button", { name: "Generate application package" }),
      );
      fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

      await waitFor(() =>
        expect(screen.queryByRole("dialog", { name: "Anything they should know?" })).toBeNull(),
      );
      expect(generate).not.toHaveBeenCalled();
    });
  });

  describe("finding people to contact", () => {
    it("starts nothing until the button is pressed", async () => {
      const contacts = vi.fn(() =>
        sseResponse([
          ["phase", { phase: "researching", message: "Looking for the people…" }],
          ["result", { artifact: { id: 21, kind: "contacts", version: 1 }, run_id: 7 }],
        ]),
      );
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/contacts": contacts,
      });
      renderApp("/applications/1");

      // Opening the application spends nothing. It is a grounded research run,
      // and re-reading a posting is not asking for one.
      const button = await screen.findByRole("button", { name: "Find people to contact" });
      expect(contacts).not.toHaveBeenCalled();

      fireEvent.click(button);
      await waitFor(() => expect(contacts).toHaveBeenCalled());
    });

    it("offers Look again on the tab rather than a second start button", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [CONTACTS_ARTIFACT] },
      });
      renderApp("/applications/1");

      expect(await screen.findByText("Claire Dupont")).toBeTruthy();
      // One control, in the place it belongs: two buttons meaning the same
      // thing in two places is worse than one in the right place.
      expect(screen.queryByRole("button", { name: "Find people to contact" })).toBeNull();
      expect(screen.getByRole("button", { name: "Look again" })).toBeTruthy();
    });

    it("says so when the research failed and only the searches survived", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": {
          artifacts: [
            {
              ...CONTACTS_ARTIFACT,
              content: {
                ...CONTACTS_ARTIFACT.content,
                people: [],
                dropped: [],
                degraded: "The agent produced no shortlist.",
              },
            },
          ],
        },
      });
      renderApp("/applications/1");

      // A failed run that saved the searches must not look like a run that
      // simply found nobody.
      expect(await screen.findByText(/The research did not finish/)).toBeTruthy();
      expect(
        screen.getByRole("link", { name: "Nimbus Labs people who went to INSA Lyon ↗" }),
      ).toBeTruthy();
    });

    it("only links to a profile that was actually opened and confirmed", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [CONTACTS_ARTIFACT] },
      });
      renderApp("/applications/1");

      // Claire's profile was fetched and the page was titled with her name, so
      // it is offered as a link.
      const profile = await screen.findByRole("link", { name: "Open their profile ↗" });
      expect(profile.getAttribute("href")).toBe("https://www.linkedin.com/in/claire-dupont");
      // Marc's could not be proved. There is exactly one profile link on the
      // page, and he gets a search instead — a link that opens the wrong person
      // costs precisely the time this feature exists to save.
      expect(screen.getAllByRole("link", { name: "Open their profile ↗" }).length).toBe(1);
      expect(screen.getByRole("link", { name: "Find them on LinkedIn ↗" })).toBeTruthy();
      expect(screen.getByText("search only")).toBeTruthy();
    });

    it("shows the built searches, and says who was left off", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [CONTACTS_ARTIFACT] },
      });
      renderApp("/applications/1");

      const alumni = await screen.findByRole("link", {
        name: "Nimbus Labs people who went to INSA Lyon ↗",
      });
      expect(alumni.getAttribute("href")).toContain("/search/results/people/");
      expect(screen.getByRole("link", { name: "Everyone who works there ↗" })).toBeTruthy();
      // A list that silently shrank looks exactly like a search that found less.
      expect(screen.getByText(/Ghost Person/)).toBeTruthy();
    });

    it("writes nobody's message until that person's button is pressed", async () => {
      const write = vi.fn(() =>
        new Response(
          JSON.stringify({
            opening_line: "Bonjour Marc, votre article sur le pipeline…",
            over_limit: false,
            artifact_id: 21,
            index: 1,
            name: "Marc Petit",
            run_id: 31,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [CONTACTS_ARTIFACT] },
        "/api/applications/1/contacts/message": (_url: string, init?: RequestInit) => {
          bodies.push(String(init?.body ?? ""));
          return write();
        },
      });
      renderApp("/applications/1");

      // Marc has no message. Rendering the shortlist did not write one, and
      // pressing nothing spends nothing.
      await screen.findByText("Marc Petit");
      const button = screen.getByRole("button", { name: "Write the message" });
      expect(write).not.toHaveBeenCalled();

      fireEvent.click(button);

      await waitFor(() => expect(write).toHaveBeenCalled());
      // Both halves of the join: the position, and who was standing in it.
      expect(JSON.parse(bodies[0])).toEqual({ index: 1, name: "Marc Petit" });
    });

    it("offers to rewrite the one message that exists, and to write the one that does not", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [CONTACTS_ARTIFACT] },
      });
      renderApp("/applications/1");

      // Claire's was asked for at some point and is stored on the shortlist;
      // Marc's has not been. Exactly one of each control, and the count that
      // matters is that "Write the message" is not offered twice.
      expect(await screen.findByText(/Bonjour Claire, INSA Lyon too/)).toBeTruthy();
      expect(screen.getAllByRole("button", { name: "Write the message" }).length).toBe(1);
      expect(screen.getAllByRole("button", { name: "Write it again" }).length).toBe(1);
    });

    it("says so plainly when nobody could be named", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": {
          artifacts: [
            {
              ...CONTACTS_ARTIFACT,
              content: {
                ...CONTACTS_ARTIFACT.content,
                people: [],
                dropped: [],
                checked: { people_named: 0, profiles_verified: 0, dropped: 0, searches: 6 },
              },
            },
          ],
        },
      });
      renderApp("/applications/1");

      expect(await screen.findByText(/No individual could be named/)).toBeTruthy();
      // The searches are the floor: they still work.
      expect(
        screen.getByRole("link", { name: "Nimbus Labs people who went to INSA Lyon ↗" }),
      ).toBeTruthy();
    });
  });

  describe("reaching an interview round", () => {
    it("starts the Interview Coach without being asked twice", async () => {
      const prep = vi.fn(() =>
        sseResponse([
          ["phase", { phase: "researching", message: "Researching the employer…" }],
          ["result", { artifact: { id: 12, kind: "interview_prep", version: 1 }, run_id: 5 }],
        ]),
      );
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/interview-prep": prep,
      });
      renderApp("/applications/1");

      fireEvent.click(await screen.findByRole("button", { name: "HR pre-call" }));

      await waitFor(() => expect(prep).toHaveBeenCalled());
    });

    it("starts it from whichever round comes first, since a process may skip some", async () => {
      // No HR rounds at all: straight from applied to the manager.
      const prep = vi.fn(() => sseResponse([["result", { artifact: {}, run_id: 5 }]]));
      stubApi({
        "/api/applications/1": application({ status: "applied" }),
        "/api/applications/1/interview-prep": prep,
      });
      renderApp("/applications/1");

      fireEvent.click(await screen.findByRole("button", { name: "Manager interview" }));

      await waitFor(() => expect(prep).toHaveBeenCalled());
    });

    it("does not start it again when a brief already exists", async () => {
      const prep = vi.fn(() => sseResponse([["result", { artifact: {}, run_id: 5 }]]));
      stubApi({
        "/api/applications/1": application({ status: "hr_pre_call" }),
        "/api/applications/1/artifacts": { artifacts: [PREP_ARTIFACT] },
        "/api/applications/1/interview-prep": prep,
      });
      renderApp("/applications/1");

      // Moving on to a later round is not a reason to write the brief twice.
      fireEvent.click(await screen.findByRole("button", { name: "Manager interview" }));

      // A second round is worth its own version, but that is a grounded
      // research run the candidate asks for — "Prepare again" is right there.
      await waitFor(() => expect(screen.getByRole("button", { name: "Prepare again" })).toBeTruthy());
      expect(prep).not.toHaveBeenCalled();
    });

    it("renders the brief, and every source as a link you can open", async () => {
      stubApi({
        "/api/applications/1": application({ status: "technical_test" }),
        "/api/applications/1/artifacts": { artifacts: [PREP_ARTIFACT] },
      });
      renderApp("/applications/1");

      expect(await screen.findByText("“Tell me about yourself”")).toBeTruthy();
      expect(screen.getByText(/Nimbus Labs builds training infrastructure/)).toBeTruthy();
      expect(screen.getByText("Walk me through your ingest pipeline.")).toBeTruthy();
      const source = screen.getByRole("link", { name: "Nimbus — about" });
      expect(source.getAttribute("href")).toBe("https://nimbus.test/about");
    });

    it("warns rather than staying quiet when the brief cites nothing", async () => {
      stubApi({
        "/api/applications/1": application({ status: "technical_test" }),
        "/api/applications/1/artifacts": {
          artifacts: [{ ...PREP_ARTIFACT, content: { ...PREP_ARTIFACT.content, sources: [] } }],
        },
      });
      renderApp("/applications/1");

      expect(await screen.findByText(/This brief cites nothing/)).toBeTruthy();
    });
  });

  describe("your notes", () => {
    it("keeps what you wrote, separately from the timeline", async () => {
      stubApi({
        "/api/applications/1": application({ notes: "1 400 €/month, mentioned on the call." }),
      });
      renderApp("/applications/1");

      const field = await screen.findByRole("textbox", { name: "Your notes" });
      expect((field as HTMLTextAreaElement).value).toBe("1 400 €/month, mentioned on the call.");
      // And the timeline's own note field is still there and still empty: one
      // records an event, the other is what you know.
      expect(
        screen.getByPlaceholderText(/This note feeds the Investigator/),
      ).toBeTruthy();
    });

    it("saves the note it is holding, and not before", async () => {
      const bodies: string[] = [];
      stubApi({
        "/api/applications/1": (_url: string, init?: RequestInit) => {
          if (init?.method === "PATCH") bodies.push(String(init.body ?? ""));
          return new Response(JSON.stringify(application()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        },
      });
      renderApp("/applications/1");

      const field = await screen.findByRole("textbox", { name: "Your notes" });
      // Nothing typed is nothing to save — the button is the gate.
      expect(screen.getByRole("button", { name: "Save notes" }).hasAttribute("disabled")).toBe(
        true,
      );

      fireEvent.change(field, { target: { value: "Ask about the team split." } });
      fireEvent.click(screen.getByRole("button", { name: "Save notes" }));

      await waitFor(() => expect(bodies.length).toBe(1));
      expect(JSON.parse(bodies[0])).toEqual({ notes: "Ask about the team split." });
    });

    it("auto-resizes to fit its content", async () => {
      stubApi({
        "/api/applications/1": application({ notes: "Line 1\nLine 2\nLine 3\nLine 4\nLine 5" }),
      });
      renderApp("/applications/1");

      const field = (await screen.findByRole("textbox", {
        name: "Your notes",
      })) as HTMLTextAreaElement;

      expect(field.className).toContain("resize-none");
      expect(field.className).toContain("overflow-hidden");
      expect(field.className).toContain("[field-sizing:content]");

      // Under engines lacking native field-sizing (like jsdom), the layout effect
      // sets inline height from scrollHeight
      Object.defineProperty(field, "scrollHeight", { configurable: true, value: 160 });
      Object.defineProperty(field, "offsetHeight", { configurable: true, value: 162 });
      Object.defineProperty(field, "clientHeight", { configurable: true, value: 160 });

      fireEvent.change(field, { target: { value: "More notes added to trigger resize" } });
      expect(field.style.height).toBe("162px");
    });
  });

  describe("the Tracker's trash", () => {
    it("moves the application to it without touching anything else", async () => {
      const urls: string[] = [];
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/trash": (url: string) => {
          urls.push(url);
          return new Response(JSON.stringify(application({ trashed_at: "2026-09-08T09:00:00+00:00" })), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        },
      });
      renderApp("/applications/1");

      fireEvent.click(await screen.findByRole("button", { name: "Move to trash" }));

      await waitFor(() => expect(urls.length).toBe(1));
      expect(urls[0]).toContain("trashed=true");
    });

    it("says so on the application, and offers it back", async () => {
      // The page still works — everything below the banner is live — so
      // without this line there is nothing to explain why the board dropped it.
      stubApi({
        "/api/applications/1": application({
          status: "applied",
          trashed_at: "2026-09-08T09:00:00+00:00",
        }),
      });
      renderApp("/applications/1");

      expect(await screen.findByText("This application is in the trash")).toBeTruthy();
      expect(screen.getByText(/returns it to the “applied” column/)).toBeTruthy();
      expect(screen.getByRole("button", { name: "Put back on the board" })).toBeTruthy();
      // One control at a time: it is already there.
      expect(screen.queryByRole("button", { name: "Move to trash" })).toBeNull();
    });
  });

  describe("the finished cover letter", () => {
    /** A letter as it is saved today: the candidate's own .docx, blanks filled. */
    const LETTER_ARTIFACT: Artifact = {
      id: 31,
      kind: "cover_letter",
      version: 2,
      revisions: 0,
      rendered_path: "",
      created_at: "2026-09-09T09:00:00+00:00",
      run_id: null,
      invocation_id: "",
      audit: null,
      content: {
        language: "en",
        document_title: "Cover letter",
        blocks: [{ index: 0, text: "Dear [recipient]," }],
        slots: [
          { key: "s0", token: "[recipient]", block: 0, start: 5, end: 16, line: "Dear [recipient]," },
        ],
        fills: [{ slot: "s0", text: "Nimbus Labs hiring team" }],
      },
    };

    const LETTER_TEXT = "Dear Nimbus Labs hiring team,\n\nYour work on training infrastructure…";

    /** jsdom has no clipboard at all. Hand back the writes it was asked for. */
    function stubClipboard(writeText = vi.fn(async () => {})) {
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText },
        writable: true,
        configurable: true,
      });
      return writeText;
    }

    beforeEach(() => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": { artifacts: [LETTER_ARTIFACT] },
        "/api/applications/artifacts/31/text": () =>
          new Response(LETTER_TEXT, { headers: { "Content-Type": "text/plain" } }),
      });
    });

    it("copies the letter as the backend assembled it, not as the page guessed", async () => {
      const writeText = stubClipboard();
      renderApp("/applications/1");

      const copy = await screen.findByRole("button", { name: "Copy text" });
      // The text is fetched with the tab, so the button is dead until it lands:
      // a `writeText` after an await is one Safari refuses.
      await waitFor(() => expect((copy as HTMLButtonElement).disabled).toBe(false));
      fireEvent.click(copy);

      await waitFor(() => expect(writeText).toHaveBeenCalledWith(LETTER_TEXT));
      expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    });

    it("says the clipboard refused rather than looking like nothing happened", async () => {
      // There is no selectable copy of the letter on the page — the preview is
      // an iframe — so a silent failure would be the whole message.
      stubClipboard(vi.fn(async () => {
        throw new Error("denied");
      }));
      renderApp("/applications/1");

      const copy = await screen.findByRole("button", { name: "Copy text" });
      await waitFor(() => expect((copy as HTMLButtonElement).disabled).toBe(false));
      fireEvent.click(copy);

      expect(await screen.findByRole("button", { name: "Clipboard refused" })).toBeTruthy();
    });

    it("offers nothing to copy on the résumé, which is attached rather than pasted", async () => {
      stubApi({
        "/api/applications/1": application(),
        "/api/applications/1/artifacts": {
          artifacts: [{ ...LETTER_ARTIFACT, id: 32, kind: "resume" }],
        },
      });
      renderApp("/applications/1");

      expect(await screen.findByText("Download .docx")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Copy text" })).toBeNull();
    });
  });
});
