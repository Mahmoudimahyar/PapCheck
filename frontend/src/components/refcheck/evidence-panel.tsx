"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { VerificationEvidenceCard } from "@/components/refcheck/verification-evidence-card";
import { VotingSection } from "@/components/viewer/voting-section";
import { getEvidence } from "@/lib/api";
import type { EvidenceResponse } from "@/lib/types";

interface EvidencePanelProps {
  sessionId: string;
  claimId: number | null;
  onNavigate: (direction: "prev" | "next") => void;
  onClose: () => void;
  showModelOpinions?: boolean;
  showDetails?: boolean;
}

export function EvidencePanel({
  sessionId, claimId, onNavigate, onClose,
  showModelOpinions = false, showDetails = false,
}: EvidencePanelProps) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!claimId) { setData(null); return; }
    setLoading(true);
    setError(null);
    getEvidence(sessionId, claimId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId, claimId]);

  if (!claimId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        Click a highlighted claim to view evidence
      </div>
    );
  }
  if (loading) {
    return (
      <div className="space-y-4 p-4 animate-pulse">
        <div className="h-6 bg-muted rounded w-3/4" />
        <div className="h-4 bg-muted rounded w-1/2" />
        <div className="h-24 bg-muted rounded" />
      </div>
    );
  }
  if (error || !data) {
    return <div className="p-4 text-red-500 text-sm">Failed to load evidence: {error}</div>;
  }

  const { claim, verifications, voting_record } = data;

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="p-4 border-b space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">Claim #{claim.id}</h3>
          <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
        </div>
        <p className="text-sm text-muted-foreground italic">{claim.extracted_claim}</p>
        <div className="flex gap-2">
          <Badge variant="outline">{claim.claim_type}</Badge>
          <Badge variant="outline">{claim.priority}</Badge>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {verifications.map((v) => (
          <VerificationEvidenceCard key={v.reference_id} verification={v} />
        ))}

        <VotingSection
          votingRecord={voting_record}
          verifications={verifications}
          showModelOpinions={showModelOpinions}
          showDetails={showDetails}
        />

        {claim.atomic_claims.length > 0 && (
          <Card>
            <CardHeader className="pb-2 pt-3 px-4">
              <span className="text-xs font-medium uppercase text-muted-foreground">
                Atomic Claims
              </span>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <ul className="space-y-1">
                {claim.atomic_claims.map((atom, i) => (
                  <li key={i} className="text-sm flex items-start gap-2">
                    <span className="text-muted-foreground">•</span>
                    {atom}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>

      <div className="p-3 border-t flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => onNavigate("prev")}>← Prev</Button>
        <Button variant="outline" size="sm" onClick={() => onNavigate("next")}>Next →</Button>
      </div>
    </div>
  );
}
