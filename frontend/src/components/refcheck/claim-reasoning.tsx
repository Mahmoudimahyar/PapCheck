"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  ConfirmationBadge,
  DecidedByBadge,
  ScreenRisk,
} from "@/components/refcheck/decided-by-badge";
import { LayerTraceEntry } from "@/components/refcheck/layer-trace-entry";
import { formatMs, formatUsd, traceVerdictStyle } from "@/lib/cascade";
import type { ConfirmationStatus, DecidedBy, ModelReasoning } from "@/lib/types";

interface ClaimReasoningProps {
  verdict: string;
  confidence: number;
  sourceCoverage: string;
  modelReasoning: ModelReasoning[];
  cannotVerifyReason?: string | null;
  sectionRelevance?: string;
  textQualityScore?: number;
  // V5 cascade trace
  decidedBy?: DecidedBy;
  consensusType?: string;
  screenPProblem?: number | null;
  confirmation?: ConfirmationStatus;
  confirmationLabel?: string;
  costUsd?: number;
  latencyMs?: number;
  quotesValidated?: boolean | null;
}

function coverageBadge(coverage: string): string {
  const badges: Record<string, string> = {
    full_text: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    abstract_only: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    relevant_sections: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    no_source: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300",
  };
  return badges[coverage] || badges.no_source;
}

function formatCoverage(coverage: string): string {
  return coverage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Index of the layer whose verdict became final (-1 if unknown / pre-V5). */
function finalLayerIndex(entries: ModelReasoning[], decidedBy?: DecidedBy, consensus?: string): number {
  if (!decidedBy || decidedBy === "none") return -1;
  // V5.6: a deterministic rule check (number / lineage) runs last and sets the verdict
  const last = entries.length - 1;
  if (last >= 0 && entries[last].layer === "post_rules") return last;
  const wanted =
    decidedBy === "screen" ? ["screen"]
    : decidedBy === "verifier"
      ? ["verifier", "verifier_expanded", "verifier_recheck",
         // V5.5: the element check's verdict is final when it cleared an element (the
         // co-cited union check runs after it, so the last of the two wins)
         // V5.7: the slot audit / slot probe can demote a supported verdict last
         ...(consensus === "adjudicated"
           ? ["adjudicate", "adjudicate_cocited", "adjudicate_slots", "slot_probe"] : [])]
    // "confirm_majority" only exists on results stored before V5.1 (confirm broke a tie);
    // V5.1 cross-checks (confirmed / disputed) keep decided_by = "verifier".
    : consensus === "confirm_majority" ? ["confirm"] : ["judge"];
  for (let i = entries.length - 1; i >= 0; i--) {
    // a failed layer (e.g. a union check over budget) never decided the verdict
    if (entries[i].verdict !== "error" && wanted.includes(entries[i].layer ?? "")) return i;
  }
  return -1;
}

export default function ClaimReasoning({
  verdict,
  confidence,
  sourceCoverage,
  modelReasoning,
  cannotVerifyReason,
  sectionRelevance,
  textQualityScore,
  decidedBy,
  consensusType,
  screenPProblem,
  confirmation,
  confirmationLabel,
  costUsd,
  latencyMs,
  quotesValidated,
}: ClaimReasoningProps) {
  const [expanded, setExpanded] = useState(false);
  const isCascade = !!decidedBy && decidedBy !== "none";
  const finalIdx = finalLayerIndex(modelReasoning, decidedBy, consensusType);
  const layerCount = modelReasoning.length;

  return (
    <div className="border rounded-lg p-3 mt-2 bg-white dark:bg-gray-900">
      {/* Collapsed view — always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2 flex-wrap">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${traceVerdictStyle(verdict)}`}>
            {verdict.replace(/_/g, " ")}
          </span>
          <span className="text-sm font-mono">{Math.round(confidence * 100)}%</span>
          <span className={`px-2 py-0.5 rounded text-xs ${coverageBadge(sourceCoverage)}`}>
            {formatCoverage(sourceCoverage)}
          </span>
          {isCascade ? (
            <DecidedByBadge decidedBy={decidedBy} withPrefix className="text-xs" />
          ) : (
            layerCount > 0 && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {modelReasoning[0].model_display || modelReasoning[0].model_name}
              </span>
            )
          )}
          <ConfirmationBadge status={confirmation} label={confirmationLabel} />
          <ScreenRisk pProblem={screenPProblem} />
          {cannotVerifyReason && (
            <span className="text-xs text-orange-700 dark:text-orange-400">
              {cannotVerifyReason.replace(/_/g, " ")}
            </span>
          )}
        </div>
        <span className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 shrink-0">
          {layerCount > 0 && `${layerCount} layer${layerCount !== 1 ? "s" : ""}`}
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
      </button>

      {/* Expanded view: one entry per cascade layer, in the order they ran */}
      {expanded && (
        <div className="mt-3 space-y-3">
          {isCascade && (
            <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400 flex-wrap">
              {costUsd !== undefined && <span>Cost {formatUsd(costUsd)}</span>}
              {latencyMs !== undefined && latencyMs > 0 && <span>Time {formatMs(latencyMs)}</span>}
              {quotesValidated === true && (
                <span className="text-green-700 dark:text-green-400">Quotes verified against source</span>
              )}
              {quotesValidated === false && (
                <span className="text-amber-700 dark:text-amber-400">
                  Some quotes could not be found in the source
                </span>
              )}
            </div>
          )}

          {modelReasoning.map((mr, idx) => (
            <LayerTraceEntry
              key={idx}
              entry={mr}
              step={idx + 1}
              isFinal={idx === finalIdx}
              sectionRelevance={sectionRelevance}
              textQualityScore={textQualityScore}
            />
          ))}

          {layerCount === 0 && (
            <div className="text-sm text-gray-500 dark:text-gray-400 italic">
              No detailed reasoning available for this claim.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
