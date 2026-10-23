import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  errorLaunchInProgress,
  errorLaunchInvalid,
  errorLaunchNoData,
  RUN_ID,
  runs,
} from "../test/fixtures";
import { fail, mockApi } from "../test/mockApi";
import { LaunchForm, requestBody } from "./LaunchForm";

describe("launch form", () => {
  it("shows the API's own defaults", () => {
    render(<LaunchForm />);
    expect(screen.getByLabelText(/Entry/)).toHaveAttribute("placeholder", "3");
    expect(screen.getByLabelText(/Lots per leg/)).toHaveAttribute("placeholder", "1");
    expect(screen.getByLabelText(/Brokerage/)).toHaveAttribute("placeholder", "20");
    expect(screen.getByLabelText(/Slippage/)).toHaveAttribute("placeholder", "0.5");
    expect(screen.getByLabelText(/Starting capital/)).toHaveAttribute("placeholder", "500000");
  });

  it("sends only the fields that were filled in", () => {
    expect(requestBody({ lots: "2", slippage_points_per_leg: " 1.5 ", start: "", end: "2025-03-31" })).toEqual({
      end: "2025-03-31",
      lots: 2,
      slippage_points_per_leg: 1.5,
    });
  });

  it("opens the new run when the API has saved it", async () => {
    const calls = mockApi({ "POST /api/runs": { status: 201, body: runs[0] } });
    render(<LaunchForm />);
    await userEvent.type(screen.getByLabelText(/Lots per leg/), "2");
    await userEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    await waitFor(() => expect(window.location.hash).toBe(`#/runs/${RUN_ID}`));
    expect(calls).toEqual([{ method: "POST", path: "/api/runs", body: { lots: 2 } }]);
  });

  it.each([
    ["invalid parameters", errorLaunchInvalid, "body.lots: Input should be greater than or equal to 1"],
    ["no market data", errorLaunchNoData, "nifty-backtest download"],
    ["a launch already running", errorLaunchInProgress, "another run is being launched"],
  ])("shows the API's explanation for %s", async (_, fixture, words) => {
    mockApi({ "POST /api/runs": fail(fixture) });
    render(<LaunchForm />);
    await userEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(await screen.findByText(new RegExp(words.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeEnabled();
  });

  it("disables the form while the run is in progress", async () => {
    mockApi({ "POST /api/runs": "pending" });
    render(<LaunchForm />);
    await userEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
    expect(screen.getByText(/about 80 seconds/)).toBeInTheDocument();
  });
});
