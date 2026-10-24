"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Cpu, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getHealth } from "@/lib/api";
import { ROLE_LABELS, formatMs } from "@/lib/cascade";
import type { HealthResponse, LLMRole, RoleHealth } from "@/lib/types";

const ROLE_ORDER: LLMRole[] = [
  "screen", "verifier", "judge", "confirm", "adjudicator", "utility", "embedding",
];

const SUMMARY: Record<HealthResponse["llm"], { text: string; tone: string }> = {
  ok: { text: "All AI models available", tone: "text-green-700 dark:text-green-400" },
  degraded: { text: "Running in degraded mode", tone: "text-amber-700 dark:text-amber-400" },
  unavailable: { text: "Verification models unavailable", tone: "text-red-700 dark:text-red-400" },
  unknown: { text: "AI model status unknown", tone: "text-muted-foreground" },
};

/** V5.8: why a role is degraded, in a few words (billing = no credits / quota). */
const CAUSE_LABELS: Record<string, string> = {
  billing: "no credits", auth: "key rejected", no_key: "no API key",
  not_found: "model unavailable", network: "network error", rate_limit: "rate limited",
  budget: "spend cap reached",
};

const MODE_LABELS: Record<string, string> = {
  fallback: "degraded fallback", skipped: "skipped", bm25_only: "BM25 only",
  unavailable: "unavailable",
};

function dotClass(m: RoleHealth): string {
  if (!m.enabled) return "bg-gray-300 dark:bg-gray-600";
  if (m.degraded && m.role !== "verifier") return "bg-amber-500";
  if (!m.available || m.probe_ok === false) return "bg-red-500";
  return m.probe_ok ? "bg-green-500" : "bg-green-300";
}

function DegradedLine({ m }: { m: RoleHealth }) {
  const cause = m.cause ? CAUSE_LABELS[m.cause] ?? m.cause : null;
  return (
    <div className="pl-[6.5rem] text-[11px] text-amber-700 dark:text-amber-400">
      {MODE_LABELS[m.degraded_mode ?? ""] ?? "degraded"}
      {cause && ` · ${cause}${m.persistent ? "" : " (temporary)"}`}
      {m.effect && <span className="text-muted-foreground"> — {m.effect}</span>}
    </div>
  );
}

function RoleRow({ m }: { m: RoleHealth }) {
  const model = m.display_name || m.model_id;
  return (
    <div>
      <div className="flex items-center gap-2 text-xs py-0.5">
        <span className={`h-2 w-2 rounded-full shrink-0 ${dotClass(m)}`} />
        <span className="w-24 text-muted-foreground">{ROLE_LABELS[m.role] ?? m.role}</span>
        <span className="font-mono truncate">
          {!m.enabled ? "disabled" : model ?? "no working model"}
          {m.reasoning_effort && m.enabled && model ? ` · ${m.reasoning_effort}` : ""}
        </span>
        {m.fallback_index > 0 && m.available && !m.degraded && (
          <span className="text-amber-700 dark:text-amber-400">fallback</span>
        )}
        {m.latency_ms != null && <span className="text-muted-foreground">{formatMs(m.latency_ms)}</span>}
        {m.last_error && (!m.available || m.fallback_index > 0) && (
          <span className="text-red-600 dark:text-red-400 truncate" title={m.last_error}>
            {m.last_error}
          </span>
        )}
      </div>
      {m.degraded && <DegradedLine m={m} />}
    </div>
  );
}

/** Compact per-role LLM status from /api/health (live check on demand). V5.8: degraded
 *  roles (confirm on a same-family fallback, screen skipped, BM25-only retrieval) say why,
 *  and persistent causes (no credits, bad key) show the fix even when collapsed. */
export function ModelStatusCard() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setFailed(true));
  }, []);

  const runLiveCheck = async () => {
    setChecking(true);
    try {
      setHealth(await getHealth(true));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setChecking(false);
    }
  };

  if (failed && !health) {
    return <p className="text-xs text-muted-foreground">Backend not reachable — model status unavailable.</p>;
  }
  if (!health) return null;

  const summary = SUMMARY[health.llm] ?? SUMMARY.unknown;
  const roles = ROLE_ORDER.map((r) => health.models[r]).filter((m): m is RoleHealth => !!m);
  const actions = health.actions ?? [];

  return (
    <div className="rounded-md border px-3 py-2 text-sm bg-muted/20">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 text-left">
        <Cpu className="h-4 w-4 text-primary" />
        <span className={summary.tone}>{summary.text}</span>
        {health.deep && <span className="text-xs text-muted-foreground">(live check)</span>}
        {health.privacy_profile !== "standard" && (
          <span className="text-xs text-muted-foreground">· profile {health.privacy_profile}</span>
        )}
        <span className="ml-auto">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
      </button>
      {actions.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-amber-700 dark:text-amber-400">
          {actions.map((a) => <li key={a}>{a}</li>)}
        </ul>
      )}
      {open && (
        <div className="mt-2 space-y-1">
          {roles.map((m) => <RoleRow key={m.role} m={m} />)}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-muted-foreground">
              Decisions API: {health.decisions_api}
            </span>
            <Button variant="outline" size="sm" className="h-6 text-xs px-2" onClick={runLiveCheck} disabled={checking}>
              {checking && <Loader2 className="h-3 w-3 animate-spin" />}
              Live check
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
