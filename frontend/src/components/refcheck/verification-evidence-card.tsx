"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { SourceSectionCard } from "@/components/refcheck/source-section-card";
import { VerificationBadge } from "@/components/refcheck/verification-badge";
import type { EvidenceResponse, Verdict } from "@/lib/types";

interface VerificationEvidenceCardProps {
  verification: EvidenceResponse["verifications"][number];
}

export function VerificationEvidenceCard({ verification: v }: VerificationEvidenceCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2 pt-3 px-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <p className="text-sm font-medium">[{v.reference_id}] {v.reference_title}</p>
            <p className="text-xs text-muted-foreground">{v.reference_authors.join(", ")}</p>
          </div>
          <div className="flex items-center gap-2">
            <VerificationBadge verdict={v.verdict as Verdict} />
            <span className="text-xs text-muted-foreground">{Math.round(v.confidence * 100)}%</span>
            <Badge variant="outline" className="text-xs">Tier {v.tier}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-3">
        {v.reasoning && (
          <>
            <div className="text-xs font-medium uppercase text-muted-foreground">Model Reasoning</div>
            <p className="text-sm leading-relaxed">{v.reasoning}</p>
            <Separator />
          </>
        )}
        {v.evidence_sections.length > 0 && (
          <>
            <div className="text-xs font-medium uppercase text-muted-foreground">Source Evidence</div>
            <div className="space-y-2">
              {v.evidence_sections.map((section, i) => (
                <SourceSectionCard key={i} section={section} />
              ))}
            </div>
          </>
        )}
        {v.atomic_results && v.atomic_results.length > 0 && (
          <>
            <Separator />
            <div className="text-xs font-medium uppercase text-muted-foreground">Atomic Verification</div>
            <ul className="space-y-1">
              {v.atomic_results.map((ar, i) => (
                <li key={i} className="text-sm flex items-start gap-2">
                  <span>{ar.verified === true ? "✓" : ar.verified === false ? "✗" : "?"}</span>
                  <span>{ar.atom}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
