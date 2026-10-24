"use client";

import { useId } from "react";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface DegradedRunBannerProps {
  /** V5.8: one sentence per LLM role that ran degraded, then each fix once (summary.degraded_notices). */
  notices?: string[];
}

/** Only the confirm role's same-family fallback queues its confirmations for human review. */
function queuesReview(notices: string[]): boolean {
  return notices.some((n) => n.startsWith("confirm:") && n.includes("human review"));
}

/** Says the run was degraded (e.g. an OpenAI account without credits), as the DOCX report's "Degraded mode" section. */
export function DegradedRunBanner({ notices }: DegradedRunBannerProps) {
  const titleId = useId();
  const shown = notices ?? [];
  // The live region stays mounted (empty on a normal run): one that mounts together with
  // its content is often not announced, and the notices arrive after the results fetch.
  return (
    <div role="status" aria-live="polite">
      {shown.length > 0 && (
        <Card role="region" aria-labelledby={titleId}
          className="gap-0 py-3 border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950">
          <CardContent className="flex gap-3 px-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
            <div className="min-w-0 space-y-1.5 text-sm text-amber-950 dark:text-amber-50">
              <h3 id={titleId} className="font-medium">This run ran in degraded mode</h3>
              <ul className="list-disc space-y-1 pl-4 break-words">
                {shown.map((notice, idx) => <li key={idx}>{notice}</li>)}
              </ul>
              <p className="text-xs text-amber-800 dark:text-amber-200">
                Some model calls were skipped or ran on a fallback model, so results may be less
                accurate than a normal run.
                {queuesReview(shown) && " Results the same-family cross-check confirmed are queued for human review."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
