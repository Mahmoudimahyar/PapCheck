"use client";

const VERDICT_COLORS: Record<string, { bg: string; label: string }> = {
  supported: { bg: "bg-green-500", label: "Supported" },
  partially_supported: { bg: "bg-amber-500", label: "Partial" },
  not_supported: { bg: "bg-red-500", label: "Not Supported" },
  contradicted: { bg: "bg-red-800", label: "Contradicted" },
  cannot_verify: { bg: "bg-gray-400", label: "Can't Verify" },
  pending: { bg: "bg-blue-400", label: "Pending" },
};

interface HighlightLegendProps {
  legend: Record<string, number>;
  activeFilter: string | null;
  onFilterClick: (verdict: string | null) => void;
}

export function HighlightLegend({ legend, activeFilter, onFilterClick }: HighlightLegendProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 py-2 px-3 bg-muted/50 rounded-md text-sm">
      <span className="font-medium text-muted-foreground">Legend:</span>
      {Object.entries(legend).map(([verdict, count]) => {
        const config = VERDICT_COLORS[verdict] ?? VERDICT_COLORS.pending;
        const isActive = activeFilter === verdict;
        return (
          <button
            key={verdict}
            onClick={() => onFilterClick(isActive ? null : verdict)}
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded transition-colors ${
              isActive ? "ring-2 ring-offset-1 ring-foreground/40" : "hover:bg-muted"
            }`}
          >
            <span className={`inline-block w-3 h-3 rounded-sm ${config.bg}`} />
            <span>{count}</span>
            <span className="text-muted-foreground">{config.label}</span>
          </button>
        );
      })}
    </div>
  );
}
