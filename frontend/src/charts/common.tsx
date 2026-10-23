// Shared chart settings. Charts receive the API's arrays as they are (no reshaping), and a
// missing value (null) is drawn as a gap, never joined across.
import type { ReactNode } from "react";
import { ResponsiveContainer } from "recharts";
import { day, month } from "../lib/format";

export const COLORS = {
  net: "#4338ca",
  gross: "#94a3b8",
  benchmark: "#d97706",
};

export function tickDay(value: string): string {
  return value.length === 10 ? month(value.slice(0, 7)) : value;
}

export function tooltipDay(value: unknown): string {
  return typeof value === "string" ? day(value) : String(value);
}

export function ChartFrame({
  title,
  description,
  height = 300,
  children,
}: {
  title: string;
  description: string;
  height?: number;
  children: ReactNode;
}) {
  return (
    <figure className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-label={title}>
      <figcaption className="mb-2">
        <span className="font-semibold">{title}</span>
        <span className="ml-2 text-xs text-slate-500">{description}</span>
      </figcaption>
      <ResponsiveContainer width="100%" height={height} initialDimension={{ width: 800, height }}>
        {children as React.ReactElement}
      </ResponsiveContainer>
    </figure>
  );
}
