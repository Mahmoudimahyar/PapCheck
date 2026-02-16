"use client";

import { useCallback, useRef } from "react";
import type { ManuscriptParagraph, ParagraphClaim } from "@/lib/types";

const VERDICT_HIGHLIGHT: Record<string, string> = {
  supported: "bg-green-500/20 hover:bg-green-500/30 dark:bg-green-900/30 dark:hover:bg-green-900/40 border-b-2 border-green-500",
  partially_supported: "bg-amber-500/20 hover:bg-amber-500/30 dark:bg-amber-900/30 dark:hover:bg-amber-900/40 border-b-2 border-amber-500",
  not_supported: "bg-red-500/20 hover:bg-red-500/30 dark:bg-red-900/30 dark:hover:bg-red-900/40 border-b-2 border-red-500",
  contradicted: "bg-red-700/20 hover:bg-red-700/30 dark:bg-red-900/40 dark:hover:bg-red-900/50 border-b-2 border-red-700",
  cannot_verify: "bg-gray-400/20 hover:bg-gray-400/30 dark:bg-gray-700/30 dark:hover:bg-gray-700/40 border-b-2 border-gray-400",
  pending: "bg-blue-400/20 hover:bg-blue-400/30 dark:bg-blue-900/30 dark:hover:bg-blue-900/40 border-b-2 border-blue-400",
};

const SELECTED_RING = "ring-2 ring-offset-1 ring-foreground/40 bg-opacity-40";

interface ManuscriptViewerProps {
  paragraphs: ManuscriptParagraph[];
  selectedClaimId: number | null;
  verdictFilter: string | null;
  onClaimClick: (claimId: number) => void;
}

export function ManuscriptViewer({
  paragraphs, selectedClaimId, verdictFilter, onClaimClick,
}: ManuscriptViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  let lastHeading = "";

  return (
    <div ref={containerRef} className="overflow-y-auto h-full p-4 space-y-1">
      {paragraphs.map((para) => {
        const showHeading = para.section_heading !== lastHeading;
        if (showHeading) lastHeading = para.section_heading;
        return (
          <div key={para.index}>
            {showHeading && para.section_heading && (
              <h3 className="text-base font-semibold mt-6 mb-2 text-foreground">
                {para.section_heading}
              </h3>
            )}
            <ParagraphBlock
              paragraph={para}
              selectedClaimId={selectedClaimId}
              verdictFilter={verdictFilter}
              onClaimClick={onClaimClick}
            />
          </div>
        );
      })}
      {paragraphs.length === 0 && (
        <p className="text-muted-foreground text-sm italic">
          No manuscript paragraphs available. Claims are shown in the legend above.
        </p>
      )}
    </div>
  );
}

function ParagraphBlock({
  paragraph, selectedClaimId, verdictFilter, onClaimClick,
}: {
  paragraph: ManuscriptParagraph;
  selectedClaimId: number | null;
  verdictFilter: string | null;
  onClaimClick: (claimId: number) => void;
}) {
  const { text, claims } = paragraph;

  const filteredClaims = verdictFilter
    ? claims.filter((c) => c.verdict === verdictFilter)
    : claims;

  if (!filteredClaims.length) {
    return <p className="text-sm leading-relaxed text-foreground/90 mb-2">{text}</p>;
  }

  return (
    <p className="text-sm leading-relaxed text-foreground/90 mb-2">
      {highlightParagraph(text, filteredClaims, selectedClaimId, onClaimClick)}
    </p>
  );
}

function highlightParagraph(
  text: string,
  claims: ParagraphClaim[],
  selectedClaimId: number | null,
  onClaimClick: (claimId: number) => void,
): React.ReactNode {
  const sorted = [...claims].sort((a, b) => a.char_start - b.char_start);
  const parts: React.ReactNode[] = [];
  let lastEnd = 0;

  for (const claim of sorted) {
    const start = Math.max(claim.char_start, lastEnd);
    const end = Math.min(claim.char_end, text.length);
    if (start >= end) continue;

    if (start > lastEnd) {
      parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd, start)}</span>);
    }

    const isSelected = selectedClaimId === claim.claim_id;
    const baseStyle = VERDICT_HIGHLIGHT[claim.verdict] ?? VERDICT_HIGHLIGHT.pending;
    const selectedStyle = isSelected ? SELECTED_RING : "";

    const showBadge = claim.model_count && claim.model_count > 0 && claim.agreeing_count !== claim.model_count;

    parts.push(
      <span
        key={`c-${claim.claim_id}-${start}`}
        className={`cursor-pointer rounded-sm px-0.5 transition-all ${baseStyle} ${selectedStyle}`}
        onClick={() => onClaimClick(claim.claim_id)}
        title={`Claim #${claim.claim_id}: ${claim.verdict} (${Math.round(claim.confidence * 100)}%)`}
      >
        {text.slice(start, end)}
        {showBadge && (
          <span className="text-[10px] text-muted-foreground ml-0.5 align-super">
            {claim.agreeing_count}/{claim.model_count}
          </span>
        )}
      </span>
    );
    lastEnd = end;
  }

  if (lastEnd < text.length) {
    parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <>{parts}</>;
}
