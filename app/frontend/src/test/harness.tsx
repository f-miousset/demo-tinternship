/**
 * Mounting the real app against a fake API.
 *
 * `renderApp("/jobs")` puts the production route table (`src/routes.tsx`) under
 * a memory router and a real `QueryClient`, with `fetch` answering from a table
 * of canned bodies. That combination is the point: it is the only check in this
 * repo that runs React, React Router and TanStack Query together, so a major
 * bump in any of them fails here rather than in the browser after a deploy.
 *
 * Endpoints that are not in the table answer **404**, not an empty object. A
 * wrong-shaped body would make a page throw for a reason the real API could
 * never produce; a 404 is a state every screen already has to handle.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import type { AppConfig, Application, Job } from "../lib/types";
import { QUERY_DEFAULTS, routes } from "../routes";

/** One uploaded base document with room left on its page. */
function baseDocument(id: number, label: string) {
  return {
    id,
    label,
    status: "parsed",
    error: "",
    on_disk: true,
    created_at: "2026-08-28T09:00:00+00:00",
    placeholders: 4,
    page: "About 96% of one page, with room for roughly 266 more characters once the blanks are filled.",
    room: 266,
    crowded: false,
    language_warning: "",
  };
}

/** A fully set-up account: nothing is gated, no warning banner. */
export const CONFIG: AppConfig = {
  models: { primary: "gemini-3-pro", fast: "gemini-3-flash", grounded: "gemini-3-flash" },
  gemini_configured: true,
  job_sources: ["google_search", "adzuna"],
  priority_platforms: ["welcometothejungle"],
  results: { default: 15, min: 5, max: 40 },
  base_resumes: {
    en: baseDocument(1, "cv-en.docx"),
    fr: baseDocument(2, "cv-fr.docx"),
  },
  base_cover_letters: {
    en: baseDocument(3, "cover-letter-en.docx"),
    fr: baseDocument(4, "lettre-fr.docx"),
  },
  audit: { threshold: 7, max_revisions: 2 },
  progress: {
    has_base_resumes: true,
    has_base_letters: true,
    has_profile: true,
    has_lists: true,
    has_interview: true,
    has_brief: true,
    has_playbook: true,
    complete: true,
  },
  warnings: [],
};

