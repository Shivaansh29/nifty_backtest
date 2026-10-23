import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { errorRunNotFound, RUN_ID, TRADE_ID, tradeDetail } from "../test/fixtures";
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
  });

  it("reports a trade the run does not have", async () => {
    mockApi({ [`/api/runs/${RUN_ID}/trades/NIFTY-1999-01-07`]: fail(errorRunNotFound) });
    render(<TradeDrillDown runId={RUN_ID} tradeId="NIFTY-1999-01-07" />);
    expect(await screen.findByText(/Not found: NIFTY-1999-01-07/)).toBeInTheDocument();
  });
});
