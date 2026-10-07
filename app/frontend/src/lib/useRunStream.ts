import { useCallback, useRef, useState } from "react";

import { streamSse } from "./api";
import type { RunPhase } from "./types";

/**
 * Drive one of the streaming run endpoints — the Investigator, the Applying team.
 *
 * Both take minutes, so they answer with server-sent events rather than one
 * blocking POST: a response that says nothing for 100 seconds is cut off by the
 * proxy in front of the app even though the run finishes and saves its work.
 * The events double as progress — a `phase` line per stage, `result` at the end.
 *
 * Nothing here aborts the request when the component unmounts. The run carries
 * on server-side either way, and dropping the connection would only throw away
 * the view of it.
 */
export function useRunStream<T>() {
  const [running, setRunning] = useState(false);
  const [phases, setPhases] = useState<RunPhase[]>([]);
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [runId, setRunId] = useState<number | null>(null);
  // State updates are batched, so `running` cannot be trusted to stop a second
  // click on the same tick from starting a second run.
  const inFlight = useRef(false);

  /** Resolves with the run's result, or null if it failed — state lags a tick. */
  const start = useCallback(async (path: string, body?: unknown): Promise<T | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    setRunning(true);
    setPhases([]);
    setResult(null);
    setError(null);
    setRunId(null);

    let value: T | null = null;
    try {
      await streamSse(path, body, (type, data) => {
        if (type === "run") setRunId(data?.run_id ?? null);
        else if (type === "phase") setPhases((current) => [...current, data as RunPhase]);
        else if (type === "result") {
          value = data as T;
          setResult(data as T);
        } else if (type === "error") setError(new Error(data?.error ?? "The run failed."));
      });
    } catch (streamError) {
      setError(streamError);
    } finally {
      inFlight.current = false;
      setRunning(false);
    }
    return value;
  }, []);

  const reset = useCallback(() => {
    setPhases([]);
    setResult(null);
    setError(null);
    setRunId(null);
  }, []);

  return { running, phases, result, error, runId, start, reset };
}
