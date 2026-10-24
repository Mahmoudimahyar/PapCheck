"use client";

import { CheckCircle2, Clock, Loader2 } from "lucide-react";
import type { ReverifyState } from "@/hooks/use-reverify-watch";

const VERDICT_WORDS: Record<string, string> = {
  supported: "supported",
  partially_supported: "partially supported",
  not_supported: "not supported",
  contradicted: "contradicted",
  cannot_verify: "cannot verify",
  not_relevant: "not relevant",
};

function verdictText(verdicts: Record<string, number>): string {
  return Object.entries(verdicts)
    .sort(([, a], [, b]) => b - a)
    .map(([v, n]) => `${n} ${VERDICT_WORDS[v] ?? v}`)
    .join(", ");
}

function plural(n: number): string {
  return `${n} claim${n !== 1 ? "s" : ""}`;
}

/** One line under a reference row: re-verifying / re-verified / still running. */
export function ReverifyStatus({ state }: { state: ReverifyState }) {
  const total = state.claimIds.length;
  if (state.status === "running") {
    return (
      <p className="flex items-center gap-1 text-[11px] text-blue-700 dark:text-blue-300" role="status">
        <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
        Re-verifying {plural(total)}... {state.done > 0 && `(${state.done}/${total})`}
      </p>
    );
  }
  if (state.status === "done") {
    return (
      <p className="flex items-start gap-1 text-[11px] text-green-800 dark:text-green-300" role="status">
        <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
        <span>Re-verified {plural(total)}: {verdictText(state.verdicts)}</span>
      </p>
    );
  }
  return (
    <p className="flex items-start gap-1 text-[11px] text-amber-800 dark:text-amber-300" role="status">
      <Clock className="mt-0.5 h-3 w-3 shrink-0" />
      <span>
        Re-verification still running ({state.done}/{total} updated). Reload the page later; a failure is
        logged on the session.
      </span>
    </p>
  );
}

/** Page-level summary, so progress is visible whichever tab or row is on screen. */
export function ReverifyBanner({ states }: { states: Record<number, ReverifyState> }) {
  const entries = Object.entries(states).map(([id, s]) => [Number(id), s] as const);
  if (entries.length === 0) return null;
  const running = entries.filter(([, s]) => s.status === "running").length;
  const slow = entries.some(([, s]) => s.status === "timeout");
  const headline = running > 0
    ? `Re-verifying ${running} reference${running !== 1 ? "s" : ""} with the new PDF or abstract...`
    : slow
      ? "Some re-verifications are taking longer than expected."
      : "Re-verification finished; the table and counts below are reloaded.";
  return (
    <div className="space-y-1 rounded border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-800 dark:bg-blue-950">
      <p className="font-medium text-blue-900 dark:text-blue-100">{headline}</p>
      <ul className="space-y-0.5">
        {entries.map(([id, s]) => (
          <li key={id} className="flex items-start gap-1.5">
            <span className="font-mono text-xs leading-4">[{id}]</span>
            <div className="min-w-0"><ReverifyStatus state={s} /></div>
          </li>
        ))}
      </ul>
    </div>
  );
}
