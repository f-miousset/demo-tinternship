import { Badge, BulletList, Card, ScoreBadge } from "./ui";
import { Markdown } from "./Markdown";
import type { AuditSummary } from "../lib/types";

/**
 * One Critic verdict, rendered the same way wherever it is shown.
 *
 * The application artifacts, the search brief and the hiring playbook are all
 * scored against a rubric by the same Critic, so they get the same panel: the
 * weighted score, the verdict, the reasoning, a bar per criterion, and whatever
 * the Critic still wants fixed. `title` names the subject when the panel is not
 * already sitting under one.
 */
export function AuditPanel({
  audit,
  title,
  className = "",
}: {
  audit: AuditSummary | null;
  title?: string;
  className?: string;
}) {
  if (!audit) return null;
  const criteria = audit.scores?.criteria ?? [];
  return (
    <Card className={`space-y-3 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <ScoreBadge score={audit.overall} label={title ?? "Audit"} threshold={audit.threshold} />
        <Badge tone={audit.verdict === "pass" ? "good" : audit.verdict === "fail" ? "bad" : "warn"}>
          {audit.verdict}
        </Badge>
        {audit.rubric && <Badge>{audit.rubric}</Badge>}
        {audit.revision ? <Badge tone="info">{audit.revision} revision(s)</Badge> : null}
      </div>
      {audit.scores?.reasoning && (
        <Markdown className="text-sm text-ink-600 dark:text-ink-300">
          {audit.scores.reasoning}
        </Markdown>
      )}
      {criteria.length > 0 && (
        <div className="space-y-1.5">
          {criteria.map((criterion) => (
            <div key={criterion.criterion} className="flex items-center gap-2 text-sm sm:gap-3">
              <span className="w-24 shrink-0 truncate text-xs text-ink-500 sm:w-40 sm:text-sm">
                {criterion.criterion}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                <div
                  className={`h-full rounded-full ${
                    criterion.score >= 7
                      ? "bg-emerald-500"
                      : criterion.score >= 5
                        ? "bg-amber-500"
                        : "bg-red-500"
                  }`}
                  style={{ width: `${Math.max(0, Math.min(100, criterion.score * 10))}%` }}
                />
              </div>
              <span className="w-8 text-right tabular-nums">{criterion.score.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
      {audit.fixes && audit.fixes.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700">
            Outstanding notes from the Critic
          </h4>
          <BulletList items={audit.fixes} />
        </div>
      )}
    </Card>
  );
}
