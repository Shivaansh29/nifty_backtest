// M9 multi-leg drill-down: the hand-computed condor week of tests/test_engine_multileg.py
// (sell 24,750 CE and 24,250 PE, buy 25,000 CE and 24,000 PE; settlement 25,100; net
// Rs -14,668.1123456, R_P -78.23%, R_ML -100.81%).
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CONDOR_RUN_ID, CONDOR_TRADE_ID, condorTradeDetail, RUN_ID, TRADE_ID, tradeDetail } from "../test/fixtures";
import { mockApi, ok } from "../test/mockApi";
import { TradeDrillDown } from "./TradeDrillDown";

describe("multi-leg trade drill-down", () => {
  it("shows one row per leg with its own fill, value at expiry and costs", async () => {
    mockApi({ [`/api/runs/${CONDOR_RUN_ID}/trades/${CONDOR_TRADE_ID}`]: ok(condorTradeDetail) });
    render(<TradeDrillDown runId={CONDOR_RUN_ID} tradeId={CONDOR_TRADE_ID} />);
    const legs = await screen.findByRole("table", { name: "Legs" });
    const rows = within(legs).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    const firstCells = (i: number) => within(rows[i]!).getAllByRole("cell").slice(0, 4).map((c) => c.textContent);
    expect(firstCells(0)).toEqual(["sell", "CE", "24,750", "40.00"]);
    expect(firstCells(2)).toEqual(["buy", "CE", "25,000", "12.00"]);
    expect(rows[0]).toHaveTextContent("assigned");
    expect(rows[2]).toHaveTextContent("exercised");
    expect(rows[3]).toHaveTextContent("worthless");
    // The long call's STT on exercise is on its intrinsic value: 0.125% x 100 x 75.
    expect(rows[2]).toHaveTextContent("₹9.38");
  });

  it("shows the reference premium, wings, maximum loss and both returns", async () => {
    mockApi({ [`/api/runs/${CONDOR_RUN_ID}/trades/${CONDOR_TRADE_ID}`]: ok(condorTradeDetail) });
    render(<TradeDrillDown runId={CONDOR_RUN_ID} tradeId={CONDOR_TRADE_ID} />);
    expect(await screen.findByText(/ATM 24,500, P = 250.00 pts/)).toBeInTheDocument();
    expect(screen.getByText(/not traded/)).toBeInTheDocument();
    expect(screen.getByText("call 250 pts, put 250 pts; maximum loss 194.00 pts")).toBeInTheDocument();
    expect(screen.getByText(/-78.23% of P \(R_P\)/)).toBeInTheDocument();
    expect(screen.getByText(/-100.81% of maximum loss \(R_ML\)/)).toBeInTheDocument();
    expect(screen.getByText(/^-₹14,668.11 \(/)).toBeInTheDocument();
    const marks = screen.getByRole("table", { name: "Daily leg marks" });
    expect(within(marks).getAllByRole("row").slice(1)).toHaveLength(4);
  });

  it("keeps the straddle view for a trade without legs", async () => {
    mockApi({ [`/api/runs/${RUN_ID}/trades/${TRADE_ID}`]: ok(tradeDetail) });
    render(<TradeDrillDown runId={RUN_ID} tradeId={TRADE_ID} />);
    expect(await screen.findByText("Value at expiry")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Legs" })).not.toBeInTheDocument();
  });
});
