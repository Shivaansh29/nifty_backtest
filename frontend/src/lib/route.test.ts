import { describe, expect, it } from "vitest";
import { href, parseRoute, runPath } from "./route";

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

describe("study routes", () => {
  it("parses study pages and runs inside a study", () => {
    expect(parseRoute("#/studies")).toEqual({ page: "studies" });
    expect(parseRoute("#/studies/s1")).toEqual({ page: "study", studyId: "s1" });
    expect(parseRoute("#/studies/s1/runs/r1")).toEqual({ page: "run", runId: "r1", studyId: "s1" });
    expect(parseRoute("#/studies/s1/runs/r1/trades/T")).toEqual({
      page: "trade",
      runId: "r1",
      tradeId: "T",
      studyId: "s1",
    });
  });

  it("round-trips study links and builds study API paths", () => {
    for (const route of [
      { page: "study", studyId: "s1" },
      { page: "run", runId: "r1", studyId: "s1" },
      { page: "trade", runId: "r1", tradeId: "T", studyId: "s1" },
    ] as const) {
      expect(parseRoute(href(route))).toEqual(route);
    }
    expect(runPath("r1", "/trades", "s1")).toBe("/api/studies/s1/runs/r1/trades");
    expect(runPath("r1", "/trades")).toBe("/api/runs/r1/trades");
  });
});
