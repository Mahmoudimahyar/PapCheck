"use client";

import type { ModelVote } from "@/lib/types";
import { getVerdictColor, TIER_LABELS, CONSENSUS_LABELS } from "@/lib/verdict-colors";
import { VerdictDot } from "@/components/viewer/jury-panel";

interface EscalationTimelineProps {
  votes: ModelVote[];
  escalationPath: number[];
  consensusType: string;
  finalVerdict: string;
  finalConfidence: number;
}

export function EscalationTimeline({
  votes,
  escalationPath,
  consensusType,
  finalVerdict,
  finalConfidence,
}: EscalationTimelineProps) {
  if (escalationPath.length <= 1) return null;

  const rounds = escalationPath.map((tier) => ({
    tier,
    votes: votes.filter((v) => v.tier === tier),
  }));

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-medium text-muted-foreground uppercase">
        Escalation Timeline
      </h4>

      {/* Desktop: horizontal */}
      <div className="hidden sm:flex items-start gap-2">
        {rounds.map((round, ri) => (
          <div key={round.tier} className="flex items-start gap-2">
            {ri > 0 && <TimelineArrow />}
            <RoundCard round={round} isLast={ri === rounds.length - 1} />
          </div>
        ))}
        <TimelineArrow />
        <ResolvedBadge
          verdict={finalVerdict}
          confidence={finalConfidence}
          consensusType={consensusType}
        />
      </div>

      {/* Mobile: vertical */}
      <div className="sm:hidden space-y-0">
        {rounds.map((round, ri) => (
          <div key={round.tier}>
            <RoundCardVertical round={round} />
            {ri < rounds.length - 1 && <VerticalConnector />}
          </div>
        ))}
        <VerticalConnector />
        <ResolvedBadge
          verdict={finalVerdict}
          confidence={finalConfidence}
          consensusType={consensusType}
        />
      </div>
    </div>
  );
}

interface RoundData {
  tier: number;
  votes: ModelVote[];
}

function RoundCard({ round, isLast }: { round: RoundData; isLast: boolean }) {
  const outcome = describeOutcome(round.votes, isLast);
  return (
    <div className="rounded-md border p-2 min-w-[120px]">
      <p className="text-[10px] font-medium text-muted-foreground mb-1.5">
        Round {round.tier + 1} ({TIER_LABELS[round.tier] ?? `Tier ${round.tier}`})
      </p>
      <div className="flex items-center gap-1">
        {round.votes.map((v, i) => (
          <VerdictDot key={`${v.abbreviation}-${i}`} vote={v} size="md" showLabel />
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground mt-1">{outcome}</p>
    </div>
  );
}

function RoundCardVertical({ round }: { round: RoundData }) {
  const outcome = describeOutcome(round.votes, false);
  return (
    <div className="flex items-start gap-2">
      <div className="w-2 h-2 rounded-full bg-muted-foreground mt-1 shrink-0" />
      <div>
        <p className="text-xs font-medium">
          Round {round.tier + 1} ({TIER_LABELS[round.tier] ?? `Tier ${round.tier}`})
        </p>
        <div className="flex items-center gap-1 mt-1">
          {round.votes.map((v, i) => (
            <VerdictDot key={`${v.abbreviation}-${i}`} vote={v} size="md" showLabel />
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-0.5">{outcome}</p>
      </div>
    </div>
  );
}

function ResolvedBadge({
  verdict,
  confidence,
  consensusType,
}: {
  verdict: string;
  confidence: number;
  consensusType: string;
}) {
  const colors = getVerdictColor(verdict);
  const label = CONSENSUS_LABELS[consensusType] ?? consensusType;
  return (
    <div className="flex items-center gap-1.5 mt-1 sm:mt-2">
      <span className="text-green-600 dark:text-green-400 font-medium text-xs">✓</span>
      <div>
        <p className={`text-xs font-medium ${colors.text}`}>
          {verdict.replace("_", " ")} ({Math.round(confidence * 100)}%)
        </p>
        <p className="text-[10px] text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function TimelineArrow() {
  return (
    <div className="flex items-center mt-4 text-muted-foreground">
      <svg width="20" height="12" viewBox="0 0 20 12" fill="none">
        <path d="M0 6H16M16 6L12 2M16 6L12 10" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </div>
  );
}

function VerticalConnector() {
  return (
    <div className="flex items-center pl-[3px] py-0.5">
      <div className="w-px h-4 bg-border" />
    </div>
  );
}

function describeOutcome(roundVotes: ModelVote[], _isLast: boolean): string {
  if (roundVotes.length === 0) return "No models";
  const active = roundVotes.filter((v) => v.verdict !== "cannot_verify");
  if (active.length === 0) return "All abstained";

  const counts: Record<string, number> = {};
  for (const v of active) {
    counts[v.verdict] = (counts[v.verdict] ?? 0) + 1;
  }

  const topVerdict = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (!topVerdict) return "No consensus";

  const [verdict, count] = topVerdict;
  if (count === active.length) return `${count}/${count} agree: ${verdict.replace("_", " ")}`;
  if (count > active.length / 2) return `${count}/${active.length}: ${verdict.replace("_", " ")}`;
  return "No majority";
}
