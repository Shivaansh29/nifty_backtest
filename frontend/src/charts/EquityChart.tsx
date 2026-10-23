import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import type { DailyPoint, EquityPoint } from "../api/types";
import { rupees, rupeesWhole } from "../lib/format";
import { ChartFrame, COLORS, tickDay, tooltipDay } from "./common";

/** Net equity against NIFTY 50 TRI buy-and-hold (both start from the run's capital), with
 *  gross equity (no costs) on request. Values are daily.csv's, unchanged. */
export function EquityChart({ daily }: { daily: DailyPoint[] }) {
  const [showGross, setShowGross] = useState(false);
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 text-xs text-slate-600">
        <input type="checkbox" checked={showGross} onChange={(e) => setShowGross(e.target.checked)} />
        Show gross equity (before slippage and charges)
      </label>
      <ChartFrame title="Equity" description="daily close, ₹; NIFTY 50 TRI buy-and-hold from the same capital">
        <LineChart data={daily} margin={{ left: 16, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tickFormatter={tickDay} minTickGap={40} />
          <YAxis tickFormatter={rupeesWhole} width={96} domain={["auto", "auto"]} />
          <Tooltip labelFormatter={tooltipDay} formatter={(v) => rupees(v as number)} />
          <Legend />
          <Line name="Strategy (net)" dataKey="equity_net_rs" stroke={COLORS.net} dot={false} isAnimationActive={false} connectNulls={false} />
          <Line name="NIFTY 50 TRI" dataKey="benchmark_equity_rs" stroke={COLORS.benchmark} dot={false} isAnimationActive={false} connectNulls={false} />
          {showGross ? (
            <Line name="Strategy (gross)" dataKey="equity_gross_rs" stroke={COLORS.gross} dot={false} isAnimationActive={false} connectNulls={false} />
          ) : null}
        </LineChart>
      </ChartFrame>
    </div>
  );
}

/** For runs saved before daily.csv existed: the net equity curve from equity.csv only. */
export function NetEquityChart({ equity }: { equity: EquityPoint[] }) {
  return (
    <ChartFrame title="Equity (net)" description="daily close, ₹, from equity.csv">
      <LineChart data={equity} margin={{ left: 16, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="date" tickFormatter={tickDay} minTickGap={40} />
        <YAxis tickFormatter={rupeesWhole} width={96} domain={["auto", "auto"]} />
        <Tooltip labelFormatter={tooltipDay} formatter={(v) => rupees(v as number)} />
        <Line name="Strategy (net)" dataKey="equity_rs" stroke={COLORS.net} dot={false} isAnimationActive={false} connectNulls={false} />
      </LineChart>
    </ChartFrame>
  );
}
