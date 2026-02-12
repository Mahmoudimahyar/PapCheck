"use client";

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
      <CardContent className="pt-4 space-y-2">
        <p className="text-sm font-medium">
          [{reference.id}] {reference.title}
        </p>
        <p className="text-xs text-muted-foreground">
          Needs confirmation — fuzzy title match
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onConfirm(reference.id, true)}
          >
            Confirm
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
