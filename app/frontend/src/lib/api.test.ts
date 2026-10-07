/**
 * The fetch wrapper, and the SSE parser it carries.
 *
 * The parser is the part worth testing: the long runs answer with
 * `text/event-stream` because Cloudflare kills a silent proxied request at 100
 * seconds, and every phase line, every result and every error of those runs
 * arrives through the loop below. It is hand-written framing — there is no
 * library to trust — and when it mis-parses, the run *looks* like it hung.
 */
import { describe, expect, it } from "vitest";

import { ApiError, api, streamSse } from "./api";

function respondWith(body: BodyInit | null, init: ResponseInit = {}): void {
  globalThis.fetch = (async () => new Response(body, init)) as typeof fetch;
}

/** A body delivered in pieces, split where a naive parser would break. */
function chunked(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("api", () => {
  it("returns the parsed body", async () => {
    respondWith(JSON.stringify({ status: "ok" }), { headers: { "Content-Type": "application/json" } });
    await expect(api.get<{ status: string }>("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("turns the backend's `detail` into the error message", async () => {
    respondWith(JSON.stringify({ detail: "GOOGLE_API_KEY is not set" }), { status: 400 });
    await expect(api.get("/api/config")).rejects.toMatchObject({
      name: "ApiError",
      message: "GOOGLE_API_KEY is not set",
      status: 400,
    });
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    respondWith("<html>502</html>", { status: 502, statusText: "Bad Gateway" });
    await expect(api.get("/api/config")).rejects.toBeInstanceOf(ApiError);
  });

  it("reads a 204 as no content rather than failing to parse it", async () => {
    respondWith(null, { status: 204 });
    await expect(api.del("/api/jobs/1")).resolves.toBeUndefined();
  });

  it("declares JSON only when it sends a body, and never for an upload", async () => {
    const seen: RequestInit[] = [];
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      seen.push(init ?? {});
      return new Response(JSON.stringify({}), { headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;

    await api.post("/api/interview/reset");
    await api.post("/api/jobs/search", { query: "internship" });
    await api.upload("/api/profile/upload", new File(["cv"], "cv.pdf"));

    expect(seen.map((init) => (init.headers as Record<string, string>)["Content-Type"])).toEqual([
      undefined,
      "application/json",
      // FormData carries its own multipart boundary; declaring JSON here is how
      // an upload turns into a 422 the user cannot explain.
      undefined,
    ]);
  });
});

describe("streamSse", () => {
  it("parses events split across chunk boundaries", async () => {
    respondWith(chunked('event: phase\ndata: {"phase":"search"', '}\n\nevent: complete\ndata: {"ok":true}\n\n'));

    const events: [string, unknown][] = [];
    await streamSse("/api/jobs/search", {}, (type, data) => events.push([type, data]));

    expect(events).toEqual([
      ["phase", { phase: "search" }],
      ["complete", { ok: true }],
    ]);
  });

  it("ignores the keep-alive comment frames", async () => {
    // The backend sends these so a long-thinking run never looks like a hung
    // origin to Cloudflare. They carry no `data:` line.
    respondWith(chunked(": keep-alive\n\n", ": keep-alive\n\n", 'event: phase\ndata: {"phase":"rank"}\n\n'));

    const events: [string, unknown][] = [];
    await streamSse("/api/jobs/search", {}, (type, data) => events.push([type, data]));

    expect(events).toEqual([["phase", { phase: "rank" }]]);
  });

  it("keeps a data line that is not JSON instead of dropping the event", async () => {
    respondWith(chunked("event: token\ndata: hello\n\n"));

    const events: [string, unknown][] = [];
    await streamSse("/api/interview/reply", {}, (type, data) => events.push([type, data]));

    expect(events).toEqual([["token", "hello"]]);
  });

  it("defaults an unnamed frame to `message` and joins multi-line data", async () => {
    respondWith(chunked("data: one\ndata: two\n\n"));

    const events: [string, unknown][] = [];
    await streamSse("/api/interview/reply", {}, (type, data) => events.push([type, data]));

    expect(events).toEqual([["message", "one\ntwo"]]);
  });

  it("raises a run rejected before the stream starts as an ordinary error", async () => {
    respondWith(JSON.stringify({ detail: "Unknown language: de" }), { status: 422 });

    await expect(streamSse("/api/jobs/search", {}, () => {})).rejects.toMatchObject({
      message: "Unknown language: de",
      status: 422,
    });
  });
});
