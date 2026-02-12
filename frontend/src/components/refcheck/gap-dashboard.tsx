"use client";

import { Badge } from "@/components/ui/badge";
import type { Reference } from "@/lib/types";

interface GapDashboardProps {
  references: Reference[];
}

export function GapDashboard({ references }: GapDashboardProps) {
  const matched = references.filter((r) => r.pdf_path).length;
  const found = references.filter((r) => r.source_status === "found").length;
  const notFound = references.filter((r) => r.source_status === "not_found").length;
  const errors = references.filter((r) => r.source_status === "api_error").length;
  const paywalled = references.filter(
    (r) => r.journal_url && !r.pdf_path
  ).length;

  return (
    <div className="flex flex-wrap gap-3">
      <StatBadge label="Total" count={references.length} />
      <StatBadge label="Matched" count={matched} color="text-success" />
      <StatBadge label="Found" count={found} color="text-info" />
      <StatBadge label="Paywalled" count={paywalled} color="text-warning" />
      <StatBadge label="Not Found" count={notFound} color="text-destructive" />
      {errors > 0 && <StatBadge label="Errors" count={errors} color="text-destructive" />}
    </div>
  );
}

function StatBadge({
  label,
  count,
  color = "text-foreground",
}: {
  label: string;
  count: number;
  color?: string;
}) {
  return (
    <Badge variant="outline" className="gap-1.5 py-1 px-3">
      <span className={`font-bold ${color}`}>{count}</span>
      <span className="text-muted-foreground">{label}</span>
    </Badge>
  );
}
