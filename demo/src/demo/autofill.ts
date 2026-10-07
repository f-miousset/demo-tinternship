/**
 * Tapping a box the agents read fills it with something they have an answer for.
 *
 * The demo's agents are pre-written, so a visitor who types their own question
 * would mostly meet "the demo has nothing for that". Instead, focusing an
 * *empty* box that feeds an agent fills it with a prompt the demo can answer —
 * the next Jobs-chat search, the suggested link, the next interview answer —
 * and the visitor only has to press Send. Anything they type over it is still
 * sent, and still answered as well as a canned demo can.
 *
 * Boxes are found by what the app already labels them with (placeholder,
 * aria-label), so the app's components stay unmodified. If a resync renames
 * one, `autofill.test.ts` fails rather than the box silently going quiet.
 */
import { nextInterviewLine } from "../mock/routes";
import { loadSeed, store } from "../mock/store";

type Rule = { match: (element: HTMLTextAreaElement | HTMLInputElement) => boolean; text: () => Promise<string>; hint: string };

const placeholder = (prefix: string) => (element: HTMLTextAreaElement | HTMLInputElement) =>
  (element.getAttribute("placeholder") ?? "").startsWith(prefix);

export const RULES: Rule[] = [
  {
    // components/jobs/SearchChat.tsx — the Jobs chat.
    match: placeholder("A company, a kind of role"),
    text: async () => {
      const [seed, state] = await Promise.all([loadSeed(), store()]);
      const next = seed.searches.find((search) => search.prompt && !state.searched.includes(search.key));
      return (next ?? seed.searches.find((search) => search.prompt))?.prompt ?? "";
    },
    hint: "Suggested search filled in — press Enter to send it to the agents.",
  },
  {
    // components/jobs/AddLinkForm.tsx — paste a link.
    match: placeholder("Paste a job posting link"),
    text: async () => (await loadSeed()).link_import,
    hint: "A posting's link filled in — send it and the Reader will score it.",
  },
  {
    // components/jobs/AddTextForm.tsx — paste a posting's text.
    match: placeholder("Paste the whole posting"),
    text: async () => (await loadSeed()).text_import,
    hint: "A posting's text filled in — send it and the Reader will score it.",
  },
  {
    // components/account/InterviewSection.tsx — the Interrogator.
    match: placeholder("Describe the internship you want"),
    text: nextInterviewLine,
    hint: "Your next answer is filled in — press Enter to reply to the Interrogator.",
  },
  {
    // routes/ApplicationPage.tsx — the note the Generate dialog asks for.
    match: (element) => element.getAttribute("aria-label") === "What you know about this employer",
    text: async () => (await loadSeed()).personalisation.en,
    hint: "A note for the writers filled in — it is optional.",
  },
];

/** React owns the value: set it through the native setter and announce it, as typing would. */
function setValue(element: HTMLTextAreaElement | HTMLInputElement, value: string): void {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  const end = value.length;
  try {
    element.setSelectionRange(end, end);
  } catch {
    /* type="url" inputs do not support a selection */
  }
}

export function installAutofill(onHint: (message: string) => void): () => void {
  async function onFocus(event: FocusEvent) {
    const element = event.target;
    if (!(element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement)) return;
    if (element.value || element.disabled || element.readOnly) return;
    const rule = RULES.find((candidate) => candidate.match(element));
    if (!rule) return;
    const value = await rule.text();
    // Still focused and still empty: the visitor may have started typing.
    if (!value || element.value || document.activeElement !== element) return;
    setValue(element, value);
    onHint(rule.hint);
  }
  document.addEventListener("focusin", onFocus);
  return () => document.removeEventListener("focusin", onFocus);
}
