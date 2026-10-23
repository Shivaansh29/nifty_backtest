import { describe, expect, it } from "vitest";
import { errorRunNotFound } from "../test/fixtures";
import { fail, mockApi } from "../test/mockApi";
import { ApiFailure, apiGet, UNREACHABLE } from "./client";

describe("API client", () => {
  it("turns the API's error body into an ApiFailure that keeps it", async () => {
    mockApi({ "/api/runs/x": fail(errorRunNotFound) });
    const error = await apiGet("/api/runs/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiFailure);
    expect((error as ApiFailure).status).toBe(404);
    expect((error as ApiFailure).body?.error).toBe("run_not_found");
    expect((error as ApiFailure).message).toBe(errorRunNotFound.body.detail);
  });

  it("explains how to start the API when it cannot be reached", async () => {
    mockApi({ "/api/runs": "unreachable" });
    const error = (await apiGet("/api/runs").catch((e: unknown) => e)) as ApiFailure;
    expect(error.status).toBe(0);
    expect(error.message).toBe(UNREACHABLE);
  });

  it("treats a non-JSON error (the dev proxy with no server behind it) as unreachable", async () => {
    mockApi({ "/api/runs": { status: 502, body: undefined } });
    const error = (await apiGet("/api/runs").catch((e: unknown) => e)) as ApiFailure;
    expect(error.status).toBe(502);
    expect(error.message).toContain("nifty-backtest serve");
  });
});
