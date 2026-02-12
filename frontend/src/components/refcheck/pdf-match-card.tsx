"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Reference } from "@/lib/types";

interface PdfMatchCardProps {
  reference: Reference;
  onConfirm: (refId: number, confirmed: boolean) => void;
}

export function PdfMatchCard({ reference, onConfirm }: PdfMatchCardProps) {
  return (
    <Card className="border-warning/50">
      <CardContent className="pt-4 space-y-3">
        {/* Reference metadata */}
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Reference</p>
          <p className="text-sm font-medium">
            [{reference.id}] {reference.title || "Untitled"}
          </p>
          <p className="text-xs text-muted-foreground">
            {reference.authors.slice(0, 2).join(", ")}
            {reference.authors.length > 2 && " et al."}
            {reference.year && ` (${reference.year})`}
          </p>
        </div>

        {/* PDF metadata — extracted title + DOI */}
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Matched PDF</p>
          <div className="flex items-center gap-2 mt-0.5">
            {reference.doi && (
              <Badge variant="outline" className="text-xs font-mono">
                DOI: {reference.doi}
              </Badge>
            )}
            {reference.pdf_source && (
              <Badge variant="outline" className="text-xs">
                {reference.pdf_source.replace("_", " ")}
              </Badge>
            )}
          </div>
        </div>

        <p className="text-xs text-amber-600 dark:text-amber-400">
          Needs confirmation — fuzzy title match
        </p>

        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onConfirm(reference.id, true)}
          >
            Confirm Match
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onConfirm(reference.id, false)}
          >
            Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
