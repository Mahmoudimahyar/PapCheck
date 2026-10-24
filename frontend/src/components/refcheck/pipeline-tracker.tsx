"use client";

import { Progress } from "@/components/ui/progress";
import { Check, Circle, Loader2, XCircle, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StageStatus } from "@/lib/types";

interface PipelineTrackerProps {
  stages: StageStatus[];
}

function formatDuration(seconds: number): string {
  if (seconds < 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const min = Math.floor(seconds / 60);
  const sec = Math.round(seconds % 60);
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hrs = Math.floor(min / 60);
  return `${hrs}h ${min % 60}m`;
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "complete":
      return <Check className="h-4 w-4 text-green-700 dark:text-green-500" />;
    case "running":
      return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
    case "error":
      return <XCircle className="h-4 w-4 text-red-500" />;
    case "needs_input":
      return <AlertCircle className="h-4 w-4 text-amber-500" />;
    default:
      return <Circle className="h-4 w-4 text-muted-foreground/40" />;
  }
}

function StageRow({ stage }: { stage: StageStatus }) {
  const isRunning = stage.status === "running";
  const isComplete = stage.status === "complete";
  const hasProgress = isRunning && stage.progress_total > 0;

  return (
    <div
      className={cn(
        "px-3 py-2 rounded-md transition-colors",
        isRunning && "bg-muted/50"
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusIcon status={stage.status} />
          <span
            className={cn(
              "text-sm font-medium",
              stage.status === "pending" && "text-muted-foreground"
            )}
          >
            {stage.name}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">
          {isComplete && stage.elapsed_seconds > 0 && (
            <span>{formatDuration(stage.elapsed_seconds)}</span>
          )}
          {isRunning && stage.progress_percent > 0 && (
            <span>{Math.round(stage.progress_percent)}%</span>
          )}
        </div>
      </div>

      {hasProgress && (
        <div className="mt-1.5 ml-6">
          <Progress
            value={stage.progress_percent}
            className="h-1"
          />
          <p className="text-xs text-muted-foreground mt-1">
            {stage.progress_current}/{stage.progress_total}
            {stage.progress_rate > 0 && (
              <> &middot; {stage.progress_rate.toFixed(1)}/s</>
            )}
            {stage.progress_eta > 0 && (
              <> &middot; ~{formatDuration(stage.progress_eta)} left</>
            )}
          </p>
        </div>
      )}

      {isComplete && stage.message && (
        <p className="text-xs text-muted-foreground ml-6 mt-0.5">
          {stage.message}
        </p>
      )}

      {stage.status === "error" && stage.message && (
        <p className="text-xs text-red-600 dark:text-red-400 ml-6 mt-0.5">{stage.message}</p>
      )}
    </div>
  );
}

export function PipelineTracker({ stages }: PipelineTrackerProps) {
  return (
    <div className="space-y-1">
      <h3 className="text-lg font-medium mb-3">Pipeline Progress</h3>
      {stages.map((stage) => (
        <StageRow key={stage.stage} stage={stage} />
      ))}
    </div>
  );
}
