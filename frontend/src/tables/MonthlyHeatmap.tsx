import type { MonthRow } from "../api/types";
import { fraction, month } from "../lib/format";

const MONTHS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Colour for a monthly return: green for gains, red for losses, darker for larger moves.
 *  Presentation only; the value shown is the API's. */
function shade(value: number | null): string {
  if (value === null) return "bg-slate-200 text-slate-500";
  const size = Math.abs(value);
  const strength = size >= 0.05 ? 3 : size >= 0.02 ? 2 : size >= 0.005 ? 1 : 0;
  const greens = ["bg-emerald-50", "bg-emerald-100", "bg-emerald-300", "bg-emerald-500 text-white"];
  const reds = ["bg-red-50", "bg-red-100", "bg-red-300", "bg-red-500 text-white"];
  return (value >= 0 ? greens : reds)[strength] ?? "";
}

/** monthly.csv laid out as years x months. A month the run did not cover is blank; a month
 *  whose return is missing (a boundary day missing, rule R3) is grey with the reason. */
export function MonthlyHeatmap({ rows }: { rows: MonthRow[] }) {
  const byMonth = new Map(rows.map((r) => [r.month, r]));
  const years = [...new Set(rows.map((r) => r.month.slice(0, 4)))];
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
      <table className="min-w-full text-xs" aria-label="Monthly returns">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left">Year</th>
            {MONTH_NAMES.map((m) => (
              <th key={m} className="px-2 py-1">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year}>
              <th className="px-2 py-1 text-left">{year}</th>
              {MONTHS.map((mm) => {
                const row = byMonth.get(`${year}-${mm}`);
                if (!row) return <td key={mm} className="px-2 py-1" />;
                const title = [
                  `${month(row.month)}: ${fraction(row.return)}`,
                  row.benchmark_return !== undefined ? `NIFTY 50 TRI ${fraction(row.benchmark_return)}` : null,
                  `${row.trading_days} trading days`,
                  row.note || null,
                ]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <td
                    key={mm}
                    title={title}
                    data-testid={`month-${row.month}`}
                    className={`px-2 py-1 text-center tabular-nums ${shade(row.return)}`}
                  >
                    {row.return === null ? "–" : fraction(row.return)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
