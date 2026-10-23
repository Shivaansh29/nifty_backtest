import { Area, AreaChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import type { DailyPoint } from "../api/types";
import { fraction } from "../lib/format";
import { ChartFrame, COLORS, tickDay, tooltipDay } from "./common";

/** Fall below the running peak, as a fraction of that peak (daily.csv). The API gives
 *  drawdowns as positive numbers; the axis is reversed so they hang down from zero, rather
 *  than the dashboard changing any value. */
export function DrawdownChart({ daily }: { daily: DailyPoint[] }) {
  return (
    <ChartFrame title="Drawdown" description="% below the running peak (peak starts at the capital)">
      <AreaChart data={daily} margin={{ left: 16, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="date" tickFormatter={tickDay} minTickGap={40} />
        <YAxis reversed tickFormatter={fraction} width={72} />
        <Tooltip labelFormatter={tooltipDay} formatter={(v) => fraction(v as number)} />
        <Legend />
        <Area name="Strategy (net)" dataKey="drawdown_net_pct" stroke={COLORS.net} fill={COLORS.net} fillOpacity={0.25} isAnimationActive={false} connectNulls={false} />
        <Area name="NIFTY 50 TRI" dataKey="benchmark_drawdown_pct" stroke={COLORS.benchmark} fill={COLORS.benchmark} fillOpacity={0.1} isAnimationActive={false} connectNulls={false} />
      </AreaChart>
    </ChartFrame>
  );
}
