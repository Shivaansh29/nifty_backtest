// The cost grid as heatmaps (slippage x brokerage) and the baseline's regime breakdowns.
// Values come from study.json; the colours are presentation only.
import type { CostGridRow, RegimeRow, StudyFile } from "../api/types";
import { decimal, fraction, percentValue, rupeesWhole } from "../lib/format";

const th = "px-3 py-2 font-medium";
const td = "px-3 py-2";

/** Shade a cell by its mean net % of premium: green above zero, red below, darker further. */
function shade(value: number | null | undefined): string {
  if (value == null) return "bg-slate-100 text-slate-500";
  const size = Math.abs(value);
  const strength = size >= 5 ? 2 : size >= 2 ? 1 : 0;
  const greens = ["bg-emerald-50", "bg-emerald-100", "bg-emerald-300"];
  const reds = ["bg-red-50", "bg-red-100", "bg-red-300"];
  return (value >= 0 ? greens : reds)[strength] ?? "";
}

const unique = (values: number[]) => [...new Set(values)].sort((a, b) => a - b);

export function CostGrid({ study }: { study: StudyFile }) {
  const groups = new Map<string, CostGridRow[]>();
  for (const c of study.cost_grid) {
    const key = `${c.base}|${c.period}`;
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {[...groups.entries()].map(([key, cells]) => {
        const [base, period] = key.split("|");
        const slippages = unique(cells.map((c) => c.slippage_points_per_leg));
        const brokerages = unique(cells.map((c) => c.brokerage_per_order_rs));
        const at = (s: number, b: number) =>
          cells.find((c) => c.slippage_points_per_leg === s && c.brokerage_per_order_rs === b);
        return (
          <div key={key} className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
            <table className="min-w-full text-xs" aria-label={`Cost grid for ${base}, ${period}`}>
              <caption className="pb-2 text-left text-sm font-semibold">
                {base}, {period === "validation" ? "validation (previously observed)" : period}
              </caption>
              <thead>
                <tr>
                  <th className="px-2 py-1 text-left">Slippage ↓ / brokerage →</th>
                  {brokerages.map((b) => (
                    <th key={b} className="px-2 py-1">
                      ₹{b} per order
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {slippages.map((s) => (
                  <tr key={s}>
                    <th className="px-2 py-1 text-left">{s} pt per leg</th>
                    {brokerages.map((b) => {
                      const c = at(s, b);
                      return (
                        <td key={b} className={`px-2 py-1 text-center ${shade(c?.mean_pct_premium_net)}`}>
                          {c ? (
                            <>
                              <div className="font-semibold">{percentValue(c.mean_pct_premium_net)}</div>
                              <div>{rupeesWhole(c.net_pnl_rs)}</div>
                              <div className="text-slate-600">t {decimal(c.t_pct_premium)}</div>
                            </>
                          ) : (
                            "n/a"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

export function RegimeTables({ study }: { study: StudyFile }) {
  const periods = study.plan.periods.map((p) => p.name);
  const groupings = [...new Set(study.regimes.map((r) => r.grouping))];
  const find = (grouping: string, group: string, period: string): RegimeRow | undefined =>
    study.regimes.find((r) => r.grouping === grouping && r.group === group && r.period === period);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {groupings.map((grouping) => {
        const groups = [...new Set(study.regimes.filter((r) => r.grouping === grouping).map((r) => r.group))];
        return (
          <div key={grouping} className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full text-sm">
              <caption className="px-3 pt-2 text-left text-sm font-semibold">
                <span className="font-mono">{grouping}</span>
              </caption>
              <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className={th}>Group</th>
                  {periods.map((p) => (
                    <th key={p} className={`${th} text-right`}>
                      {p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr key={group} className="border-t border-slate-100 align-top">
                    <td className={td}>{group}</td>
                    {periods.map((p) => {
                      const r = find(grouping, group, p);
                      return (
                        <td key={p} className={`${td} text-right`}>
                          {r ? (
                            <>
                              <div>{percentValue(r.mean_pct_premium_net)}</div>
                              <div className="text-xs text-slate-500">
                                {r.trades} trades · {rupeesWhole(r.total_net_rs)} · win {fraction(r.win_rate)}
                              </div>
                            </>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
