import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MISSING_ID, RUN_ID, runs } from "../test/fixtures";
import { mockApi, ok } from "../test/mockApi";
import { RunList } from "./RunList";

describe("run list", () => {
  it("shows loading while the API answers", () => {
    mockApi({ "/api/runs": "pending" });
    render(<RunList />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading saved runs");
  });

  it("lists every run with its status, headline numbers and problems", async () => {
    mockApi({ "/api/runs": ok(runs) });
    render(<RunList />);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(RUN_ID);
    expect(rows[1]).toHaveTextContent("complete");
    expect(rows[1]).toHaveTextContent("₹8,852.28");
    expect(rows[1]).toHaveTextContent("1.77%");
    expect(screen.getByText(/metrics missing/)).toBeInTheDocument();
    expect(screen.getByText("invalid")).toBeInTheDocument();
    // The API's explanation of an incomplete run, with its command shown as code.
    expect(screen.getByText(`nifty-backtest metrics runs/${MISSING_ID}`).tagName).toBe("CODE");
    expect(screen.getByText(/trades.csv: 0.pnl_rs_net: Field required/)).toBeInTheDocument();
  });

  it("says how to make a first run when there are none", async () => {
    mockApi({ "/api/runs": ok([]) });
    render(<RunList />);
    expect(await screen.findByText("No saved runs yet")).toBeInTheDocument();
  });

  it("says how to start the API when it is not running", async () => {
    mockApi({ "/api/runs": "unreachable" });
    render(<RunList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("API not reachable");
    expect(screen.getByText("uv run nifty-backtest serve")).toBeInTheDocument();
  });
});
