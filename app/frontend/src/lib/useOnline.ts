import { useEffect, useState } from "react";

/**
 * Whether the browser thinks it has a network.
 *
 * Worth showing on a phone: every screen here is a view of data the API holds,
 * so offline they all fail at once, and "no network" is a much better answer
 * than five copies of a fetch error. It is a hint, not a guarantee — the browser
 * only knows about its own interface, not about the tunnel at the other end.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  return online;
}
