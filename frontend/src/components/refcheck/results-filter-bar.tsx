"use client";

interface ResultsFilterBarProps {
  verdictFilter: string;
  priorityFilter: string;
  onVerdictChange: (value: string) => void;
  onPriorityChange: (value: string) => void;
  resultCount: number;
  totalCount: number;
  loading: boolean;
}

export function ResultsFilterBar({
  verdictFilter,
  priorityFilter,
  onVerdictChange,
  onPriorityChange,
  resultCount,
  totalCount,
  loading,
}: ResultsFilterBarProps) {
  return (
    <div className="flex gap-4 items-center">
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
  );
}
