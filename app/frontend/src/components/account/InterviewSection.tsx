import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Markdown, InlineMarkdown } from "../Markdown";
import { Button, Card, ErrorNote, ScoreBadge, SectionTitle, Spinner } from "../ui";
import { api, streamSse } from "../../lib/api";
import type { AppConfig, ChatMessage } from "../../lib/types";
import { jumpToSection } from "./sections";
import { useBriefWriting, useGenerateBrief } from "./useGenerateBrief";

const OPENER =
  "Hi — I'm the Interrogator. Tell me what internship you're after and I'll work out the rest: role, dates, where, and what makes you a strong candidate.";

export function InterviewSection({ onBriefReady }: { onBriefReady?: () => void }) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // Whether the brief being written was the Interrogator's call rather than a
  // click, which is what decides if the Strategy research follows it.
  const [handedOff, setHandedOff] = useState(false);
  // True while *either* side of the page writes a brief — both run the same
  // finaliser over this conversation's session.
  const writing = useBriefWriting();
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: history, isLoading } = useQuery({
    queryKey: ["interview", "history"],
    queryFn: () => api.get<{ messages: ChatMessage[] }>("/api/interview/history"),
  });
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/api/config"),
  });

  useEffect(() => {
    if (history) setMessages(history.messages);
  }, [history]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  async function send() {
    const text = draft.trim();
    if (!text || streaming || writing) return;
    setDraft("");
    setError(null);
    setStreaming(true);
    setMessages((current) => [
      ...current,
      { role: "user", author: "user", text },
      { role: "assistant", author: "interrogator", text: "", pending: true },
    ]);

    // The Interrogator ends the interview itself and says so with a `complete`
    // event. Read here, acted on below — the goodbye it wrote should be on
    // screen before the brief starts being written under it.
    let complete = false;

    try {
      await streamSse("/api/interview/message", { message: text }, (type, data) => {
        if (type === "complete") complete = true;
        if (type === "event" && data.text && !data.partial) {
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.pending) {
              next[next.length - 1] = {
                // A blank line, not a newline: these are separate final events,
                // so they are separate blocks. Joined by a single newline
                // markdown reads them as one paragraph and runs the second
                // event's opening list item onto the end of the first's prose.
                ...last,
                text: last.text ? `${last.text}\n\n${data.text}` : data.text,
              };
            }
            return next;
          });
        }
        if (type === "error") setError(new Error(data.error));
      });
    } catch (streamError) {
      setError(streamError);
    } finally {
      setStreaming(false);
      setMessages((current) =>
        current.map((message) => (message.pending ? { ...message, pending: false } : message)),
      );
      // The turn only lives in local state until this refetch. Without it the
      // cached history goes stale, and coming back to this page after leaving it
      // repaints the conversation as it was before the turn.
      queryClient.invalidateQueries({ queryKey: ["interview", "history"] });
    }

    if (complete) await handOff();
  }

  const finalise = useGenerateBrief();

  /**
   * Write the brief because the Interrogator says the interview is over.
   *
   * This is the only path that carries on into the HR Expert research. The
   * button on the brief side of Strategy writes a brief too, but a click there
   * is someone taking manual control — usually re-writing a brief after an edit
   * — and firing a two-minute grounded run off the back of that would be a
   * surprise, not a convenience.
   */
  async function handOff() {
    if (writing) return;
    setHandedOff(true);
    try {
      await finalise.mutateAsync();
      onBriefReady?.();
    } catch {
      // `finalise.error` is already on screen, and a handoff that fails just
      // stops here — Strategy's button is there to try again by hand.
    }
  }

  const reset = useMutation({
    mutationFn: () => api.post("/api/interview/reset"),
    onSuccess: () => {
      setMessages([]);
      finalise.reset();
      queryClient.invalidateQueries({ queryKey: ["interview", "history"] });
    },
  });

  const visible = messages.filter((message) => message.role === "user" || message.text);

  return (
    <div className="space-y-4">
      <SectionTitle
        title="2 · Interview"
        subtitle="The Interrogator reads your profile, then asks until it understands the internship you want. When it has what it needs it says so, step 3 writes itself, and step 4 researches the playbook from it. Ending the interview early is the button on step 3."
        action={
          <div className="flex w-full gap-2 sm:w-auto">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => reset.mutate()}
              disabled={streaming || writing}
            >
              Start over
            </Button>
          </div>
        }
      />

      <ErrorNote error={error} />
      <ErrorNote error={finalise.error} />

      {config && !config.progress.has_profile ? (
        <Card className="flex flex-wrap items-center gap-3 border-amber-300 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/30">
          <span className="min-w-0 flex-1 text-sm text-amber-900 dark:text-amber-300">
            No profile yet. The Interrogator can still interview you, but it will have to ask
            about your background from scratch and the brief will be thinner for it — import a
            résumé above first.
          </span>
          <Button variant="secondary" onClick={() => jumpToSection("profile")}>
            Back to 1 · Profile ↑
          </Button>
        </Card>
      ) : null}

      {finalise.isPending && handedOff ? (
        <Card className="flex flex-wrap items-center gap-3">
          <Spinner label="The Interrogator has what it needs — writing the search brief…" />
        </Card>
      ) : null}

      {finalise.isSuccess ? (
        <Card className="flex flex-wrap items-center gap-3">
          {finalise.data?.audit?.overall ? (
            <ScoreBadge score={finalise.data.audit.overall} label="Brief audit" />
          ) : null}
          <span className="min-w-0 flex-1 text-sm text-ink-500 dark:text-ink-400">
            {finalise.data?.audit?.reasoning ? (
              <InlineMarkdown>{finalise.data.audit.reasoning}</InlineMarkdown>
            ) : handedOff ? (
              "Search brief saved. The HR Expert is researching the playbook from it below."
            ) : (
              "Search brief saved. You can read and edit it below."
            )}
          </span>
          <Button onClick={() => jumpToSection("brief")}>Continue to 3 · Search brief ↓</Button>
        </Card>
      ) : null}

      {/* svh, not vh or dvh: this panel scrolls inside a page that scrolls, and
          a height that changed every time the phone's URL bar slid away would
          re-lay-out the conversation under the thumb doing the scrolling. */}
      <Card className="flex h-[70svh] flex-col p-0 sm:h-[62vh]">
        <div
          ref={scrollRef}
          className="flex-1 space-y-4 overflow-y-auto overscroll-contain p-4 sm:p-5"
        >
          {isLoading && <Spinner label="Loading conversation…" />}
          {!isLoading && visible.length === 0 && (
            <div className="rounded-lg bg-ink-100 p-4 text-sm dark:bg-ink-800">{OPENER}</div>
          )}
          {visible.map((message, index) => (
            <div
              key={index}
              className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm sm:max-w-[80%] ${
                  message.role === "user"
                    ? "whitespace-pre-wrap bg-accent-600 text-white"
                    : "bg-ink-100 dark:bg-ink-800"
                }`}
              >
                {/* Only the Interrogator's side is markdown. What the candidate
                    typed is literal — "C++ *and* Rust" is two asterisks they
                    meant, and their line breaks are the layout they chose. */}
                {message.role === "user" ? (
                  message.text
                ) : (
                  <Markdown>{message.text}</Markdown>
                )}
                {!message.text && message.pending ? <Spinner label="thinking…" /> : null}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-end gap-2 border-t border-ink-200 p-3 dark:border-ink-800">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            rows={2}
            // Sending mid-finalise would run a second agent in the session the
            // brief writer is reading, and the brief would be written from a
            // transcript that no longer matches what is on screen.
            disabled={writing}
            placeholder={
              writing
                ? "Writing the brief from this conversation…"
                : "Describe the internship you want… (Enter to send, Shift+Enter for a new line)"
            }
            className="min-w-0 flex-1 resize-none rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm outline-none focus:border-accent-500 disabled:opacity-60 dark:border-ink-700 dark:bg-ink-950"
          />
          <Button
            className="shrink-0"
            onClick={() => void send()}
            disabled={streaming || writing || !draft.trim()}
          >
            {streaming ? "…" : "Send"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
