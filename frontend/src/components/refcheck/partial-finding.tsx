"use client";

/**
 * V5.4 partial sub-type of one result: why it is only partial (type + minor/major), what the
 * source does not state, what the author should do, and the benign guards that cleared a concern.
 * Negative verdicts (not supported / contradicted / not relevant) also carry a type; there it is
 * shown as the "Issue type" (as in the DOCX report), never as "Why partial", and the table chip
 * is dashed so it does not read as one of the partial-type counts.
 */

import { CheckCircle2, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  GUARD_LABELS,
  knownGuards,
  partialTypeInfo,
  type PartialFields,
  type PartialSeverity,
} from "@/lib/partial-types";

const CHIP = "text-[10px] px-1.5 py-0";
const SEVERITY_STYLE: Record<PartialSeverity, string> = {
  major: "border-red-300 text-red-700 dark:border-red-700 dark:text-red-300",
  minor: "border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300",
};

/** "Major" / "Minor" badge. */
export function SeverityBadge({ severity, className = "" }: { severity?: PartialSeverity | null; className?: string }) {
  if (!severity) return null;
  return (
    <Badge variant="outline" className={`${CHIP} ${SEVERITY_STYLE[severity]} ${className}`}>
      {severity === "major" ? "Major" : "Minor"}
    </Badge>
  );
}

/** Verdicts that never show a type (a supported result shows its cleared guards instead). */
const UNTYPED_VERDICTS = new Set(["supported", "cannot_verify"]);

/** The result's type info, or null for supported / cannot-verify / untyped results. */
function typeInfoFor(verdict: string, fields: PartialFields) {
  return UNTYPED_VERDICTS.has(verdict) ? null : partialTypeInfo(fields.partial_type);
}

/** Compact type chip for a results-table row (dashed for a negative verdict's issue type). */
export function PartialTypeBadge({ verdict, fields }: { verdict: string; fields: PartialFields }) {
  const info = typeInfoFor(verdict, fields);
  if (info) {
    const severity = fields.partial_severity ?? info.severity;
    const partial = verdict === "partially_supported";
    return (
      <Badge
        variant="outline"
        className={`${CHIP} ${SEVERITY_STYLE[severity]} ${partial ? "" : "border-dashed"}`}
        title={partial ? info.meaning : `Issue type: ${info.meaning}`}
      >
        {info.label}
      </Badge>
    );
  }
  const guards = knownGuards(fields.guards_applied);
  if (verdict !== "supported" || guards.length === 0) return null;
  return (
    <Badge
      variant="outline"
      className={`${CHIP} border-green-300 text-green-700 dark:border-green-700 dark:text-green-300`}
      title={guards.map((g) => GUARD_LABELS[g].explanation).join(" ")}
    >
      Cleared: {guards.map((g) => GUARD_LABELS[g].label).join(", ")}
    </Badge>
  );
}

/**
 * Why the verdict is partial (or, for a negative verdict, its issue type) and what to do about
 * it; nothing for supported / cannot-verify / untyped results.
 */
export function PartialFinding({ verdict, fields }: { verdict: string; fields: PartialFields }) {
  const info = typeInfoFor(verdict, fields);
  if (!info) return null;
  const heading = verdict === "partially_supported" ? "Why partial" : "Issue type";
  const severity = fields.partial_severity ?? info.severity;
  const elements = fields.unsupported_elements ?? [];
  const tone = severity === "major"
    ? "border-red-200 dark:border-red-800 bg-red-50/60 dark:bg-red-950/40"
    : "border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/40";
  return (
    <div className={`rounded border p-2 space-y-1.5 ${tone}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium uppercase tracking-wide text-stone-600 dark:text-muted-foreground">{heading}</span>
        <span className="text-sm font-medium">{info.label}</span>
        <SeverityBadge severity={severity} />
      </div>
      <p className="text-xs text-stone-600 dark:text-muted-foreground">{info.meaning}</p>
      {elements.length > 0 && (
        <div>
          <p className="text-xs font-medium">Not stated in the source:</p>
          <ul className="list-disc ml-5 text-xs space-y-0.5">
            {elements.map((element, i) => <li key={i}>{element}</li>)}
          </ul>
        </div>
      )}
      {fields.author_action && (
        <p className="text-xs flex items-start gap-1.5">
          <Wrench className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span><span className="font-medium">What to do:</span> {fields.author_action}</span>
        </p>
      )}
    </div>
  );
}

/**
 * "Cleared: ..." notes for concerns a benign guard dismissed. Only a supported result was
 * cleared; on any other verdict the guards did not settle the concern, so nothing is shown.
 */
export function GuardNotes({ verdict, guards }: { verdict: string; guards?: string[] }) {
  const known = verdict === "supported" ? knownGuards(guards) : [];
  if (known.length === 0) return null;
  return (
    <div className="space-y-1">
      {known.map((g) => (
        <div
          key={g}
          className="flex items-start gap-1.5 p-2 rounded border text-xs bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800 text-green-800 dark:text-green-300"
        >
          <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            <span className="font-medium">Cleared: {GUARD_LABELS[g].label}.</span> {GUARD_LABELS[g].explanation}
          </span>
        </div>
      ))}
    </div>
  );
}