/** Empty-but-valid bodies: the shape every screen must survive on day one. */
const DEFAULT_BODIES: [RegExp, unknown][] = [
  [/^\/api\/config$/, CONFIG],
  [/^\/api\/account$/, {
    authenticated: false,
    username: "",
    display_name: "",
    email: "",
    groups: [],
    setup: CONFIG.progress,
  }],
  [/^\/api\/applications\/follow-ups$/, { after_days: 14, follow_ups: [] }],
  [/^\/api\/applications\/\d+\/artifacts$/, { artifacts: [] }],
  [/^\/api\/applications$/, { applications: [] }],
  [/^\/api\/jobs\/search\/history(\/.*)?$/, { items: [] }],
  [/^\/api\/jobs\b/, { jobs: [], sources: [] }],
  [/^\/api\/profile$/, {
    profile: {},
    has_profile: true,
    sources: [],
    base_resumes: {
      en: baseDocument(1, "cv-en.docx"),
      fr: baseDocument(2, "cv-fr.docx"),
    },
    base_cover_letters: {
      en: baseDocument(3, "cover-letter-en.docx"),
      fr: baseDocument(4, "lettre-fr.docx"),
    },
  }],
  // Two saved items, one per list, each in both languages. Enough that the
  // Account page renders a non-empty list without every test having to say so.
  [/^\/api\/profile\/lists$/, {
    lists: {
      course: [{
        id: 1,
        kind: "course",
        en: "Operations Research and Combinatorial Optimisation",
        fr: "Recherche opérationnelle, optimisation combinatoire",
        position: 0,
      }],
      skill: [{ id: 2, kind: "skill", en: "Data Analysis", fr: "Analyse de données", position: 0 }],
    },
  }],
  [/^\/api\/interview\/history$/, { messages: [] }],
  [/^\/api\/strategy\/prompts$/, { prompts: [] }],
  [/^\/api\/strategy\/prompts\/active$/, {}],
  [/^\/api\/settings\/config$/, {
    fields: [],
    model_options: [],
    ollama: { base_url: "http://127.0.0.1:11434", reachable: false, in_use: false },
  }],
  [/^\/api\/traces\/runs$/, { runs: [] }],
  [/^\/api\/traces\/audits\b/, { audits: [] }],
  [/^\/api\/traces\/stats$/, {
    runs: 0,
    failed_runs: 0,
    trace_events: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    llm_calls: 0,
    tool_calls: 0,
    by_kind: [],
    audit_by_kind: [],
  }],
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * One server-sent-event stream, as the streaming endpoints answer with.
 *
 * `streamSse` reads `response.body`, so a canned JSON body cannot stand in for
 * a run: this builds the real wire format instead, and a test hands it to
 * `stubApi` to drive a page's progress lines and result card without a server.
 */
export function sseResponse(events: [string, unknown][]): Response {
  const body = events
    .map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/**
 * Install the fake API. `overrides` is keyed by exact path and wins over the
 * defaults, so a test says only what it cares about:
 * `stubApi({ "/api/config": { ...CONFIG, gemini_configured: false } })`.
 *
 * An override may be a `Response` (or a function returning one) when the shape
 * matters more than the body — a stream, or a status the page branches on.
 *
 * The function form is handed the full URL, query string included, and the
 * `RequestInit` the caller sent. The URL because `/api/jobs` is one path serving
 * three views (`deck`, `discarded`, `all`), and a stub that could not tell them
 * apart could not test the trash. The init because some of what a page does is
 * only visible in what it *sends* — the Jobs chat's whole job is putting a focus
 * in the body of a search.
 */
let defaultSearchHistory: Array<{ id: string; text: string; timestamp: number }> = [];

export function stubApi(overrides: Record<string, unknown> = {}): void {
  defaultSearchHistory = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const full = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (path in overrides) {
      const override = overrides[path];
      if (typeof override === "function") {
        return (override as (url: string, init?: RequestInit) => Response)(full, init);
      }
      if (override instanceof Response) return override;
      return json(override);
    }

    if (path === "/api/jobs/search/history") {
      if (method === "GET") {
        return json({ items: defaultSearchHistory });
      }
      if (method === "POST") {
        const payload = init?.body ? JSON.parse(String(init.body)) : {};
        const text = String(payload.text ?? "").trim();
        if (text) {
          defaultSearchHistory = [
            { id: String(Date.now()), text, timestamp: Date.now() },
            ...defaultSearchHistory.filter((i) => i.text.toLowerCase() !== text.toLowerCase()),
          ];
        }
        return json({ items: defaultSearchHistory });
      }
      if (method === "DELETE") {
        defaultSearchHistory = [];
        return json({ deleted_count: 0 });
      }
    }

    if (/^\/api\/jobs\/search\/history\/\w+$/.test(path) && method === "DELETE") {
      const id = path.split("/").pop();
      defaultSearchHistory = defaultSearchHistory.filter((i) => i.id !== id);
      return json({ deleted: true, id });
    }

    if (path === "/api/jobs/search/history/sync" && method === "POST") {
      const payload = init?.body ? JSON.parse(String(init.body)) : {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      for (const item of items) {
        if (item.text) {
          defaultSearchHistory = [
            { id: String(Date.now()), text: item.text, timestamp: item.timestamp ?? Date.now() },
            ...defaultSearchHistory.filter((i) => i.text.toLowerCase() !== item.text.toLowerCase()),
          ];
        }
      }
      return json({ items: defaultSearchHistory });
    }

    for (const [pattern, body] of DEFAULT_BODIES) {
      if (pattern.test(full) || pattern.test(path)) return json(body);
    }
    return json({ detail: `No stub for ${full}` }, 404);
  }) as typeof fetch;
}

/**
 * The real routes, the real providers, a memory history starting at `path`.
 *
 * Returns the router alongside the render result, because some of what a page
 * does is only visible in the history: a page that strips a query parameter as
 * it acts on it — `?generate=` on an application — leaves nothing in the DOM to
 * assert on, and `window.location` is not where a memory router writes.
 */
export function renderApp(path = "/jobs") {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = new QueryClient({
    defaultOptions: {
      ...QUERY_DEFAULTS,
      // The one deliberate difference from production: a retry would only add a
      // second of latency before the same assertion.
      queries: { ...QUERY_DEFAULTS.queries, retry: false },
    },
  });
  return {
    ...render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
    router,
  };
}

/** A posting with every field filled, for a test to override the few it is about. */
export function job(id: number, title: string, company: string, overrides: Partial<Job> = {}): Job {
  return {
    id,
    title,
    company,
    location: "Lyon, France",
    remote: "hybrid",
    url: "",
    apply_url: "",
    source: "google_search",
    description: "",
    summary: "",
    requirements: [],
    nice_to_have: [],
    contract_type: "internship",
    start_date: "",
    duration: "",
    compensation: "",
    language: "en",
    posted_at: "",
    posted_on: "",
    posted_days_ago: null,
    deadline: "",
    fit_score: 0,
    fit_rationale: "",
    strengths: [],
    risks: [],
    keywords: [],
    confidence: "high",
    url_status: "ok",
    url_http_status: 200,
    dismissed: false,
    deferred_at: null,
    run_id: null,
    invocation_id: "",
    discovered_at: "2026-08-25T09:00:00+00:00",
    application_id: id,
    ...overrides,
  };
}

/** An application on the board around `posting`, `applied` unless overridden. */
export function application(id: number, posting: Job, overrides: Partial<Application> = {}): Application {
  return {
    id,
    job_posting_id: posting.id,
    status: "applied",
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
    job: posting,
    artifacts: [],
    timeline: [],
    ...overrides,
  };
}
