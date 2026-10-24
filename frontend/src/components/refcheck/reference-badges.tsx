"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Reference, ReferenceLinks, SourceIssue, SourceIssueKind } from "@/lib/types";

const CHIP = "text-[10px] px-1.5 py-0";
const BAD = `${CHIP} border-red-300 text-red-600 dark:border-red-700 dark:text-red-400`;
const WARN = `${CHIP} border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-300`;
const INFO = `${CHIP} border-sky-300 text-sky-700 dark:border-sky-700 dark:text-sky-300`;

const RETRACTION_BADGE: Record<string, { label: string; className: string }> = {
  retracted: { label: "RETRACTED", className: "bg-red-700 text-white" },
  corrected: { label: "CORRECTED", className: "bg-amber-700 text-white" },
  expression_of_concern: { label: "CONCERN", className: "bg-orange-700 text-white" },
};

/** V5.2 bibliography / source issues shown on the reference row. */
const ISSUE_BADGES: Partial<Record<SourceIssueKind, { label: string; className: string }>> = {
  wrong_pdf: { label: "Wrong PDF", className: BAD },
  scanned_pdf: { label: "Scanned PDF", className: BAD },
  supplement_pdf: { label: "Supplement PDF only", className: BAD },
  metadata_only_pdf: { label: "Metadata-only PDF", className: BAD },
  replaced_pdf: { label: "Upload replaced", className: WARN },
  ambiguous_citation: { label: "Ambiguous citation", className: WARN },
  title_fixed: { label: "Title from DOI record", className: INFO },
};

/** "2018b" for author-year lists that disambiguate with letters. */
export function referenceYear(reference: Reference): string {
  return reference.year ? `${reference.year}${reference.year_suffix ?? ""}` : "";
}

export function ReferenceBadges({ reference, issues = [] }: { reference: Reference; issues?: SourceIssue[] }) {
  const retraction = RETRACTION_BADGE[reference.retraction_status];
  const byKind = new Map<SourceIssueKind, string>();
  for (const issue of issues) byKind.set(issue.kind, issue.message);
  if (reference.repair_applied === "title_from_api" && !byKind.has("title_fixed")) {
    byKind.set("title_fixed", "The parsed title looked garbled; the DOI/PMID record's title is shown.");
  }
  // The PDF column already says "PDF may be wrong paper" for an identity mismatch.
  if (reference.identity_status === "mismatch") byKind.delete("wrong_pdf");
  return (
    <>
      {retraction && <Badge className={`${retraction.className} ${CHIP}`}>{retraction.label}</Badge>}
      {reference.duplicate_of != null && (
        <Badge variant="outline" className={WARN} title="Same work as another entry: merge them">
          Duplicate of [{reference.duplicate_of}]
        </Badge>
      )}
      {[...byKind.entries()].map(([kind, message]) => {
        const badge = ISSUE_BADGES[kind];
        return badge ? <Badge key={kind} variant="outline" className={badge.className} title={message}>{badge.label}</Badge> : null;
      })}
    </>
  );
}

export function RefLinks({ links }: { links: ReferenceLinks }) {
  const items = [
    { url: links.doi_url, label: "DOI" },
    { url: links.pubmed_url, label: "PubMed" },
    { url: links.pmc_url, label: "PMC" },
    { url: links.journal_url, label: "Publisher" },
    { url: links.scholar_url, label: "Scholar" },
  ].filter((l) => l.url);
  if (items.length === 0) return null;
  return (
    <div className="flex gap-1.5 mt-1 flex-wrap">
      {items.map((item) => (
        <a
          key={item.label}
          href={item.url!}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 hover:bg-blue-100 dark:bg-blue-950 dark:text-blue-300 dark:hover:bg-blue-900 transition-colors"
        >
          <ExternalLink className="h-2.5 w-2.5" />
          {item.label}
        </a>
      ))}
    </div>
  );
}
