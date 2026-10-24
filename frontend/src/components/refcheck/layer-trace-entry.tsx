"use client";

import { BarChart3, Clock } from "lucide-react";
import { LAYER_LABELS, formatLabel, formatMs, traceVerdictStyle } from "@/lib/cascade";
import type { ModelReasoning } from "@/lib/types";

interface LayerTraceEntryProps {
  entry: ModelReasoning;
  step: number;
  isFinal: boolean;
  sectionRelevance?: string;
  textQualityScore?: number;
}

/** One cascade layer (screen / verifier / judge / confirm) in the reasoning panel. */
export function LayerTraceEntry({
  entry,
  step,
  isFinal,
  sectionRelevance,
  textQualityScore,
}: LayerTraceEntryProps) {
  const layerLabel = entry.layer ? LAYER_LABELS[entry.layer] ?? formatLabel(entry.layer) : "";
  const display = entry.model_display || entry.model_name;
  // "Judge · claude-sonnet-5-5" -> "claude-sonnet-5-5" when the step label already names the layer
  const model = entry.layer && entry.layer !== "screen" && display.includes(" · ")
    ? display.slice(display.indexOf(" · ") + 3)
    : display;
  const tokens = entry.input_tokens + entry.output_tokens;

  return (
    <div
      className={`border rounded p-3 bg-gray-50 dark:bg-gray-800 ${
        isFinal ? "border-indigo-300 dark:border-indigo-700" : ""
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap text-xs mb-2">
        {layerLabel && (
          <span className="font-semibold text-gray-700 dark:text-gray-200">
            {step}. {layerLabel}
          </span>
        )}
        <span className="text-gray-500 dark:text-gray-400 font-medium">{model}</span>
        <span className={`px-2 py-0.5 rounded font-medium ${traceVerdictStyle(entry.verdict)}`}>
          {formatLabel(entry.verdict)}
        </span>
        {isFinal && (
          <span className="text-[10px] uppercase tracking-wide text-indigo-600 dark:text-indigo-300">
            final call
          </span>
        )}
      </div>

      {entry.reasoning && <div className="text-sm mb-2">{entry.reasoning}</div>}

      {entry.evidence_quotes.length > 0 && (
        <div className="space-y-1 mb-2">
          {entry.evidence_quotes.map((quote, qIdx) => (
            <div
              key={qIdx}
              className="text-xs bg-gray-100 dark:bg-gray-700 border-l-2 border-blue-400 pl-2 py-1 italic"
            >
              &ldquo;{quote}&rdquo;
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400 mt-2 flex-wrap">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatMs(entry.response_time_ms)}
        </span>
        {tokens > 0 && (
          <span className="flex items-center gap-1">
            <BarChart3 className="h-3 w-3" />
            {tokens} tokens
          </span>
        )}
        {entry.source_section_preview && (
          <span className="truncate max-w-xs" title={entry.source_section_preview}>
            Evidence: {entry.source_section_preview}
          </span>
        )}
        {sectionRelevance && <span>Section: {sectionRelevance}</span>}
        {textQualityScore !== undefined && textQualityScore < 1.0 && (
          <span>Quality: {(textQualityScore * 100).toFixed(0)}%</span>
        )}
      </div>
    </div>
  );
}
