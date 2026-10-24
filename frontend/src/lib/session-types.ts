/** Session, pipeline progress, cost and report-preview types. */

import type { SourceIssue } from "./signal-types";

export interface Session {
  id: string;
  status: "created" | "running" | "paused" | "complete" | "error";
  created_at: string;
  manuscript_filename: string;
  pdf_count: number;
  // V5.8: GET /api/sessions/{id} only; same as ResultsSummary.degraded_notices
  degraded_notices?: string[];
}

// V3: Session list
export interface SessionListResponse {
  sessions: Session[];
  total: number;
  page: number;
  per_page: number;
}

export interface PipelineEvent {
  stage: number;
  status: "running" | "complete" | "error" | "needs_input" | "pipeline_complete";
  progress?: StageProgress;
  message?: string;
  elapsed_seconds?: number;
  intervention?: { type: string; count?: number };
}

export interface StageProgress {
  current: number;
  total: number;
  percent?: number;
  rate?: number;
  elapsed_seconds?: number;
  estimated_remaining_seconds?: number;
}

export interface StageStatus {
  stage: number;
  name: string;
  status: "pending" | "running" | "complete" | "error" | "needs_input";
  elapsed_seconds: number;
  progress_current: number;
  progress_total: number;
  progress_percent: number;
  progress_rate: number;
  progress_eta: number;
  message: string;
}

export interface CostSummary {
  total_usd: number;
  total_calls: number;
  by_model: Record<string, number>;
  by_task: Record<string, number>;
  by_tier: Record<number, number>;
}

// V2 Report types
export interface ReportPreview {
  summary: Record<string, number>;
  critical_findings: Array<Record<string, string>>;
  minor_issues: Array<Record<string, string>>;
  retracted: Array<Record<string, string>>;
  source_issues?: SourceIssue[];
  overrides_count: number;
  generated_at: string;
}
