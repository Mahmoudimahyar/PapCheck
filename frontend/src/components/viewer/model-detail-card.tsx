"use client";

import { Badge } from "@/components/ui/badge";
import type { ModelVote } from "@/lib/types";
import { getVerdictColor, TIER_LABELS } from "@/lib/verdict-colors";

interface ModelDetailCardProps {
  vote: ModelVote;
  isExpanded: boolean;
  onToggle: () => void;
}

export function ModelDetailCard({ vote, isExpanded, onToggle }: ModelDetailCardProps) {
  const colors = getVerdictColor(vote.verdict);
  const tierLabel = TIER_LABELS[vote.tier] ?? `Tier ${vote.tier}`;

  return (
    <div className="rounded-md border overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted/50 transition-colors"
      >
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${colors.dot}`} />
        <span className="text-sm font-medium flex-1 truncate">{vote.model_name}</span>
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 shrink-0">
          {tierLabel}
        </Badge>
        <span className={`text-xs shrink-0 ${colors.text}`}>
          {vote.verdict.replace("_", " ")} {Math.round(vote.confidence * 100)}%
        </span>
        <ChevronIcon expanded={isExpanded} />
      </button>

      {isExpanded && (
        <CardBody vote={vote} borderColor={colors.border} />
      )}
    </div>
  );
}

function CardBody({ vote, borderColor }: { vote: ModelVote; borderColor: string }) {
  const totalTokens = vote.input_tokens + vote.output_tokens;

  return (
    <div className="px-3 pb-3 space-y-3 border-t">
      {vote.reasoning && (
        <p className="text-sm leading-relaxed pt-2">{vote.reasoning}</p>
      )}

      {vote.evidence_quotes.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground uppercase">Evidence</span>
          {vote.evidence_quotes.map((quote, i) => (
            <blockquote
              key={i}
              className={`text-xs leading-relaxed pl-3 border-l-2 ${borderColor} text-muted-foreground italic`}
            >
              &ldquo;{quote}&rdquo;
            </blockquote>
          ))}
        </div>
      )}

      <CostFooter
        timeMs={vote.response_time_ms}
        tokens={totalTokens}
        cost={vote.cost_usd}
      />
    </div>
  );
}

function CostFooter({ timeMs, tokens, cost }: { timeMs: number; tokens: number; cost: number }) {
  const timeStr = timeMs >= 1000 ? `${(timeMs / 1000).toFixed(1)}s` : `${timeMs}ms`;
  const costStr = cost >= 0.01 ? `$${cost.toFixed(2)}` : `$${cost.toFixed(4)}`;

  return (
    <div className="flex items-center gap-3 text-[10px] text-muted-foreground pt-1">
      <span>⏱ {timeStr}</span>
      <span>·</span>
      <span>📊 {tokens.toLocaleString()} tok</span>
      <span>·</span>
      <span>{costStr}</span>
    </div>
  );
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      className={`shrink-0 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`}
    >
      <path
        d="M3 4.5L6 7.5L9 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
