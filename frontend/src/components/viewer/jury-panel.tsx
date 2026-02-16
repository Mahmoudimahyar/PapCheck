"use client";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ModelVote } from "@/lib/types";
import {
  getVerdictColor,
  CONSENSUS_LABELS,
  CONSENSUS_STYLES,
  TIER_LABELS,
} from "@/lib/verdict-colors";

interface JuryPanelProps {
  votes: ModelVote[];
  consensusType: string;
  finalTier: number;
  escalationPath: number[];
  agreementRatio: number;
  compact?: boolean;
}

export function JuryPanel({
  votes,
  consensusType,
  finalTier,
  escalationPath,
  agreementRatio,
  compact = false,
}: JuryPanelProps) {
  const isUnanimous = consensusType === "unanimous";
  const wasEscalated = escalationPath.length > 1;
  const agreeCount = Math.round(agreementRatio * votes.length);

  if (compact) {
    return <CompactJury votes={votes} isUnanimous={isUnanimous} agreeCount={agreeCount} />;
  }

  const tierGroups = groupByTier(votes, escalationPath);

  return (
    <div
      className={`rounded-md border p-3 space-y-2 ${
        wasEscalated ? "border-amber-400/60 dark:border-amber-500/40" : "border-border"
      }`}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Jury</span>
          <ConsensusBadge type={consensusType} />
        </div>
        <span className="text-xs text-muted-foreground">
          {TIER_LABELS[finalTier] ?? `Tier ${finalTier}`} · {agreeCount}/{votes.length} agree
        </span>
      </div>

      <div className="flex items-center gap-1 flex-wrap">
        {tierGroups.map((group, gi) => (
          <div key={group.tier} className="flex items-center gap-1">
            {gi > 0 && <TierDivider />}
            {group.votes.map((vote, vi) => (
              <VerdictDot key={`${vote.abbreviation}-${vi}`} vote={vote} size="md" showLabel />
            ))}
          </div>
        ))}
      </div>

      {wasEscalated && (
        <DissenterNote votes={votes} />
      )}
    </div>
  );
}

function CompactJury({
  votes,
  isUnanimous,
  agreeCount,
}: {
  votes: ModelVote[];
  isUnanimous: boolean;
  agreeCount: number;
}) {
  if (isUnanimous) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground">
        {agreeCount}/{votes.length} ✓
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-0.5">
      {votes.map((vote, i) => (
        <VerdictDot key={`${vote.abbreviation}-${i}`} vote={vote} size="sm" />
      ))}
    </span>
  );
}

function ConsensusBadge({ type }: { type: string }) {
  const label = CONSENSUS_LABELS[type] ?? type;
  const style = CONSENSUS_STYLES[type] ?? "bg-muted text-muted-foreground";
  return (
    <Badge variant="outline" className={`text-[10px] px-1.5 py-0 h-4 font-medium ${style} border-0`}>
      {label}
      {type === "unanimous" && " ✓"}
      {type === "tiebreaker" && " ⚖"}
    </Badge>
  );
}

export function VerdictDot({
  vote,
  size = "sm",
  showLabel = false,
}: {
  vote: ModelVote;
  size?: "sm" | "md";
  showLabel?: boolean;
}) {
  const colors = getVerdictColor(vote.verdict);
  const sizeClass = size === "sm" ? "w-2 h-2" : "w-3 h-3";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex flex-col items-center gap-0.5 cursor-default">
          <div className={`${sizeClass} rounded-full ${colors.dot}`} />
          {showLabel && (
            <span className="text-[9px] text-muted-foreground leading-none">
              {vote.abbreviation}
            </span>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="text-xs">
        <p className="font-medium">{vote.model_name}</p>
        <p className={colors.text}>
          {vote.verdict.replace("_", " ")} ({Math.round(vote.confidence * 100)}%)
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

function TierDivider() {
  return <div className="w-px h-5 bg-border mx-1" />;
}

function DissenterNote({ votes }: { votes: ModelVote[] }) {
  const majorityVerdict = getMajorityVerdict(votes);
  const dissenters = votes.filter((v) => v.verdict !== majorityVerdict && v.verdict !== "cannot_verify");
  if (dissenters.length === 0) return null;
  return (
    <p className="text-[10px] text-amber-600 dark:text-amber-400">
      ⚠ {dissenters.length} dissent{dissenters.length > 1 ? "s" : ""}
    </p>
  );
}

function getMajorityVerdict(votes: ModelVote[]): string {
  const counts: Record<string, number> = {};
  for (const v of votes) {
    if (v.verdict === "cannot_verify") continue;
    counts[v.verdict] = (counts[v.verdict] ?? 0) + 1;
  }
  let best = "cannot_verify";
  let bestCount = 0;
  for (const [verdict, count] of Object.entries(counts)) {
    if (count > bestCount) { best = verdict; bestCount = count; }
  }
  return best;
}

interface TierGroup {
  tier: number;
  votes: ModelVote[];
}

function groupByTier(votes: ModelVote[], escalationPath: number[]): TierGroup[] {
  const groups: TierGroup[] = [];
  for (const tier of escalationPath) {
    const tierVotes = votes.filter((v) => v.tier === tier);
    if (tierVotes.length > 0) groups.push({ tier, votes: tierVotes });
  }
  return groups;
}
