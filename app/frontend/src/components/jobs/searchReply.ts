import type { SearchResult } from "../../lib/types";

/**
 * One exchange in the Jobs chat.
 *
 * `agents` turns are written here from the run's own result rather than by a
 * model — there is no chat agent, and inventing one would put a second voice
 * between the candidate and the four that did the work. The reply is what the
 * run actually did: how many postings it scored, how many are new, and the
 * Matcher's `strategy_notes` in its own words.
 */
export type ChatTurn = { role: "you" | "agents"; text: string };

/**
 * What a finished run says back.
 *
 * A run that came back with nothing gets a sentence rather than a zero: on a
 * deck this deep into a search that is the *normal* answer — every posting it
 * found was already answered — and it is worth saying which lever moves it.
 */
export function replyTo(result: SearchResult | null): string {
  if (!result) return "That run did not finish. The note below says what went wrong.";

  const found = result.jobs?.length ?? 0;
  const created = result.saved?.created ?? 0;
  if (found === 0) {
    return (
      "Nothing came back for that — either no posting matched, or everything found is " +
      "already on your deck. Naming a different company, a wider location or another " +
      "kind of role is usually what moves it."
    );
  }

  const head =
    created === found
      ? `${found} posting${found === 1 ? "" : "s"} added to your deck.`
      : `${found} posting${found === 1 ? "" : "s"} scored, ${created} of them new on your deck.`;
  return result.strategy_notes ? `${head}\n\n${result.strategy_notes}` : head;
}
