"use client";

import { Badge } from "@/components/ui/badge";
import type { Verdict } from "@/lib/types";

const VERDICT_CONFIG: Record<Verdict, { label: string; className: string }> = {
  supported: { label: "Supported", className: "bg-green-600 text-white hover:bg-green-700" },
  partially_supported: { label: "Partial", className: "bg-amber-500 text-white hover:bg-amber-600" },
  not_supported: { label: "Not Supported", className: "bg-red-600 text-white hover:bg-red-700" },
  contradicted: { label: "Contradicted", className: "bg-red-800 text-white hover:bg-red-900" },
  cannot_verify: { label: "Can't Verify", className: "bg-gray-400 text-white hover:bg-gray-500" },
};

interface VerificationBadgeProps {
  verdict: Verdict;
  className?: string;
}

export function VerificationBadge({ verdict, className = "" }: VerificationBadgeProps) {
  const config = VERDICT_CONFIG[verdict] ?? VERDICT_CONFIG.cannot_verify;
  return (
    <Badge className={`${config.className} ${className}`}>
      {config.label}
    </Badge>
  );
}

interface PriorityBadgeProps {
  priority: string;
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  const styles: Record<string, string> = {
    high: "bg-red-100 text-red-800 border-red-200",
    medium: "bg-amber-100 text-amber-800 border-amber-200",
    low: "bg-gray-100 text-gray-600 border-gray-200",
  };
  return (
    <Badge variant="outline" className={styles[priority] ?? styles.low}>
      {priority}
    </Badge>
  );
}
