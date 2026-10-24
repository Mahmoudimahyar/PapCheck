"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, FileX, Search, AlertTriangle, Upload } from "lucide-react";
import { CannotVerifyRefList } from "@/components/refcheck/cannot-verify-refs";
import { ReverifyBanner } from "@/components/refcheck/reverify-status";
import { useCannotVerifyRefs } from "@/hooks/use-cannot-verify-refs";
import type { CannotVerifyBreakdown } from "@/lib/types";

interface CannotVerifyBreakdownProps {
  breakdown: CannotVerifyBreakdown;
  onUploadClick?: () => void;
  /** With a session, an expanded reason lists its references and free-full-text hints. */
  sessionId?: string;
  /** After a metadata refresh's re-verification settled (the page reloads its results). */
  onResultsChanged?: () => void;
}

const REASON_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string; fixable: boolean }> = {
  no_pdf_paywalled: { label: "No PDF — Paywalled", icon: <FileX className="h-4 w-4" />, color: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200", fixable: true },
  no_pdf_not_found: { label: "No PDF — Not Found", icon: <FileX className="h-4 w-4" />, color: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200", fixable: true },
  no_pdf_book_chapter: { label: "No PDF — Book Chapter", icon: <FileX className="h-4 w-4" />, color: "bg-orange-50 text-orange-700 dark:bg-orange-950 dark:text-orange-300", fixable: false },
  no_pdf_website: { label: "No PDF — Website", icon: <FileX className="h-4 w-4" />, color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200", fixable: false },
  pdf_metadata_only: { label: "PDF Metadata Only", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200", fixable: false },
  pdf_supplement: { label: "PDF Supplement", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200", fixable: false },
  pdf_scanned: { label: "PDF Unreadable — Scanned / No Text", icon: <FileX className="h-4 w-4" />, color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200", fixable: true },
  insufficient_in_source: { label: "Source Lacks Evidence (Full Text Checked)", icon: <Search className="h-4 w-4" />, color: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200", fixable: false },
  section_irrelevant: { label: "Irrelevant Section", icon: <Search className="h-4 w-4" />, color: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200", fixable: false },
  reference_mismatch: { label: "Reference Mismatch", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200", fixable: false },
  llm_error: { label: "LLM Error", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200", fixable: false },
  abstract_insufficient: { label: "Abstract Insufficient", icon: <Search className="h-4 w-4" />, color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200", fixable: false },
  not_relevant: { label: "Not Relevant — Topic Mismatch", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200", fixable: false },
  unknown: { label: "Unknown", icon: <AlertTriangle className="h-4 w-4" />, color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300", fixable: false },
};

export default function CannotVerifyBreakdownPanel({
  breakdown,
  onUploadClick,
  sessionId,
  onResultsChanged,
}: CannotVerifyBreakdownProps) {
  const [expandedReason, setExpandedReason] = useState<string | null>(null);
  const refs = useCannotVerifyRefs(sessionId, expandedReason !== null, onResultsChanged);

  if (breakdown.total === 0) return null;

  const sortedReasons = Object.entries(breakdown.reasons).sort(
    ([, a], [, b]) => b.count - a.count,
  );
  const maxCount = Math.max(...sortedReasons.map(([, r]) => r.count), 1);

  return (
    <div className="border rounded-lg p-4 bg-white dark:bg-gray-900">
      <h3 className="font-semibold text-sm mb-3">
        Cannot Verify Breakdown ({breakdown.total} claims)
      </h3>
      {Object.keys(refs.reverifying).length > 0 && (
        <div className="mb-3"><ReverifyBanner states={refs.reverifying} /></div>
      )}

      <div className="space-y-2">
        {sortedReasons.map(([reason, detail]) => {
          const config = REASON_CONFIG[reason] || REASON_CONFIG.unknown;
          const isExpanded = expandedReason === reason;
          const barWidth = Math.round((detail.count / maxCount) * 100);

          return (
            <div key={reason}>
              <button
                onClick={() => setExpandedReason(isExpanded ? null : reason)}
                className="w-full flex items-center gap-2 text-left hover:bg-gray-50 dark:hover:bg-gray-800 rounded p-1"
              >
                <span className={`px-2 py-0.5 rounded text-xs flex items-center gap-1 ${config.color}`}>
                  {config.icon}
                  {config.label}
                </span>
                <span className="text-sm font-mono ml-auto mr-2">{detail.count}</span>
                <div className="w-24 h-2 bg-gray-200 dark:bg-gray-700 rounded overflow-hidden">
                  <div
                    className="h-full bg-orange-400 rounded"
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
                {config.fixable && onUploadClick && (
                  // A <button> inside the row <button> is invalid HTML (hydration error).
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); onUploadClick(); }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onUploadClick(); }
                    }}
                    className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1 cursor-pointer"
                  >
                    <Upload className="h-3 w-3" /> Upload
                  </span>
                )}
                {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>

              {isExpanded && (
                <div className="ml-2 sm:ml-8 mt-1 text-xs text-gray-500 dark:text-gray-400">
                  <p className="break-words">Claim IDs: {detail.claim_ids.join(", ")}</p>
                  {sessionId && (
                    <CannotVerifyRefList
                      reason={reason}
                      references={refs.refsByReason ? refs.refsByReason[reason] ?? [] : undefined}
                      failed={refs.failed}
                      sessionId={sessionId}
                      reverifying={refs.reverifying}
                      onBeforeRefresh={refs.onBeforeRefresh}
                      onRefreshed={refs.onRefreshed}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
