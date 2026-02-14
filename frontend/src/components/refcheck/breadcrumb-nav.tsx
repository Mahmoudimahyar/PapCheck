"use client";

import Link from "next/link";

interface BreadcrumbNavProps {
  sessionId: string;
  current: "progress" | "review" | "claims" | "results" | "viewer" | "report";
}

const STEPS = [
  { key: "progress", label: "Progress", path: "" },
  { key: "review", label: "Review", path: "/review" },
  { key: "claims", label: "Claims", path: "/claims" },
  { key: "results", label: "Results", path: "/results" },
  { key: "viewer", label: "Viewer", path: "/viewer" },
  { key: "report", label: "Report", path: "/report" },
] as const;

export function BreadcrumbNav({ sessionId, current }: BreadcrumbNavProps) {
  const base = `/verify/${sessionId}`;

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted-foreground mb-4">
      <Link href="/" className="hover:text-foreground transition-colors">
        Upload
      </Link>
      {STEPS.map((step) => {
        const isActive = step.key === current;
        return (
          <span key={step.key} className="flex items-center gap-1">
            <span className="mx-1 select-none">/</span>
            {isActive ? (
              <span className="font-medium text-foreground">{step.label}</span>
            ) : (
              <Link href={`${base}${step.path}`} className="hover:text-foreground transition-colors">
                {step.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
