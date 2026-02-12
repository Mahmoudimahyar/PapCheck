"use client";

import { Progress } from "@/components/ui/progress";
import type { StageStatus } from "@/lib/types";

interface PipelineTrackerProps {
  stages: StageStatus[];
}

const STATUS_ICONS: Record<string, string> = {
  pending: "○",
  running: "◌",
  complete: "✓",
  error: "✗",
  needs_input: "!",
};

export function PipelineTracker({ stages }: PipelineTrackerProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">Pipeline Progress</h3>
      {stages.map((stage) => (
        <div key={stage.stage} className="flex items-start gap-3">
          <span
            className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
              stage.status === "complete"
                ? "bg-success text-white"
                : stage.status === "running"
                ? "bg-info text-white animate-pulse"
                : stage.status === "error"
                ? "bg-destructive text-white"
                : stage.status === "needs_input"
                ? "bg-warning text-white"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {STATUS_ICONS[stage.status] || "?"}
          </span>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{stage.name}</span>
              <span className="text-xs text-muted-foreground">
                {stage.status === "complete"
                  ? `${stage.elapsed_seconds.toFixed(1)}s`
                  : stage.status === "running"
                  ? "..."
                  : "waiting"}
              </span>
            </div>
            {stage.message && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {stage.message}
              </p>
            )}
            {stage.status === "running" && stage.progress_total > 0 && (
              <Progress
                value={(stage.progress_current / stage.progress_total) * 100}
                className="mt-1 h-1.5"
              />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
