"use client";

import { useEffect, useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { JuryPanel } from "@/components/viewer/jury-panel";
import { ModelDetailCard } from "@/components/viewer/model-detail-card";
import { EscalationTimeline } from "@/components/viewer/escalation-timeline";
import type { EvidenceResponse, VotingRecord } from "@/lib/types";

interface VotingSectionProps {
  votingRecord?: VotingRecord;
  verifications: EvidenceResponse["verifications"];
  showModelOpinions: boolean;
  showDetails: boolean;
}

export function VotingSection({
  votingRecord,
  verifications,
  showModelOpinions,
  showDetails,
}: VotingSectionProps) {
  const [opinionsOpen, setOpinionsOpen] = useState(showModelOpinions);
  const [detailsOpen, setDetailsOpen] = useState(showDetails);
  const [expandedIdx, setExpandedIdx] = useState<number>(0);

  useEffect(() => { setOpinionsOpen(showModelOpinions); }, [showModelOpinions]);
  useEffect(() => { setDetailsOpen(showDetails); }, [showDetails]);

  if (!votingRecord || votingRecord.votes.length === 0) return null;

  const primaryVerdict = verifications[0]?.verdict ?? "cannot_verify";
  const primaryConfidence = verifications[0]?.confidence ?? 0;

  return (
    <div className="space-y-3">
      <JuryPanel
        votes={votingRecord.votes}
        consensusType={votingRecord.consensus_type}
        finalTier={votingRecord.final_tier}
        escalationPath={votingRecord.escalation_path}
        agreementRatio={votingRecord.agreement_ratio}
      />

      {votingRecord.votes.length > 1 && (
        <Collapsible open={opinionsOpen} onOpenChange={setOpinionsOpen}>
          <CollapsibleTrigger className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
            {opinionsOpen ? "▾" : "▸"} Show all model opinions ({votingRecord.votes.length})
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-2 mt-2">
            {votingRecord.votes.map((vote, i) => (
              <ModelDetailCard
                key={`${vote.abbreviation}-${i}`}
                vote={vote}
                isExpanded={expandedIdx === i}
                onToggle={() => setExpandedIdx(expandedIdx === i ? -1 : i)}
              />
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}

      {votingRecord.escalation_path.length > 1 && (
        <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
          <CollapsibleTrigger className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
            {detailsOpen ? "▾" : "▸"} Verification details
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <EscalationTimeline
              votes={votingRecord.votes}
              escalationPath={votingRecord.escalation_path}
              consensusType={votingRecord.consensus_type}
              finalVerdict={primaryVerdict}
              finalConfidence={primaryConfidence}
            />
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
