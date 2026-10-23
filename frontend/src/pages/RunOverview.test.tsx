import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  daily,
  detail,
  detailMetricsMissing,
  detailOld,
  equity,
  errorDailyMissing,
  errorInvalidTrades,
  errorMetricsMissing,
  INVALID_ID,
  metrics,
  metricsOld,
  MISSING_ID,
  monthly,
  OLD_ID,
  RUN_ID,
  runs,
  skipped,
  trades,
  yearly,
  yearlyOld,
} from "../test/fixtures";
import { fail, mockApi, ok, type Routes } from "../test/mockApi";
import { RunOverview } from "./RunOverview";

function completeRun(id: string = RUN_ID): Routes {
  const base = `/api/runs/${id}`;
  return {
    [base]: ok(detail),
    [`${base}/metrics`]: ok(metrics),
    [`${base}/daily`]: ok(daily),
    [`${base}/yearly`]: ok(yearly),
    [`${base}/monthly`]: ok(monthly),
    [`${base}/trades`]: ok(trades),
    [`${base}/skipped`]: ok(skipped),
    [`${base}/equity`]: ok(equity),
  };
}

describe("run overview", () => {
  it("shows the headline metrics exactly as the API computed them", async () => {
    mockApi(completeRun());
    render(<RunOverview runId={RUN_ID} />);
    expect(await screen.findByTestId("metric-Net P&L")).toHaveTextContent("₹8,852.28");
    expect(screen.getByTestId("metric-ROI")).toHaveTextContent("1.77%");
    expect(screen.getByTestId("metric-Max drawdown")).toHaveTextContent("0.03%");
    expect(screen.getByTestId("metric-Sharpe")).toHaveTextContent("11.34");
    expect(screen.getByTestId("metric-Win rate")).toHaveTextContent("100.00%");
    // One trade, so the t-statistic is not computable: shown as n/a, never as 0.
    expect(screen.getByTestId("metric-Mean trade").parentElement).toHaveTextContent("t = n/a");
    const comparison = screen.getByRole("table", { name: "Net, gross and benchmark metrics" });
    const roi = within(comparison).getByText("ROI (on starting capital)").closest("tr")!;
    expect(roi).toHaveTextContent("1.77%");
    expect(roi).toHaveTextContent("-0.48%"); // NIFTY 50 TRI: 25,020 -> 24,900
    // The target rates in the labels come from the run's metrics config.
    expect(within(comparison).getByText("Sharpe, rupee, 6.50%")).toBeInTheDocument();
  });

  it("draws the equity and drawdown charts from the daily series", async () => {
    mockApi(completeRun());
    render(<RunOverview runId={RUN_ID} />);
    expect(await screen.findByRole("figure", { name: "Equity" })).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Drawdown" })).toBeInTheDocument();
  });

  it("shows the yearly table, monthly heatmap, trades and skipped weeks", async () => {
    mockApi(completeRun());
    render(<RunOverview runId={RUN_ID} />);
    const years = await screen.findByRole("table", { name: "Calendar years" });
    expect(within(years).getByText("2025")).toBeInTheDocument();
    expect(await screen.findByTestId("month-2025-08")).toHaveTextContent("1.77%");
    expect(screen.getByTestId("month-2025-08")).toHaveAttribute(
      "title",
      expect.stringContaining("NIFTY 50 TRI -0.48%"),
    );
    const tradeTable = await screen.findByRole("table", { name: "Trades" });
    expect(within(tradeTable).getByRole("link", { name: "NIFTY-2025-08-07" })).toHaveAttribute(
      "href",
      `#/runs/${RUN_ID}/trades/NIFTY-2025-08-07`,
    );
    expect(await screen.findByText("No weeks were skipped.")).toBeInTheDocument();
  });

  it("serves older runs: no optional fields, and no daily series but a clear fallback", async () => {
    const base = `/api/runs/${OLD_ID}`;
    mockApi({
      ...completeRun(OLD_ID),
      [base]: ok(detailOld),
      [`${base}/metrics`]: ok(metricsOld),
      [`${base}/yearly`]: ok(yearlyOld),
      [`${base}/daily`]: fail(errorDailyMissing),
    });
    render(<RunOverview runId={OLD_ID} />);
    expect(await screen.findByTestId("metric-Net P&L")).toHaveTextContent("₹8,852.28");
    const notice = await screen.findByText(/computed before daily series were saved/);
    expect(notice.closest("[role=note]")).toHaveTextContent("Not computed yet");
    expect(screen.getByText(`nifty-backtest metrics runs/${OLD_ID}`).tagName).toBe("CODE");
    // What the run does have is still shown: the net equity curve from equity.csv.
    expect(await screen.findByRole("figure", { name: "Equity (net)" })).toBeInTheDocument();
    expect(screen.queryByRole("figure", { name: "Drawdown" })).not.toBeInTheDocument();
  });

  it("shows a run without metrics as incomplete, with the command, and still lists its trades", async () => {
    const base = `/api/runs/${MISSING_ID}`;
    mockApi({
      ...completeRun(MISSING_ID),
      [base]: ok(detailMetricsMissing),
      [`${base}/metrics`]: fail(errorMetricsMissing),
      [`${base}/daily`]: fail(errorMetricsMissing),
      [`${base}/yearly`]: fail(errorMetricsMissing),
      [`${base}/monthly`]: fail(errorMetricsMissing),
    });
    render(<RunOverview runId={MISSING_ID} />);
    expect(await screen.findByText("This run is incomplete")).toBeInTheDocument();
    // Metrics, daily series, yearly and monthly each say they are not computed yet.
    await waitFor(() => expect(screen.getAllByText(/Not computed yet/)).toHaveLength(4));
    expect(await screen.findByRole("table", { name: "Trades" })).toBeInTheDocument();
  });

  it("shows an invalid run's problems and the failing section's error", async () => {
    const base = `/api/runs/${INVALID_ID}`;
    const invalidDetail = { ...detail, run_id: INVALID_ID, status: "invalid" as const, problems: runs[3]!.problems };
    mockApi({
      ...completeRun(INVALID_ID),
      [base]: ok(invalidDetail),
      [`${base}/trades`]: fail(errorInvalidTrades),
    });
    render(<RunOverview runId={INVALID_ID} />);
    expect(await screen.findByText("Some saved files are unreadable")).toBeInTheDocument();
    const failure = (await screen.findByText("Saved results are unreadable: trades")).closest("[role=alert]");
    expect(failure).toHaveTextContent("trades.csv: 0.pnl_rs_net: Field required");
    expect(failure).toHaveTextContent("artifact_invalid · trades.csv");
  });

  it("shows the metrics' missing-data notes and a lower-bound drawdown", async () => {
    const gappy = {
      ...metrics,
      strategy_net: {
        ...metrics.strategy_net,
        max_drawdown_lower_bound: true,
        max_drawdown_note: "observed lower bound: 1 daily values missing",
        sharpe_notional: { value: null, note: "2 daily values missing: a multi-day return would be needed, so not computed" },
      },
    };
    mockApi({ ...completeRun(), [`/api/runs/${RUN_ID}/metrics`]: ok(gappy) });
    render(<RunOverview runId={RUN_ID} />);
    expect(await screen.findByTestId("metric-Sharpe")).toHaveTextContent("n/a");
    expect(screen.getByText("lower bound")).toBeInTheDocument();
    expect(screen.getByText("Net: observed lower bound: 1 daily values missing")).toBeInTheDocument();
    expect(screen.getByText(/Sharpe \(notional\): 2 daily values missing/)).toBeInTheDocument();
  });

  it("reports an unknown run", async () => {
    mockApi({});
    render(<RunOverview runId="20990101-000000-short_straddle" />);
    expect(await screen.findByText(/Not found/)).toBeInTheDocument();
  });
});
