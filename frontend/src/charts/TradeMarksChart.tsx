import { CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";
import type { MarkRow } from "../api/types";
import { rupees, rupeesWhole } from "../lib/format";
import { ChartFrame, COLORS, tooltipDay } from "./common";

/** One trade's net mark-to-market (₹, after costs) on each day it was held (marks.csv). */
export function TradeMarksChart({ marks }: { marks: MarkRow[] }) {
  return (
    <ChartFrame title="Mark-to-market" description="net ₹ at each close, entry to expiry" height={240}>
      <LineChart data={marks} margin={{ left: 16, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="date" tickFormatter={tooltipDay} />
        <YAxis tickFormatter={rupeesWhole} width={96} />
        <ReferenceLine y={0} stroke="#64748b" />
        <Tooltip labelFormatter={tooltipDay} formatter={(v) => rupees(v as number)} />
        <Line name="Net MTM" dataKey="mtm_rs_net" stroke={COLORS.net} isAnimationActive={false} connectNulls={false} />
      </LineChart>
    </ChartFrame>
  );
}
