/**
 * Finding one application on the Tracker board.
 *
 * The filtering happens here rather than as a query parameter on
 * `/api/applications`, because the board is already one fetch of every row: the
 * whole list is in the browser before the first keystroke, and a round trip per
 * character would make a field that has to feel instant depend on a network
 * that — installed to the home screen, read on a train — is sometimes not there
 * at all.
 *
 * What it searches is deliberately wider than what a board card prints and
 * narrower than what the row holds. Wider, because the card is a summary: the
 * city, the contract type and the keywords are all things you would type and
 * none of them is on it. Narrower, because `job.description` is the posting in
 * full — several hundred words of boilerplate per application, in which
 * "engineer", "stage" or "équipe" matches every row at once and the filter has
 * stopped filtering. `summary` is the one line that says what the role is, and
 * that is the prose worth searching.
 */
import { isInterview, STATUS_LABEL } from "./statuses";
import type { Application } from "./types";

/**
 * Lower-cased, unaccented, punctuation flattened to spaces.
 *
 * Accents because half of this board is in French and nobody reaches for `é` on
 * a phone keyboard held one-handed — typing "donnees" has to find "Données".
 * Punctuation because these fields are machine-written as often as they are
 * human-written: `google_search` and "Lyon, France" both have to answer to the
 * words inside them.
 */
function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/** Everything one application answers to, folded into a single string. */
function haystack(application: Application): string {
  const job = application.job;
  // `join` turns a missing field into nothing at all, so an application whose
  // posting failed to serialise still matches on your own notes rather than
  // throwing.
  return fold(
    [
      job?.title,
      job?.company,
      job?.location,
      job?.remote,
      job?.contract_type,
      job?.source,
      job?.summary,
      job?.keywords?.join(" "),
      // The status, so a word already printed on a column header narrows to it:
      // "offer" is a search as much as it is a column. Its label too, so
      // "technical" finds `technical_test`, and "interview" for every round —
      // the pre-call and the test are interviews whatever their name says.
      application.status,
      STATUS_LABEL[application.status],
      isInterview(application.status) ? "interview" : "",
      // Your own writing — the half of the row no agent ever touched, and the
      // half you are most likely to remember a row by.
      application.notes,
      application.next_action,
      application.personalisation,
    ].join(" "),
  );
}

/**
 * The board, narrowed to the rows matching every word of `query`.
 *
 * Every word has to appear somewhere, in any order and across any fields:
 * "nimbus intern" finds the ML internship at Nimbus Labs whether the two words
 * sit in one field or three fields apart, which is how you type a search for a
 * row you half-remember. Matching *any* word instead would hand back most of
 * the board and call it a result.
 *
 * An empty or whitespace-only query returns the list untouched — the same array
 * instance, so React sees no change where the user made none.
 */
export function searchApplications(
  applications: Application[],
  query: string,
): Application[] {
  const words = fold(query).split(" ").filter(Boolean);
  if (words.length === 0) return applications;
  return applications.filter((application) => {
    const text = haystack(application);
    return words.every((word) => text.includes(word));
  });
}
