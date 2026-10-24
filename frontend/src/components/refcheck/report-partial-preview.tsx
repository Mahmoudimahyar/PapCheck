"use client";

/**
 * Report preview of the partially supported findings, grouped by V5.4 partial type in the
 * report's sub-section order, each with its severity and the author action.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SeverityBadge } from "@/components/refcheck/partial-finding";
import {
  PARTIAL_TYPE_INFO,
  PARTIAL_TYPE_ORDER,
  isPartialTypeKey,
  type PartialSeverity,
  type PartialTypeKey,
} from "@/lib/partial-types";

type PreviewRow = Record<string, string>;

function groupKey(row: PreviewRow): PartialTypeKey {
  return isPartialTypeKey(row.partial_type) ? row.partial_type : "unclassified";
}

function severity(row: PreviewRow): PartialSeverity | null {
  return row.partial_severity === "major" || row.partial_severity === "minor" ? row.partial_severity : null;
}

function Row({ row }: { row: PreviewRow }) {
  return (
    <div className="p-2 border rounded text-sm space-y-1">
      <div className="flex items-center gap-1.5 flex-wrap">
        {row.check_first && <Badge variant="outline" className="text-[10px]">check first</Badge>}
        <SeverityBadge severity={severity(row)} />
        <span>
          Claim {row.claim_id}{row.disputed && " (disputed)"}: {row.cited_for || row.claim}
        </span>
      </div>
      {row.unsupported_elements && (
        <p className="text-xs text-muted-foreground">Not stated in the source: {row.unsupported_elements}</p>
      )}
      {row.author_action && (
        <p className="text-xs"><span className="font-medium">What to do:</span> {row.author_action}</p>
      )}
    </div>
  );
}

export function ReportPartialPreview({ rows }: { rows: PreviewRow[] }) {
  if (rows.length === 0) return null;
  const groups = PARTIAL_TYPE_ORDER
    .map((key) => ({ key, rows: rows.filter((r) => groupKey(r) === key) }))
    .filter((g) => g.rows.length > 0);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Partially Supported — by Type</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {groups.map((g) => (
          <div key={g.key} className="space-y-2">
            <div>
              <h4 className="text-sm font-medium">
                {PARTIAL_TYPE_INFO[g.key].label} ({g.rows.length})
              </h4>
              <p className="text-xs text-muted-foreground">{PARTIAL_TYPE_INFO[g.key].meaning}</p>
            </div>
            {g.rows.map((row, i) => <Row key={`${row.claim_id}-${row.reference_id}-${i}`} row={row} />)}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
