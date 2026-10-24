"use client";

/**
 * V5.2 signals next to a verdict: what the reference is cited for, both views of a
 * disputed verdict, and warnings (incomplete sentence, ambiguous citation, unusable PDF,
 * secondary citation, numbers missing from the source). V5.7: a "supported" verdict the
 * triage flagged as a possible missed problem ("check first").
 */

import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatLabel, traceVerdictStyle } from "@/lib/cascade";
import type { ClaimDetail, DisputeViews, LayerView, ResultSignals, SourceProblem } from "@/lib/types";

export const FRAGMENT_TEXT = "Claim text appears incomplete — check the sentence in the manuscript.";

export const SOURCE_PROBLEM_SHORT: Record<SourceProblem, string> = {
  reference_mismatch: "Wrong PDF",
  pdf_scanned: "Scanned PDF",
  pdf_supplement: "Supplement PDF",
  pdf_metadata_only: "Metadata-only PDF",
};

const CHIP = "text-[10px] px-1.5 py-0";
const WARN_CHIP = `${CHIP} border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-300`;
const BAD_CHIP = `${CHIP} border-red-300 text-red-600 dark:border-red-700 dark:text-red-400`;

/** The clause this reference is cited for (only when narrower than the sentence). */
export function CitedFor({ citedFor }: { citedFor?: string }) {
  if (!citedFor) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Cited for</p>
      <p className="text-sm font-medium">{citedFor}</p>
      <p className="text-[11px] text-muted-foreground">
        Other parts of the sentence cite other references; only this part was checked.
      </p>
    </div>
  );
}

function Warning({ text, tone = "amber" }: { text: string; tone?: "amber" | "red" }) {
  const style = tone === "red"
    ? "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300"
    : "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300";
  return (
    <div className={`flex items-start gap-1.5 p-2 rounded border text-xs ${style}`}>
      <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

/** Warnings about the claim text, the citation mapping and the attached PDF. */
export function ClaimWarnings({ claim, signals }: { claim: ClaimDetail; signals?: ResultSignals }) {
  const items: { text: string; tone: "amber" | "red" }[] = [];
  if (signals?.source_problem_text) {
    items.push({ text: `${signals.source_problem_text}; it was not used as the article.`, tone: "red" });
  }
  if (claim.claim_quality === "fragment") items.push({ text: FRAGMENT_TEXT, tone: "amber" });
  if (claim.mapping_note) items.push({ text: claim.mapping_note, tone: "amber" });
  if (items.length === 0) return null;
  return (
    <div className="space-y-1">
      {items.map((w, i) => <Warning key={i} text={w.text} tone={w.tone} />)}
    </div>
  );
}

function ViewColumn({ title, view }: { title: string; view: LayerView }) {
  return (
    <div className="flex-1 min-w-0 rounded border p-2 space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium">{title}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${traceVerdictStyle(view.verdict)}`}>
          {formatLabel(view.verdict)}
        </span>
        {view.model_name && <span className="text-[10px] text-muted-foreground">{view.model_name}</span>}
      </div>
      {view.explanation && <p className="text-xs leading-relaxed">{view.explanation}</p>}
    </div>
  );
}

/** Both models' verdicts and reasons when they disagreed. */
export function DisputePanel({ dispute }: { dispute?: DisputeViews | null }) {
  if (!dispute) return null;
  return (
    <div className="rounded border border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/40 p-2 space-y-2">
      <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
        Disputed — the two models disagreed. Shown as {formatLabel(dispute.shown_verdict)} pending your review.
      </p>
      <div className="flex flex-col md:flex-row gap-2">
        <ViewColumn title="Verifier" view={dispute.verifier} />
        <ViewColumn title="Cross-check" view={dispute.cross_check} />
      </div>
    </div>
  );
}

/** Deterministic notes that never change the verdict. */
export function ResultNotes({ signals }: { signals?: ResultSignals }) {
  if (!signals) return null;
  const notes: string[] = [];
  if (signals.check_first_reasons?.length) {
    notes.push(`Check first — shown as supported, but ${signals.check_first_reasons.join("; ")}.`);
  }
  if (signals.secondary_citation) {
    notes.push("Secondary citation: the supporting passage itself cites other work — consider citing the primary study.");
  }
  if (signals.numbers_not_found.length > 0) {
    notes.push(`Numbers in the claim found nowhere in the source: ${signals.numbers_not_found.join(", ")}`);
  }
  if (notes.length === 0) return null;
  return <div className="space-y-1">{notes.map((n, i) => <Warning key={i} text={n} />)}</div>;
}

/** Compact badges for a results-table row. */
export function SignalBadges({ claim, signals }: { claim: ClaimDetail; signals?: ResultSignals }) {
  return (
    <>
      {signals?.source_problem && (
        <Badge variant="outline" className={BAD_CHIP} title={signals.source_problem_text}>
          {SOURCE_PROBLEM_SHORT[signals.source_problem]}
        </Badge>
      )}
      {claim.claim_quality === "fragment" && (
        <Badge variant="outline" className={WARN_CHIP} title={FRAGMENT_TEXT}>Incomplete sentence</Badge>
      )}
      {claim.mapping_ambiguous && (
        <Badge variant="outline" className={WARN_CHIP} title={claim.mapping_note}>Ambiguous reference</Badge>
      )}
      {signals?.check_first_reasons?.length ? (
        <Badge variant="outline" className={WARN_CHIP} title={signals.check_first_reasons.join("; ")}>
          Check first
        </Badge>
      ) : null}
      {signals?.secondary_citation && (
        <Badge variant="outline" className={WARN_CHIP}>Secondary citation</Badge>
      )}
      {signals && signals.numbers_not_found.length > 0 && (
        <Badge variant="outline" className={WARN_CHIP} title={signals.numbers_not_found.join(", ")}>
          Numbers not in source
        </Badge>
      )}
    </>
  );
}
