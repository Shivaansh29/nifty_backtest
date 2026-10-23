import type { YearRow } from "../api/types";
import { decimal, fraction, percentValue, rupees } from "../lib/format";

/** yearly.csv as saved. Trade statistics group trades by expiry year; returns and drawdowns
 *  group days by date (see M4 notes). Partial years are flagged, never annualised. */
export function YearlyTable({ rows }: { rows: YearRow[] }) {
  const hasBenchmark = rows.some((r) => r.benchmark_return !== undefined);
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm" aria-label="Calendar years">
        <thead className="bg-slate-100 text-right text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2 text-left">Year</th>
            <th className="px-3 py-2">Days</th>
            <th className="px-3 py-2">Trades</th>
            <th className="px-3 py-2">Win rate</th>
            <th className="px-3 py-2">Net ₹ (by date)</th>
            <th className="px-3 py-2">Return</th>
            {hasBenchmark ? <th className="px-3 py-2">TRI return</th> : null}
            <th className="px-3 py-2">Mean % premium</th>
            <th className="px-3 py-2">t (% premium)</th>
            <th className="px-3 py-2">t (points)</th>
            <th className="px-3 py-2">Max DD %</th>
            <th className="px-3 py-2">Sharpe (notional)</th>
          </tr>
        </thead>
        <tbody className="text-right tabular-nums">
          {rows.map((r) => (
            <tr key={r.year} className="border-t border-slate-100">
              <td className="px-3 py-1.5 text-left">
                {r.year}
                {r.partial_year ? <span className="ml-1 text-xs text-slate-500">(partial)</span> : null}
                {r.note ? <span className="block text-xs text-amber-700">{r.note}</span> : null}
              </td>
              <td className="px-3 py-1.5">{r.trading_days}</td>
              <td className="px-3 py-1.5">{r.trades}</td>
              <td className="px-3 py-1.5">{fraction(r.win_rate)}</td>
              <td className="px-3 py-1.5">{rupees(r.pnl_rs)}</td>
              <td className="px-3 py-1.5">{fraction(r.return)}</td>
              {hasBenchmark ? <td className="px-3 py-1.5">{fraction(r.benchmark_return)}</td> : null}
              <td className="px-3 py-1.5">{percentValue(r.mean_pct_premium_net)}</td>
              <td className="px-3 py-1.5">{decimal(r.t_stat_pct_premium_net)}</td>
              <td className="px-3 py-1.5">{decimal(r.t_stat_points_net)}</td>
              <td className="px-3 py-1.5">
                {fraction(r.max_drawdown_pct)}
                {r.max_drawdown_lower_bound ? <span title="observed lower bound: days missing"> ≥</span> : null}
              </td>
              <td className="px-3 py-1.5">{decimal(r.sharpe_notional)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
