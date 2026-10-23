import { describe, expect, it } from "vitest";
import { href, parseRoute } from "./route";

describe("routes", () => {
  it("parses every page", () => {
    expect(parseRoute("")).toEqual({ page: "runs" });
    expect(parseRoute("#/")).toEqual({ page: "runs" });
    expect(parseRoute("#/new")).toEqual({ page: "launch" });
    expect(parseRoute("#/runs/20250807-160000-short_straddle")).toEqual({
      page: "run",
      runId: "20250807-160000-short_straddle",
    });
    expect(parseRoute("#/runs/r1/trades/NIFTY-2025-08-07")).toEqual({
      page: "trade",
      runId: "r1",
      tradeId: "NIFTY-2025-08-07",
    });
    expect(parseRoute("#/elsewhere")).toEqual({ page: "not-found", hash: "/elsewhere" });
  });

  it("round-trips links", () => {
    const route = { page: "trade", runId: "r1", tradeId: "NIFTY-2025-08-07" } as const;
    expect(parseRoute(href(route))).toEqual(route);
  });
});
