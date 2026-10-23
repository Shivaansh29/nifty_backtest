// One run: its settings and status, then each part of its results. Every section fetches
// its own endpoint and shows its own loading / incomplete / error state, so a run with
// missing metrics still shows its trades, and a run with a broken trade log still shows
// what can be read.
import type {
  DailyPoint,
  EquityPoint,
  Metrics,
  MonthRow,
  RunDetail,
  SkippedWeek,
  TradeRecord,
  YearRow,
} from "../api/types";
import { useApi } from "../api/useApi";
import { DrawdownChart } from "../charts/DrawdownChart";
import { EquityChart, NetEquityChart } from "../charts/EquityChart";
import { Section } from "../components/MetricCard";
import { ApiErrorNotice, Loading, Notice, WithCode } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { day, rupees } from "../lib/format";
import { runPath } from "../lib/route";
import { MonthlyHeatmap } from "../tables/MonthlyHeatmap";
import { TradeTable } from "../tables/TradeTable";
import { YearlyTable } from "../tables/YearlyTable";
import { HeadlineMetrics } from "./HeadlineMetrics";

export function RunOverview({ runId }: { runId: string }) {
  const detail = useApi<RunDetail>(runPath(runId));
  if (detail.state === "loading") return <Loading what="run" />;
  if (detail.state === "error") return <ApiErrorNotice error={detail.error} what={runId} />;
  const run = detail.data;
  return (
    <div className="space-y-8">
      <RunHeader run={run} />
      <Section title="Headline results">
        <MetricsSection runId={runId} />
      </Section>
      <Section title="Equity and drawdown">
        <ChartsSection runId={runId} />
      </Section>
      <Section title="Calendar years">
        <YearlySection runId={runId} />
      </Section>
      <Section title="Monthly returns">
        <MonthlySection runId={runId} />
      </Section>
      <Section title="Trades">
        <TradesSection runId={runId} />
      </Section>
      <Section title="Skipped weeks">
        <SkippedSection runId={runId} />
      </Section>
    </div>
  );
}

function RunHeader({ run }: { run: RunDetail }) {
  const settings = run.config.run;
  const strategy = run.config.strategy;
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-xl font-semibold">{run.run_id}</h1>
        <StatusBadge status={run.status} />
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-4">
        <dt className="text-slate-500">Period</dt>
        <dd>
          {day(run.first_trading_day)} – {day(run.last_trading_day)}
          {run.manifest.data.trading_day_count ? ` (${run.manifest.data.trading_day_count} trading days)` : ""}
        </dd>
        <dt className="text-slate-500">Strategy</dt>
        <dd>
          {strategy.name}, {strategy.lots} lot, entry {strategy.entry_days_before_expiry} sessions before expiry
        </dd>
        <dt className="text-slate-500">Capital</dt>
        <dd>{rupees(settings.capital_rs)}</dd>
        <dt className="text-slate-500">Cost assumptions</dt>
        <dd>
          {rupees(settings.costs.brokerage_per_order_rs)} per order, {settings.costs.slippage_points_per_leg} pt slippage per leg
        </dd>
        <dt className="text-slate-500">Code</dt>
        <dd className="font-mono text-xs">
          {run.git_commit?.slice(0, 7) ?? "unknown"}
          {run.uncommitted_changes ? <span className="ml-1 text-amber-700">+ uncommitted changes</span> : null}
        </dd>
        <dt className="text-slate-500">Trades / skipped</dt>
        <dd>
          {run.trade_count ?? "n/a"} / {run.skipped_count ?? "n/a"}
        </dd>
      </dl>
      {run.status !== "complete" ? (
        <Notice
          tone={run.status === "invalid" ? "error" : "warning"}
          title={run.status === "invalid" ? "Some saved files are unreadable" : "This run is incomplete"}
        >
          <ul className="list-disc pl-5">
            {run.problems.map((p) => (
              <li key={p}>
                <WithCode text={p} />
              </li>
            ))}
          </ul>
        </Notice>
      ) : null}
    </header>
  );
}

function MetricsSection({ runId }: { runId: string }) {
  const metrics = useApi<Metrics>(runPath(runId, "/metrics"));
  if (metrics.state === "loading") return <Loading what="metrics" />;
  if (metrics.state === "error") return <ApiErrorNotice error={metrics.error} what="metrics" />;
  return <HeadlineMetrics metrics={metrics.data} runId={runId} />;
}

function ChartsSection({ runId }: { runId: string }) {
  const daily = useApi<DailyPoint[]>(runPath(runId, "/daily"));
  if (daily.state === "loading") return <Loading what="daily series" />;
  if (daily.state === "ok") {
    return (
      <div className="grid gap-4">
        <EquityChart daily={daily.data} />
        <DrawdownChart daily={daily.data} />
      </div>
    );
  }
  // No daily series: say why (and how to add it), then show what the run does have.
  return (
    <div className="space-y-3">
      <ApiErrorNotice error={daily.error} what="drawdown and NIFTY 50 TRI series" />
      {daily.error.status === 409 ? <EquityFallback runId={runId} /> : null}
    </div>
  );
}

function EquityFallback({ runId }: { runId: string }) {
  const equity = useApi<EquityPoint[]>(runPath(runId, "/equity"));
  if (equity.state === "loading") return <Loading what="equity curve" />;
  if (equity.state === "error") return <ApiErrorNotice error={equity.error} what="equity curve" />;
  return <NetEquityChart equity={equity.data} />;
}

function YearlySection({ runId }: { runId: string }) {
  const yearly = useApi<YearRow[]>(runPath(runId, "/yearly"));
  if (yearly.state === "loading") return <Loading what="yearly table" />;
  if (yearly.state === "error") return <ApiErrorNotice error={yearly.error} what="yearly table" />;
  return <YearlyTable rows={yearly.data} />;
}

function MonthlySection({ runId }: { runId: string }) {
  const monthly = useApi<MonthRow[]>(runPath(runId, "/monthly"));
  if (monthly.state === "loading") return <Loading what="monthly returns" />;
  if (monthly.state === "error") return <ApiErrorNotice error={monthly.error} what="monthly returns" />;
  return <MonthlyHeatmap rows={monthly.data} />;
}

function TradesSection({ runId }: { runId: string }) {
  const trades = useApi<TradeRecord[]>(runPath(runId, "/trades"));
  if (trades.state === "loading") return <Loading what="trades" />;
  if (trades.state === "error") return <ApiErrorNotice error={trades.error} what="trades" />;
  if (trades.data.length === 0) return <Notice tone="info" title="No trades in this run" />;
  return <TradeTable trades={trades.data} runId={runId} />;
}

function SkippedSection({ runId }: { runId: string }) {
  const skipped = useApi<SkippedWeek[]>(runPath(runId, "/skipped"));
  if (skipped.state === "loading") return <Loading what="skipped weeks" />;
  if (skipped.state === "error") return <ApiErrorNotice error={skipped.error} what="skipped weeks" />;
  if (skipped.data.length === 0) return <p className="text-sm text-slate-600">No weeks were skipped.</p>;
  return (
    <ul className="list-disc pl-5 text-sm">
      {skipped.data.map((w) => (
        <li key={w.expiry}>
          Expiry {day(w.expiry)} (entry {day(w.entry_date)}): {w.reason}
        </li>
      ))}
    </ul>
  );
}

