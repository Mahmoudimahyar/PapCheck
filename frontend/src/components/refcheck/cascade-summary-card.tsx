"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DECIDED_BY_LABELS, formatUsd } from "@/lib/cascade";
import type { DecidedBy, VerificationResult } from "@/lib/types";

const ORDER: DecidedBy[] = ["screen", "verifier", "judge", "none"];
const BAR_COLORS: Record<DecidedBy, string> = {
  screen: "bg-sky-500",
  verifier: "bg-violet-500",
  judge: "bg-indigo-500",
  none: "bg-gray-400",
};

/** V5: who decided each pair (fast screen / verifier / judge), cost and agreement. */
export function CascadeSummaryCard({ results }: { results: VerificationResult[] }) {
  const total = results.length;
  const counts: Record<DecidedBy, number> = { screen: 0, verifier: 0, judge: 0, none: 0 };
  for (const r of results) counts[r.decided_by ?? "none"] += 1;
  const cost = results.reduce((s, r) => s + (r.cost_usd ?? 0), 0);
  const decided = total - counts.none;
  const confirmed = results.filter((r) => r.confirmation === "confirmed").length;
  const disputed = results.filter((r) => r.confirmation === "disputed").length;
  const unconfirmed = results.filter((r) => r.confirmation === "unconfirmed").length;

  return (
    <Card>
      <CardHeader className="pb-2 pt-4 px-4">
        <h3 className="text-sm font-semibold">Verification Cascade</h3>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-bold">{formatUsd(cost)}</span>
          <span className="text-xs text-muted-foreground">
            {decided > 0 ? `${formatUsd(cost / decided)} per checked pair` : `${total} pairs`}
          </span>
        </div>

        <div className="space-y-1.5">
          {ORDER.filter((d) => counts[d] > 0).map((d) => {
            const pct = total > 0 ? (counts[d] / total) * 100 : 0;
            return (
              <div key={d} className="flex items-center gap-2 text-xs">
                <span className="w-24 text-muted-foreground truncate">
                  {d === "none" ? "No LLM verdict" : DECIDED_BY_LABELS[d]}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                  <div className={`h-full rounded-full ${BAR_COLORS[d]}`} style={{ width: `${Math.max(pct, 1)}%` }} />
                </div>
                <span className="w-20 text-right text-muted-foreground tabular-nums">
                  {counts[d]} ({pct.toFixed(0)}%)
                </span>
              </div>
            );
          })}
        </div>

        {(confirmed > 0 || disputed > 0 || unconfirmed > 0) && (
          <div className="pt-2 border-t flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {confirmed > 0 && <span>{confirmed} confirmed by 2 model families</span>}
            {disputed > 0 && <span className="text-amber-700 dark:text-amber-400">{disputed} disputed</span>}
            {unconfirmed > 0 && (
              <span className="text-amber-700 dark:text-amber-400">{unconfirmed} unconfirmed</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
