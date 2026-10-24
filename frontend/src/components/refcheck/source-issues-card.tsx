"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SourceIssue, SourceIssueKind } from "@/lib/types";

/** Same order and wording as the DOCX report's "Bibliography & Source Issues" section. */
export const ISSUE_LABELS: Record<SourceIssueKind, string> = {
  retracted: "Retracted or corrected",
  wrong_pdf: "Attached PDF is a different paper",
  scanned_pdf: "Attached PDF is a scan without text",
  supplement_pdf: "Attached PDF is the supplement only",
  metadata_only_pdf: "Attached PDF holds only a metadata page",
  replaced_pdf: "Uploaded PDF unusable; a library / open-access copy was used",
  duplicate: "Duplicate reference",
  ambiguous_citation: "In-text citation matches several references",
  title_fixed: "Garbled title replaced from the DOI/PMID record",
};

/** Issues keyed by every reference id they mention (for per-row badges). */
export function issuesByReference(issues: SourceIssue[]): Record<number, SourceIssue[]> {
  const out: Record<number, SourceIssue[]> = {};
  for (const issue of issues) {
    for (const id of issue.reference_ids) (out[id] ??= []).push(issue);
  }
  return out;
}

interface SourceIssuesCardProps {
  issues: SourceIssue[];
  /** The report preview lists retractions in their own card. */
  hideRetracted?: boolean;
}

export function SourceIssuesCard({ issues, hideRetracted = false }: SourceIssuesCardProps) {
  const shown = hideRetracted ? issues.filter((i) => i.kind !== "retracted") : issues;
  if (shown.length === 0) return null;
  const kinds = (Object.keys(ISSUE_LABELS) as SourceIssueKind[]).filter((k) => shown.some((i) => i.kind === k));
  return (
    <Card className="border-amber-300 dark:border-amber-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Bibliography &amp; Source Issues ({shown.length})</CardTitle>
        <p className="text-xs text-muted-foreground">
          Fix these first: the affected claims were checked against another paper, only the
          abstract, or a guessed reference.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {kinds.map((kind) => (
          <div key={kind}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{ISSUE_LABELS[kind]}</p>
            <ul className="mt-1 space-y-1">
              {shown.filter((i) => i.kind === kind).map((issue, idx) => (
                <li key={idx} className="text-sm">
                  {issue.message}
                  {issue.claim_ids.length > 0 && (
                    <span className="text-xs text-muted-foreground"> Affected claims: {issue.claim_ids.join(", ")}.</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
