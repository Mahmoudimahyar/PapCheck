"use client";

import {
  PARTIAL_TYPE_ORDER,
  partialFilterLabel,
  type PartialFilter,
  type PartialSummary,
} from "@/lib/partial-types";

interface ResultsFilterBarProps {
  verdictFilter: string;
  priorityFilter: string;
  onVerdictChange: (value: string) => void;
  onPriorityChange: (value: string) => void;
  resultCount: number;
  totalCount: number;
  loading: boolean;
  /** V5.4 partial-type chips (counts from the results summary). */
  partialFilter?: PartialFilter;
  onPartialChange?: (value: PartialFilter) => void;
  partialSummary?: PartialSummary;
}

const CHIP = "px-2 py-0.5 rounded-full border text-xs transition-colors";
const CHIP_ON = "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300";
const CHIP_OFF = "border-border text-muted-foreground hover:border-blue-300";

function PartialChips({
  filter, onChange, summary,
}: { filter: PartialFilter; onChange: (value: PartialFilter) => void; summary?: PartialSummary }) {
  const chips: { value: PartialFilter; count: number }[] = PARTIAL_TYPE_ORDER
    .map((key) => ({ value: key as PartialFilter, count: summary?.partial_types?.[key] ?? 0 }))
    .filter((chip) => chip.count > 0);
  if ((summary?.guarded ?? 0) > 0) chips.push({ value: "guarded", count: summary?.guarded ?? 0 });
  // A guard-specific filter set from the breakdown card has no chip of its own.
  if (filter !== "all" && !chips.some((chip) => chip.value === filter)) chips.push({ value: filter, count: -1 });
  if (chips.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-xs text-muted-foreground mr-1">Partial type</span>
      <button type="button" onClick={() => onChange("all")} className={`${CHIP} ${filter === "all" ? CHIP_ON : CHIP_OFF}`}>
        All
      </button>
      {chips.map((chip) => {
        const active = filter === chip.value;
        return (
          <button
            key={chip.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(active ? "all" : chip.value)}
            className={`${CHIP} ${active ? CHIP_ON : CHIP_OFF}`}
          >
            {partialFilterLabel(chip.value)}
            {chip.count >= 0 && <span className="ml-1 tabular-nums">{chip.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function ResultsFilterBar({
  verdictFilter,
  priorityFilter,
  onVerdictChange,
  onPriorityChange,
  resultCount,
  totalCount,
  loading,
  partialFilter = "all",
  onPartialChange,
  partialSummary,
}: ResultsFilterBarProps) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-x-4 gap-y-2 items-center">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Verdict</label>
          <select
            value={verdictFilter}
            onChange={(e) => onVerdictChange(e.target.value)}
            className="border rounded px-2 py-1 text-sm bg-background"
          >
            <option value="all">All</option>
            <option value="supported">Supported</option>
            <option value="partially_supported">Partially Supported</option>
            <option value="not_supported">Not Supported</option>
            <option value="contradicted">Contradicted</option>
            <option value="cannot_verify">Cannot Verify</option>
            <option value="not_relevant">Not Relevant</option>
            <option value="needs_review">Needs Review</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Priority</label>
          <select
            value={priorityFilter}
            onChange={(e) => onPriorityChange(e.target.value)}
            className="border rounded px-2 py-1 text-sm bg-background"
          >
            <option value="all">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="ml-auto text-sm text-muted-foreground">
          {loading ? "Loading..." : `${resultCount} of ${totalCount} results`}
        </div>
      </div>
      {onPartialChange && (
        <PartialChips filter={partialFilter} onChange={onPartialChange} summary={partialSummary} />
      )}
    </div>
  );
}
