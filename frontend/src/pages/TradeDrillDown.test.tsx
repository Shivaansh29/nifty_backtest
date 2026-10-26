import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  errorRunNotFound,
  RUN_ID,
  STUDY_ID,
  stopTradeDetail,
  TRADE_ID,
  tradeDetail,
  V3_RUN_ID,
} from "../test/fixtures";
import { fail, mockApi, ok } from "../test/mockApi";
import { TradeDrillDown } from "./TradeDrillDown";

describe("trade drill-down", () => {
  it("shows the trade's facts, costs and every daily mark", async () => {
    mockApi({ [`/api/runs/${RUN_ID}/trades/${TRADE_ID}`]: ok(tradeDetail) });
    render(<TradeDrillDown runId={RUN_ID} tradeId={TRADE_ID} />);
    expect(await screen.findByRole("heading", { name: TRADE_ID })).toBeInTheDocument();
    expect(screen.getByText(/75 × 1 lot = 75 units/)).toBeInTheDocument();
    expect(screen.getByText(/₹8,852.28 \(118.03 pts/)).toBeInTheDocument();
    const marks = screen.getByRole("table", { name: "Daily marks" });
    const rows = within(marks).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    // Net MTM per day, as saved: -1.94021128, 18.06, 28.06, 118.03 points x 75 units.
    expect(rows.map((r) => r.lastElementChild?.previousElementSibling?.textContent)).toEqual([
      "-₹145.52",
      "₹1,354.48",
      "₹2,104.48",
      "₹8,852.28",
    ]);
    expect(screen.getByRole("figure", { name: "Mark-to-market" })).toBeInTheDocument();
    // A trade without an exit rule settles at expiry, and says so.
    expect(screen.getByText("Value at expiry")).toBeInTheDocument();
    expect(screen.queryByText("Exits")).not.toBeInTheDocument();
  });

  it("shows a stopped leg's buy-back as an exit, not as a value at expiry", async () => {
    // The hand-computed stop of test_engine_conditions, served from the study's V3 run.
    mockApi({
      [`/api/studies/${STUDY_ID}/runs/${V3_RUN_ID}/trades/${TRADE_ID}`]: ok(stopTradeDetail),
    });
    render(<TradeDrillDown runId={V3_RUN_ID} tradeId={TRADE_ID} studyId={STUDY_ID} />);
    expect(await screen.findByText("Exits")).toBeInTheDocument();
    expect(
      screen.getByText("CE held to expiry, 7 Aug 2025 at 0.00; PE stopped, 5 Aug 2025 at 124.38"),
    ).toBeInTheDocument();
    expect(screen.getByText("Value at exit")).toBeInTheDocument();
    expect(screen.queryByText("Value at expiry")).not.toBeInTheDocument();
    expect(screen.getByText("₹98.33 (of which buy-back ₹27.81)")).toBeInTheDocument();
    expect(screen.getByText(/^₹6,961.05 \(/)).toBeInTheDocument(); // net P&L line
    expect(screen.getByRole("link", { name: `← back to run ${V3_RUN_ID}` })).toHaveAttribute(
      "href",
      `#/studies/${STUDY_ID}/runs/${V3_RUN_ID}`,
    );
  });

  it("reports a trade the run does not have", async () => {
    mockApi({ [`/api/runs/${RUN_ID}/trades/NIFTY-1999-01-07`]: fail(errorRunNotFound) });
    render(<TradeDrillDown runId={RUN_ID} tradeId="NIFTY-1999-01-07" />);
    expect(await screen.findByText(/Not found: NIFTY-1999-01-07/)).toBeInTheDocument();
  });
});
