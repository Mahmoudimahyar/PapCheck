"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { VerificationResult, Verdict } from "@/lib/types";

interface HumanReviewModalProps {
  result: VerificationResult | null;
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (verdict: Verdict, reason: string) => void;
  onSkip: () => void;
  current: number;
  total: number;
}

const VERDICT_OPTIONS: { value: Verdict; label: string; color: string }[] = [
  { value: "supported", label: "Supported", color: "text-green-600" },
  {
    value: "partially_supported",
    label: "Partially Supported",
    color: "text-amber-600",
  },
  { value: "not_supported", label: "Not Supported", color: "text-red-600" },
  { value: "contradicted", label: "Contradicted", color: "text-red-700" },
  {
    value: "cannot_verify",
    label: "I'll Check Manually",
    color: "text-gray-500",
  },
];

export function HumanReviewModal({
  result,
  isOpen,
  onClose,
  onSubmit,
  onSkip,
  current,
  total,
}: HumanReviewModalProps) {
  const [selectedVerdict, setSelectedVerdict] = useState<Verdict | null>(null);
  const [reason, setReason] = useState("");

  if (!result) return null;

  const handleSubmit = () => {
    if (selectedVerdict) {
      onSubmit(selectedVerdict, reason);
      setSelectedVerdict(null);
      setReason("");
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Review Verification Result</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Reviewing {current} of {total}
          </p>
        </DialogHeader>

        <div className="space-y-4">
          {/* Claim */}
          <div>
            <Label className="text-xs font-medium text-muted-foreground">
              Manuscript Text
            </Label>
            <p className="text-sm mt-1 p-2 bg-muted rounded">
              {result.claim.manuscript_text || result.claim.extracted_claim}
            </p>
          </div>

          {/* Evidence Quotes */}
          {result.evidence_quotes.length > 0 && (
            <div>
              <Label className="text-xs font-medium text-muted-foreground">
                Evidence from Source
              </Label>
              <div className="space-y-1 mt-1">
                {result.evidence_quotes.map((quote, i) => (
                  <blockquote
                    key={i}
                    className="text-sm p-2 border-l-2 border-blue-300 bg-blue-50 dark:bg-blue-950 italic"
                  >
                    &ldquo;{quote}&rdquo;
                  </blockquote>
                ))}
              </div>
            </div>
          )}

          {/* Reasoning */}
          <div>
            <Label className="text-xs font-medium text-muted-foreground">
              AI Reasoning (Tier {result.tier})
            </Label>
            <div className="text-sm mt-1 p-2 bg-muted rounded whitespace-pre-wrap max-h-40 overflow-y-auto">
              {result.reasoning}
            </div>
          </div>

          {/* Verdict Selection */}
          <div>
            <Label className="text-xs font-medium">Your Verdict</Label>
            <div className="grid grid-cols-1 gap-2 mt-2">
              {VERDICT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSelectedVerdict(opt.value)}
                  className={`text-left px-3 py-2 rounded border text-sm transition-colors ${
                    selectedVerdict === opt.value
                      ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
                      : "border-border hover:border-blue-300"
                  } ${opt.color}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Reason */}
          <div>
            <Label className="text-xs font-medium text-muted-foreground">
              Reason (optional)
            </Label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why are you overriding the AI verdict?"
              className="mt-1"
              rows={2}
            />
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onSkip}>
            Skip
          </Button>
          <Button onClick={handleSubmit} disabled={!selectedVerdict}>
            Submit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
