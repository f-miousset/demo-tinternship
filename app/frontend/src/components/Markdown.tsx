/**
 * Agent prose, rendered as the markdown it actually is.
 *
 * Every agent here writes to a person: the Interrogator asks its two-to-four
 * questions as a numbered list, the Critic labels each note in bold, the Matcher
 * names a company as a link. That is markdown, whatever the instruction asks
 * for, and printing it verbatim in a `whitespace-pre-wrap` box shows the reader
 * the asterisks instead of the emphasis they stand for.
 *
 * Two entry points, because agent text arrives in two shapes:
 *
 * - `Markdown` for a whole message — the chat bubble. Blocks are laid out.
 * - `InlineMarkdown` for one field of a structured answer — a fit rationale, an
 *   audit's reasoning, a bullet in a list the page has already styled. Those
 *   live inside a sentence-shaped slot the page controls, so only the inline
 *   marks are honoured and a paragraph renders as bare text rather than opening
 *   a `<p>` inside whatever element is already around it.
 *
 * Nothing goes near `dangerouslySetInnerHTML`: react-markdown builds React
 * elements, and raw HTML in the source is left as text unless a plugin opts into
 * it, which none here does.
 */

import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Links leave the app, and the ones in agent output are job postings and company
 * sites — untrusted enough that the tab they open must not keep a handle on this
 * one.
 */
function Anchor({ href, children }: { href?: string; children?: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent-600 underline underline-offset-2 dark:text-accent-400"
    >
      {children}
    </a>
  );
}

/**
 * Block styling.
 *
 * Spacing is set on the children rather than with `space-y` on a wrapper so that
 * a one-paragraph message — most of them — has no stray margin above or below it
 * inside its bubble.
 *
 * The list markers are the point of the whole exercise: `list-decimal` restores
 * the numbering the model wrote, and `marker:` keeps it from competing with the
 * text it numbers.
 */
const BLOCK: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0 marker:text-ink-400">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0 marker:text-ink-400">{children}</ol>
  ),
  // Nested lists sit against their parent item, not a blank line away from it.
  li: ({ children }) => <li className="[&>ol]:mb-0 [&>ol]:mt-1 [&>ul]:mb-0 [&>ul]:mt-1">{children}</li>,
  // Headings in a chat message are a section label, not a title — a model that
  // opens with `## Role focus` means it to read one step louder than the prose,
  // and an h1-sized line in a bubble is shouting.
  h1: ({ children }) => <h3 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h3>,
  h4: ({ children }) => (
    <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide opacity-70 first:mt-0">
      {children}
    </h4>
  ),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: Anchor,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-ink-300 pl-3 opacity-80 last:mb-0 dark:border-ink-600">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-ink-200 dark:border-ink-700" />,
  // `code` covers both the inline span and the body of a fence; only the fenced
  // one is wrapped in a `pre`, which is where the scrolling belongs.
  code: ({ children }) => (
    <code className="rounded bg-black/10 px-1 py-0.5 font-mono text-[0.9em] dark:bg-white/10">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-3 overflow-x-auto rounded-lg bg-black/10 p-3 text-xs last:mb-0 dark:bg-white/10 [&_code]:bg-transparent [&_code]:p-0">
      {children}
    </pre>
  ),
  // A table cannot reflow to 360px, so it scrolls inside its own box rather than
  // taking the page sideways with it.
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-left">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-ink-300 px-2 py-1 font-semibold dark:border-ink-600">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-ink-200 px-2 py-1 dark:border-ink-800">{children}</td>
  ),
};

/**
 * Inline styling.
 *
 * Everything that would open a block is flattened to its contents: this text is
 * already inside a `<p>` or an `<li>` the page laid out, and a nested one is
 * invalid HTML that React will happily render and the browser will happily
 * un-nest, moving the text somewhere nobody styled.
 */
const passthrough = ({ children }: { children?: ReactNode }) => <>{children}</>;

const INLINE: Components = {
  p: passthrough,
  h1: passthrough,
  h2: passthrough,
  h3: passthrough,
  h4: passthrough,
  h5: passthrough,
  h6: passthrough,
  blockquote: passthrough,
  strong: BLOCK.strong,
  em: BLOCK.em,
  code: BLOCK.code,
  a: Anchor,
  // A model that answers a one-line field with a list still means a list, so
  // keep it — just without the top margin a mid-sentence block would introduce.
  ul: ({ children }) => <ul className="mt-1 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mt-1 list-decimal space-y-0.5 pl-5">{children}</ol>,
};

/** A whole agent message: paragraphs, lists, emphasis, links, the lot. */
export function Markdown({ children, className = "" }: { children?: string | null; className?: string }) {
  if (!children) return null;
  return (
    // `break-words`: an unbroken URL or a 40-character identifier is otherwise
    // wider than a phone, and one of them would scroll the whole page sideways.
    <div className={`break-words ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={BLOCK}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** One field of an agent's answer, rendered into the slot the page gave it. */
export function InlineMarkdown({ children }: { children?: string | null }) {
  if (!children) return null;
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={INLINE}>
      {children}
    </ReactMarkdown>
  );
}
