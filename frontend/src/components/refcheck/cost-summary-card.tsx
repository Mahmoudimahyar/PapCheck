"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { CostSummary } from "@/lib/types";
import { TIER_LABELS } from "@/lib/verdict-colors";

interface CostSummaryCardProps {
  cost: CostSummary;
  escalatedCount?: number;
}

export function CostSummaryCard({ cost, escalatedCount }: CostSummaryCardProps) {
  const totalCalls = cost.total_calls;
  const tierEntries = Object.entries(cost.by_tier)
    .map(([tier, count]) => ({
      tier: Number(tier),
      count: count as number,
      pct: totalCalls > 0 ? ((count as number) / totalCalls) * 100 : 0,
    }))
    .sort((a, b) => a.tier - b.tier);

  return (
    <Card>
      <CardHeader className="pb-2 pt-4 px-4">
        <h3 className="text-sm font-semibold">Verification Cost</h3>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-bold">${cost.total_usd.toFixed(2)}</span>
          <span className="text-xs text-muted-foreground">
            {totalCalls.toLocaleString()} calls · {Object.keys(cost.by_model).length} models
          </span>
        </div>

        <div className="space-y-1.5">
          {tierEntries.map(({ tier, count, pct }) => (
            <div key={tier} className="flex items-center gap-2 text-xs">
              <span className="w-20 text-muted-foreground truncate">
                {TIER_LABELS[tier] ?? `Tier ${tier}`}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.max(pct, 1)}%` }}
                />
              </div>
              <span className="w-20 text-right text-muted-foreground tabular-nums">
                {count.toLocaleString()} ({pct.toFixed(0)}%)
              </span>
            </div>
          ))}
        </div>

        <div className="pt-2 border-t flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {Object.entries(cost.by_model).map(([model, modelCost]) => (
            <span key={model}>
              {model} ${(modelCost as number).toFixed(2)}
            </span>
          ))}
        </div>

        {escalatedCount !== undefined && escalatedCount > 0 && (
          <p className="text-xs text-muted-foreground">
            {escalatedCount} claim{escalatedCount > 1 ? "s" : ""} escalated
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Inline cost display for pipeline progress. */
export function PipelineCostLine({
  verified,
  total,
  costUsd,
  escalated,
}: {
  verified: number;
  total: number;
  costUsd: number;
  escalated: number;
}) {
  return (
    <div className="text-sm text-muted-foreground">
      Verifying: {verified}/{total} claims
      {costUsd > 0 && <> · Cost: ${costUsd.toFixed(2)}</>}
      {escalated > 0 && <> · {escalated} escalated</>}
    </div>
  );
}
