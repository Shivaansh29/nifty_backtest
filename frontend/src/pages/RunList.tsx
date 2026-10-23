import type { RunSummary } from "../api/types";
import { useApi } from "../api/useApi";
import { StatusBadge } from "../components/StatusBadge";
import { ApiErrorNotice, Loading, Notice, WithCode } from "../components/States";
import { day, decimal, fraction, rupees, savedAt } from "../lib/format";
import { href } from "../lib/route";

export function RunList() {
  const runs = useApi<RunSummary[]>("/api/runs");

  if (runs.state === "loading") return <Loading what="saved runs" />;
  if (runs.state === "error") return <ApiErrorNotice error={runs.error} what="saved runs" />;
  if (runs.data.length === 0) {
    return (
      <Notice tone="info" title="No saved runs yet">
        <p>
          Launch one from <a className="underline" href={href({ page: "launch" })}>New run</a>, or
          run <code className="font-mono">uv run nifty-backtest backtest</code>.
        </p>
      </Notice>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Saved backtest runs, newest first</caption>
        <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2">Run</th>
            <th className="px-3 py-2">Saved</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Period</th>
            <th className="px-3 py-2 text-right">Trades</th>
            <th className="px-3 py-2 text-right">Net P&amp;L</th>
            <th className="px-3 py-2 text-right">ROI</th>
            <th className="px-3 py-2 text-right">Sharpe (notional)</th>
          </tr>
        </thead>
        <tbody>
          {runs.data.map((run) => (
            <RunRow key={run.run_id} run={run} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunRow({ run }: { run: RunSummary }) {
  const h = run.headline;
  return (
    <>
      <tr className="border-t border-slate-100 hover:bg-slate-50">
        <td className="px-3 py-2 font-mono text-xs">
          <a className="text-indigo-700 underline" href={href({ page: "run", runId: run.run_id })}>
            {run.run_id}
          </a>
          {run.uncommitted_changes ? (
            <span className="ml-2 text-amber-700" title="saved from a working tree with uncommitted changes">
              (uncommitted code)
            </span>
          ) : null}
        </td>
        <td className="px-3 py-2">{savedAt(run.created_at)}</td>
        <td className="px-3 py-2">
          <StatusBadge status={run.status} />
        </td>
        <td className="px-3 py-2">
          {day(run.first_trading_day)} – {day(run.last_trading_day)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums">{h ? h.trades : "–"}</td>
        <td className="px-3 py-2 text-right tabular-nums">{h ? rupees(h.total_pnl_rs) : "–"}</td>
        <td className="px-3 py-2 text-right tabular-nums">{h ? fraction(h.roi) : "–"}</td>
        <td className="px-3 py-2 text-right tabular-nums">{h ? decimal(h.sharpe_notional) : "–"}</td>
      </tr>
      {run.problems.length > 0 ? (
        <tr>
          <td colSpan={8} className="px-3 pb-2 text-xs text-slate-600">
            <ul className="list-disc pl-5">
              {run.problems.map((problem) => (
                <li key={problem}>
                  <WithCode text={problem} />
                </li>
              ))}
            </ul>
          </td>
        </tr>
      ) : null}
    </>
  );
}
