"use client";

import { Card, CardContent } from "@/components/ui/card";
import { CostSummaryCard } from "@/components/refcheck/cost-summary-card";
import type { CostSummary, VerificationResult } from "@/lib/types";

export function ResultsLoadingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-10 bg-muted rounded w-full" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-12 bg-muted/60 rounded w-full" />
      ))}
    </div>
  );
}

export function SummaryCard({
  label,
  count,
  color,
  bg,
}: {
  label: string;
  count: number;
  color: string;
  bg: string;
}) {
  return (
    <Card className={bg}>
      <CardContent className="pt-4 text-center">
        <p className={`text-3xl font-bold ${color}`}>{count}</p>
        <p className="text-xs text-muted-foreground mt-1">{label}</p>
      </CardContent>
    </Card>
  );
}

export function CostFromResults({ results }: { results: VerificationResult[] }) {
  const withVoting = results.filter(
    (r) => r.total_models_consulted && r.total_models_consulted > 0,
  );
  if (withVoting.length === 0) return null;

  const totalModels = withVoting.reduce(
    (s, r) => s + (r.total_models_consulted ?? 0), 0,
  );
  const escalated = withVoting.filter(
    (r) => r.final_tier !== undefined && r.final_tier > 0,
  ).length;

  const tierCounts: Record<number, number> = {};
  for (const r of withVoting) {
    const t = r.final_tier ?? 0;
    tierCounts[t] = (tierCounts[t] ?? 0) + (r.total_models_consulted ?? 0);
  }

  const costData: CostSummary = {
    total_usd: 0,
    total_calls: totalModels,
    by_model: {},
    by_task: {},
    by_tier: tierCounts,
  };

  return <CostSummaryCard cost={costData} escalatedCount={escalated} />;
}
