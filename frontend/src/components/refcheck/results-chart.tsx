"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { ResultsSummary } from "@/lib/types";

const VERDICT_COLORS: Record<string, string> = {
  supported: "#16A34A",
  partially_supported: "#D97706",
  not_supported: "#DC2626",
  contradicted: "#991B1B",
  cannot_verify: "#9CA3AF",
};

interface ResultsChartProps {
  summary: ResultsSummary;
}

export function ResultsChart({ summary }: ResultsChartProps) {
  const data = [
    { name: "Supported", value: summary.supported, key: "supported" },
    { name: "Partial", value: summary.partially_supported, key: "partially_supported" },
    { name: "Not Supported", value: summary.not_supported, key: "not_supported" },
    { name: "Contradicted", value: summary.contradicted, key: "contradicted" },
    { name: "Can't Verify", value: summary.cannot_verify, key: "cannot_verify" },
  ];

  if (summary.total === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-muted-foreground">
        No verification results yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
        <Tooltip />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((entry) => (
            <Cell key={entry.key} fill={VERDICT_COLORS[entry.key] ?? "#9CA3AF"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
