import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TradeRecord } from "../api/types";
import { RUN_ID, trades } from "../test/fixtures";
import { TradeTable } from "./TradeTable";

// The fixture run has one trade; two more (copies with different ids, P&L and events) show
// sorting and searching. Values are only displayed, so their exact size does not matter.
const base = trades[0]!;
const three: TradeRecord[] = [
  base,
  { ...base, trade_id: "NIFTY-2025-08-14", expiry: "2025-08-14", pnl_rs_net: -5000, event_in_window: false, events: null },
  { ...base, trade_id: "NIFTY-2025-08-21", expiry: "2025-08-21", pnl_rs_net: 100, event_in_window: false, events: null },
];

function ids(): string[] {
  const table = screen.getByRole("table", { name: "Trades" });
  return within(table)
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");
}

describe("trade table", () => {
  it("sorts by a column when its header is clicked", async () => {
    render(<TradeTable trades={three} runId={RUN_ID} />);
    expect(ids()).toEqual(["NIFTY-2025-08-07", "NIFTY-2025-08-14", "NIFTY-2025-08-21"]);
    const header = screen.getByRole("button", { name: /Net ₹/ });
    await userEvent.click(header);
    const first = ids();
    await userEvent.click(header);
    const second = ids();
    expect(new Set([first.join(), second.join()])).toEqual(
      new Set([
        "NIFTY-2025-08-14,NIFTY-2025-08-21,NIFTY-2025-08-07",
        "NIFTY-2025-08-07,NIFTY-2025-08-21,NIFTY-2025-08-14",
      ]),
    );
  });

  it("searches trade ids and event tags", async () => {
    render(<TradeTable trades={three} runId={RUN_ID} />);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search trades" }), "rbi_policy");
    expect(ids()).toEqual(["NIFTY-2025-08-07"]);
    expect(screen.getByText("1 of 3 trades")).toBeInTheDocument();
  });

  it("links each trade to its drill-down", () => {
    render(<TradeTable trades={three} runId={RUN_ID} />);
    expect(screen.getByRole("link", { name: "NIFTY-2025-08-14" })).toHaveAttribute(
      "href",
      `#/runs/${RUN_ID}/trades/NIFTY-2025-08-14`,
    );
  });
});
