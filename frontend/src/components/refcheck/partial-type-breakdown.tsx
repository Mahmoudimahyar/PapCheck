"use client";

/**
 * V5.4 Results-page section: partially supported results grouped by type (label, count,
 * one-line meaning, minor/major, author action) and supported results whose concern a guard
 * cleared. Clicking a row filters the results table to that group; clicking again clears it.
 */

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SeverityBadge } from "@/components/refcheck/partial-finding";
import {
  GUARD_LABELS,
  PARTIAL_TYPE_INFO,
  type GuardDetail,
  type PartialBreakdown,
  type PartialFilter,
  type PartialTypeDetail,
} from "@/lib/partial-types";

interface PartialTypeBreakdownProps {
  breakdown: PartialBreakdown;
  activeFilter: PartialFilter;
  onSelect: (filter: PartialFilter) => void;
}

const ROW = "w-full text-left rounded border p-2 transition-colors hover:bg-muted/60";
const ACTIVE = "border-blue-500 bg-blue-50/50 dark:bg-blue-950";

function Severity({ detail }: { detail: PartialTypeDetail }) {
  if (detail.major > 0 && detail.minor > 0) {
    return (
      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
        <SeverityBadge severity="major" /> {detail.major}
        <SeverityBadge severity="minor" /> {detail.minor}
      </span>
    );
  }
  return <SeverityBadge severity={detail.major > 0 ? "major" : detail.minor > 0 ? "minor" : detail.severity} />;
}

function TypeRow({ detail, active, onClick }: { detail: PartialTypeDetail; active: boolean; onClick: () => void }) {
  const info = PARTIAL_TYPE_INFO[detail.type];
  return (
    <button type="button" onClick={onClick} className={`${ROW} ${active ? ACTIVE : ""}`} aria-pressed={active}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium">{info?.label ?? detail.label}</span>
        <Severity detail={detail} />
        <span className="ml-auto text-lg font-semibold tabular-nums text-amber-700 dark:text-amber-400">{detail.count}</span>
      </div>
      <p className="text-xs text-muted-foreground">{info?.meaning ?? detail.meaning}</p>
      {detail.author_action && (
        <p className="text-[11px] text-muted-foreground mt-0.5">
          <span className="font-medium">What to do:</span> {detail.author_action}
        </p>
      )}
    </button>
  );
}

function GuardRow({ detail, active, onClick }: { detail: GuardDetail; active: boolean; onClick: () => void }) {
  const guard = GUARD_LABELS[detail.guard];
  return (
    <button type="button" onClick={onClick} className={`${ROW} ${active ? ACTIVE : ""}`} aria-pressed={active}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">Cleared: {guard?.label ?? detail.label}</span>
        <span className="ml-auto text-lg font-semibold tabular-nums text-green-700 dark:text-green-400">{detail.count}</span>
      </div>
      <p className="text-xs text-muted-foreground">{guard?.explanation ?? detail.explanation}</p>
    </button>
  );
}

export function PartialTypeBreakdown({ breakdown, activeFilter, onSelect }: PartialTypeBreakdownProps) {
  const types = breakdown.types.filter((t) => t.count > 0);
  const guards = breakdown.guards.filter((g) => g.count > 0);
  if (types.length === 0 && guards.length === 0) return null;
  const toggle = (filter: PartialFilter) => onSelect(activeFilter === filter ? "all" : filter);

  return (
    <Card>
      <CardHeader className="pb-2">
        <h3 className="text-lg font-medium">Partially supported — by type</h3>
        <p className="text-xs text-muted-foreground">
          Each partial verdict is filed under its most serious problem. Major: the sentence states something
          the source does not. Minor: the core point is supported. Click a row to filter the table.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {types.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {types.map((t) => (
              <TypeRow key={t.type} detail={t} active={activeFilter === t.type} onClick={() => toggle(t.type)} />
            ))}
          </div>
        )}
        {guards.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium">Supported with a note ({breakdown.guarded})</h4>
              <span className="text-xs text-muted-foreground">A concern was checked and cleared; no change needed.</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {guards.map((g) => {
                const filter: PartialFilter = `guarded:${g.guard}`;
                return <GuardRow key={g.guard} detail={g} active={activeFilter === filter} onClick={() => toggle(filter)} />;
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
