/**
 * Responses as the real API sends them — JSON, errors, and SSE streams.
 *
 * A stream is the backend's wire format (`api/sse.py::format_event`) paced the
 * way a run is: a `run` event, a `phase` line per stage a second or so apart,
 * then `result`. Real runs take minutes; these take seconds, because watching a
 * demo think for three minutes teaches nothing the first ten seconds did not.
 */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function error(detail: string, status = 400): Response {
  return json({ detail }, status);
}

export function text(body: string): Response {
  return new Response(body, { status: 200, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

export type StreamStep =
  | { event: string; data: unknown; delay?: number }
  | { produce: () => Promise<{ event: string; data: unknown }[]>; delay?: number };

/** Milliseconds between stream steps. Zero under test, where nobody is watching. */
export let pace = 900;
export function setPace(ms: number): void {
  pace = ms;
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * A server-sent-event response that writes its steps over time.
 *
 * A step may be a function, so the work behind a `result` — saving the
 * application, adding the trace — happens when the stream reaches it, not when
 * the request is made: a visitor who leaves the page mid-run finds the same
 * state they would after a real one that finished without them.
 */
export function sse(steps: StreamStep[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const step of steps) {
          await wait(Math.round((step.delay ?? 1) * pace));
          const events = "produce" in step ? await step.produce() : [step];
          for (const { event, data } of events) {
            controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
          }
        }
      } catch (failure) {
        const message = failure instanceof Error ? failure.message : String(failure);
        controller.enqueue(encoder.encode(`event: error\ndata: ${JSON.stringify({ error: message })}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}
