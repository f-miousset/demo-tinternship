/** Thin fetch wrapper. Everything is same-origin thanks to the Vite proxy. */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The backend's `detail` if it sent one, the status text otherwise. */
async function apiError(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  try {
    const body = await response.json();
    detail = body.detail ?? JSON.stringify(body);
  } catch {
    /* non-JSON error body — keep the status text */
  }
  return new ApiError(detail, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) throw await apiError(response);

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestText(path: string): Promise<string> {
  const response = await fetch(path);
  if (!response.ok) throw await apiError(response);
  return await response.text();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  /** The one endpoint that answers with prose rather than JSON: a document's
   *  text, which is copied to the clipboard verbatim. Wrapping it in JSON would
   *  only be a second escaping of something already exactly what it is. */
  getText: (path: string) => requestText(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};

/**
 * Consume an SSE stream from a POST endpoint.
 *
 * EventSource only does GET, and these runs need a request body, so this parses
 * the `event:`/`data:` framing off a fetch body stream by hand. Comment frames
 * (`: keep-alive`, which the backend sends so a long-thinking run never looks
 * like a hung origin to a proxy) carry no `data:` line and fall through.
 */
export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (type: string, data: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  // A run that is rejected before it starts — an unknown language, a missing
  // application — answers with an ordinary JSON error, so read it as one.
  if (!response.ok) throw await apiError(response);
  if (!response.body) {
    throw new ApiError("The server sent no stream to read.", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      let eventType = "message";
      const dataLines: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      try {
        onEvent(eventType, JSON.parse(dataLines.join("\n")));
      } catch {
        onEvent(eventType, dataLines.join("\n"));
      }
    }
  }
}
