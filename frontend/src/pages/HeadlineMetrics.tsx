// Headline numbers and the net / gross / TRI comparison, straight from metrics.json.
import type { BenchmarkMetrics, Metrics, Ratio, StrategyMetrics } from "../api/types";
import { MetricCard } from "../components/MetricCard";
import { Notice } from "../components/States";
import { decimal, fraction, NA, percentValue, rupees } from "../lib/format";
import { href } from "../lib/route";

function ratio(r: Ratio): string {
  return decimal(r.value);
}

/** Notes the metrics carry about missing data (only present in newer runs). */
function seriesNotes(label: string, s: StrategyMetrics | BenchmarkMetrics): string[] {
  const notes: string[] = [];
  if (s.totals_note) notes.push(`${label}: ${s.totals_note}`);
  if (s.max_drawdown_note) notes.push(`${label}: ${s.max_drawdown_note}`);
  return notes;
}

function drawdownBadge(s: StrategyMetrics | BenchmarkMetrics): string | undefined {
  return s.max_drawdown_lower_bound ? "lower bound" : undefined;
}

type Series = StrategyMetrics | BenchmarkMetrics;
interface Row {
  label: string;
  shared: (s: Series) => string;
  strategyOnly?: boolean;
}

export function HeadlineMetrics({ metrics, runId }: { metrics: Metrics; runId: string }) {
  const net = metrics.strategy_net;
  const gross = metrics.strategy_gross;
  const t = metrics.trades;
  const bench = "not_computed" in metrics.benchmark_nifty50_tri ? null : metrics.benchmark_nifty50_tri;
  const benchReason =
    "not_computed" in metrics.benchmark_nifty50_tri ? metrics.benchmark_nifty50_tri.not_computed : null;
  const rf = fraction(metrics.metrics_config.risk_free_rate);
  const target = fraction(metrics.metrics_config.notional_target_rate);
  const notes = [
    ...seriesNotes("Net", net),
    ...seriesNotes("Gross", gross),
    ...(bench ? seriesNotes("NIFTY 50 TRI", bench) : []),
  ];

  const rows: Row[] = [
    { label: "Total P&L", shared: (s) => rupees(s.total_pnl_rs) },
    { label: "ROI (on starting capital)", shared: (s) => fraction(s.roi) },
    { label: "CAGR", shared: (s) => fraction(s.cagr) },
    { label: "Max drawdown (₹)", shared: (s) => rupees(s.max_drawdown_rs) },
    { label: "Max drawdown (%)", shared: (s) => fraction(s.max_drawdown_pct) },
    {
      label: `Sharpe, notional, ${target} target (headline)`,
      shared: (s) => ("sharpe_notional" in s ? ratio(s.sharpe_notional) : NA),
      strategyOnly: true,
    },
    {
      label: `Sortino, notional, ${target} target (headline)`,
      shared: (s) => ("sortino_notional" in s ? ratio(s.sortino_notional) : NA),
      strategyOnly: true,
    },
    { label: `Sharpe, rupee, ${rf}`, shared: (s) => ratio(s.sharpe_rupee) },
    { label: `Sortino, rupee, ${rf}`, shared: (s) => ratio(s.sortino_rupee) },
    {
      label: `Sensitivity: Sharpe notional at ${rf}`,
      shared: (s) => ("sensitivity_sharpe_notional_at_rf" in s ? ratio(s.sensitivity_sharpe_notional_at_rf) : NA),
      strategyOnly: true,
    },
    {
      label: `Sensitivity: Sortino notional at ${rf}`,
      shared: (s) => ("sensitivity_sortino_notional_at_rf" in s ? ratio(s.sensitivity_sortino_notional_at_rf) : NA),
      strategyOnly: true,
    },
  ];

  // Reasons a ratio could not be computed (e.g. a gap in the daily series).
  const ratioNotes = [
    ["Sharpe (notional)", net.sharpe_notional],
    ["Sortino (notional)", net.sortino_notional],
    ["Sharpe (rupee)", net.sharpe_rupee],
    ["Sortino (rupee)", net.sortino_rupee],
  ] as const;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="Net P&L" value={rupees(net.total_pnl_rs)} detail={`gross ${rupees(gross.total_pnl_rs)}`} />
        <MetricCard label="ROI" value={fraction(net.roi)} detail="on starting capital" />
        <MetricCard label="CAGR" value={fraction(net.cagr)} />
        <MetricCard
          label="Max drawdown"
          value={fraction(net.max_drawdown_pct)}
          detail={rupees(net.max_drawdown_rs)}
          badge={drawdownBadge(net)}
        />
        <MetricCard
          label="Sharpe"
          value={ratio(net.sharpe_notional)}
          badge="headline"
          detail={`notional, ${target} target · rupee ${ratio(net.sharpe_rupee)} at ${rf}`}
        />
        <MetricCard
          label="Sortino"
          value={ratio(net.sortino_notional)}
          badge="headline"
          detail={`notional, ${target} target · rupee ${ratio(net.sortino_rupee)} at ${rf}`}
        />
        <MetricCard
          label="Win rate"
          value={fraction(t.win_rate)}
          detail={`${t.trades} trades: ${t.wins} wins, ${t.losses} losses, ${t.zero_pnl} zero`}
        />
        <MetricCard
          label="Mean trade"
          value={percentValue(t.mean_pct_premium_net)}
          detail={`of premium (t = ${decimal(t.t_stat_pct_premium_net)}) · ${decimal(t.mean_points_net)} points (t = ${decimal(t.t_stat_points_net)})`}
        />
      </div>

      {notes.length > 0 ? (
        <Notice tone="warning" title="Missing data in this run">
          <ul className="list-disc pl-5">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {ratioNotes.some(([, r]) => r.value === null) ? (
        <Notice tone="info" title="Ratios not computed">
          <ul className="list-disc pl-5">
            {ratioNotes
              .filter(([, r]) => r.value === null)
              .map(([name, r]) => (
                <li key={name}>
                  {name}: {r.note}
                </li>
              ))}
          </ul>
        </Notice>
      ) : null}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm" aria-label="Net, gross and benchmark metrics">
          <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">Metric</th>
              <th className="px-3 py-2 text-right">Net</th>
              <th className="px-3 py-2 text-right">Gross (no costs)</th>
              <th className="px-3 py-2 text-right">NIFTY 50 TRI buy-and-hold</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-slate-100">
                <td className="px-3 py-1.5">{row.label}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{row.shared(net)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{row.shared(gross)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {bench && !row.strategyOnly ? row.shared(bench) : NA}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {benchReason ? (
          <p className="px-3 py-2 text-xs text-slate-600">Benchmark not computed: {benchReason}</p>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <h3 className="mb-2 font-semibold">Trades</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
            <dt>Average win / loss</dt>
            <dd className="tabular-nums">
              {rupees(t.avg_win_rs)} / {rupees(t.avg_loss_rs)}
            </dd>
            <dt>Best trade</dt>
            <dd className="tabular-nums">
              {rupees(t.rs.best)}{" "}
              <a className="text-indigo-700 underline" href={href({ page: "trade", runId, tradeId: t.rs.best_trade })}>
                {t.rs.best_trade}
              </a>
            </dd>
            <dt>Worst trade</dt>
            <dd className="tabular-nums">
              {rupees(t.rs.worst)}{" "}
              <a className="text-indigo-700 underline" href={href({ page: "trade", runId, tradeId: t.rs.worst_trade })}>
                {t.rs.worst_trade}
              </a>
            </dd>
          </dl>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <h3 className="mb-2 font-semibold">Costs (all trades)</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
            <dt>Gross P&amp;L</dt>
            <dd className="tabular-nums">{rupees(t.gross_rs)}</dd>
            <dt>Slippage</dt>
            <dd className="tabular-nums">{rupees(t.slippage_rs)}</dd>
            <dt>Charges</dt>
            <dd className="tabular-nums">{rupees(t.charges_rs)}</dd>
            <dt>Net P&amp;L</dt>
            <dd className="tabular-nums">{rupees(t.net_rs)}</dd>
            {Object.entries(t.charges_by_line_rs).map(([line, value]) => (
              <div key={line} className="contents text-slate-500">
                <dt className="pl-3">{line}</dt>
                <dd className="tabular-nums">{rupees(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
