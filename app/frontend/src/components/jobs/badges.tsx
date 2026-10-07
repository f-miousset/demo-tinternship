import { Badge } from "../ui";
import type { Job } from "../../lib/types";

/**
 * How old the posting is, in the words a person uses for it.
 *
 * The unit changes with the magnitude because the precision does: "3 days" is
 * something you act on today, "4 months" is a warning, and nobody needs to know
 * it was 118 days.
 */
function ageLabel(days: number): string {
  if (days <= 0) return "posted today";
  if (days === 1) return "posted yesterday";
  if (days < 14) return `posted ${days} days ago`;
  if (days < 60) return `posted ${Math.round(days / 7)} weeks ago`;
  return `posted ${Math.round(days / 30)} months ago`;
}

/**
 * The posting's age, which the ranking weighs as heavily as the match itself.
 *
 * Undated postings get no badge at all rather than an "unknown" one: it is the
 * normal case for anything found through search, the ranking treats it as
 * middle-aged rather than suspect, and a badge on most cards would say nothing.
 */
export function AgeBadge({ days }: { days: number | null }) {
  if (days === null) return null;
  const tone = days <= 7 ? "good" : days <= 45 ? "info" : "warn";
  return (
    <Badge
      tone={tone}
      title={
        days <= 45
          ? "Recent postings are ranked well above older ones — the role is far more likely to still be open."
          : "This posting is old enough that the role has probably been filled. It survived the ranking anyway, which means it is a strong match or nothing fresher was found."
      }
    >
      {ageLabel(days)}
    </Badge>
  );
}

/**
 * Whether the posting's link actually resolves — the anti-hallucination signal.
 *
 * `url` is optional and answers a different question from `status`: whether
 * there is a link at all. A posting pasted as text may have none — the one place
 * in the app where a posting is saved without one, because the candidate is
 * holding the posting itself — and **it must never look like one that was
 * checked**. Silence would do exactly that, since `unchecked` renders nothing,
 * so the absence is said out loud wherever a posting is shown: the deck card,
 * the details sheet and the application page all render this.
 */
export function UrlStatusBadge({
  status,
  code,
  url,
}: {
  status: Job["url_status"];
  code: number;
  url?: string;
}) {
  if (url !== undefined && !url) {
    return (
      <Badge
        tone="warn"
        title="This posting was pasted as text and the text carried no link, so there is nothing to open and nothing was checked. Everything else on it was read from what you pasted."
      >
        no link
      </Badge>
    );
  }
  if (status === "ok") {
    return (
      <Badge tone="good" title="This link was fetched and resolved successfully">
        link verified
      </Badge>
    );
  }
  if (status === "dead") {
    return (
      <Badge
        tone="bad"
        title={`This URL returned ${code || 404}. Runs drop these before you see them, so this is an older posting or one whose link has broken since — check the company's careers page directly.`}
      >
        link dead ({code || 404})
      </Badge>
    );
  }
  if (status === "index") {
    return (
      <Badge
        tone="bad"
        title="This link resolves, but not to the posting — it lands on the company's careers page or a search page. Runs drop these before you see them, so this is an older posting or one whose link has broken since."
      >
        link misses the posting
      </Badge>
    );
  }
  if (status === "blocked") {
    return (
      <Badge
        tone="warn"
        title={`The site answered ${code} with bot protection instead of the posting, so this link could not be checked at all. It is not evidence either way — some links in this state are live and some are 404. Open it to find out.`}
      >
        link unchecked
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge tone="warn" title="The link could not be reached (DNS, timeout or TLS failure)">
        link unreachable
      </Badge>
    );
  }
  return null;
}
