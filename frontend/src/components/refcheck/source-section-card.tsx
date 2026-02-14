"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { EvidenceSection, QuoteHighlight } from "@/lib/types";

interface SourceSectionCardProps {
  section: EvidenceSection;
}

const MATCH_STYLES: Record<string, string> = {
  direct: "underline decoration-green-500 decoration-2 bg-green-500/10 dark:bg-green-900/30",
  paraphrased: "underline decoration-dashed decoration-amber-500 decoration-2 bg-amber-500/10 dark:bg-amber-900/30",
  numeric_mismatch: "underline decoration-wavy decoration-red-500 decoration-2 bg-red-500/10 dark:bg-red-900/30",
  absent: "line-through text-red-500",
};

const MATCH_ICONS: Record<string, string> = {
  direct: "✓",
  paraphrased: "≈",
  numeric_mismatch: "⚠",
  absent: "✗",
};

export function SourceSectionCard({ section }: SourceSectionCardProps) {
  const [expanded, setExpanded] = useState(section.full_text.length < 500);

  const displayText = expanded ? section.full_text : section.full_text.slice(0, 400);

  return (
    <Card className="border-muted">
      <CardHeader className="pb-2 pt-3 px-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            {section.section_heading || "Source Section"}
            {section.page_number && ` — Page ${section.page_number}`}
          </span>
          <div className="flex gap-2">
            {section.quote_highlights.map((qh, i) => (
              <span key={i} className="text-xs" title={`${qh.match_type}: ${qh.quote.slice(0, 40)}...`}>
                {MATCH_ICONS[qh.match_type] ?? "?"}
              </span>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        <div className="text-sm leading-relaxed whitespace-pre-wrap font-serif">
          {highlightSourceText(displayText, section.quote_highlights)}
        </div>
        {section.full_text.length > 500 && (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 text-xs"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Show less" : "Show more..."}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function highlightSourceText(text: string, highlights: QuoteHighlight[]): React.ReactNode {
  if (!highlights.length) return text;

  const sorted = [...highlights]
    .filter((h) => h.char_start < text.length)
    .sort((a, b) => a.char_start - b.char_start);

  const parts: React.ReactNode[] = [];
  let lastEnd = 0;

  for (const hl of sorted) {
    const start = Math.max(hl.char_start, lastEnd);
    const end = Math.min(hl.char_end, text.length);
    if (start >= end) continue;

    if (start > lastEnd) {
      parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd, start)}</span>);
    }

    const style = MATCH_STYLES[hl.match_type] ?? "";
    parts.push(
      <span key={`h-${start}`} className={style} title={`${hl.match_type}: "${hl.quote}"`}>
        {text.slice(start, end)}
      </span>
    );
    lastEnd = end;
  }

  if (lastEnd < text.length) {
    parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <>{parts}</>;
}
