// POST /api/runs: launch a backtest. Defaults are read from the API's own schema, and only
// the fields the user fills in are sent, so the API applies its defaults and its validation;
// its error messages are shown as they come back.
import { useState, type FormEvent } from "react";
import { ApiFailure, apiPost } from "../api/client";
import openapi from "../api/openapi.json";
import type { RunRequest, RunSummary } from "../api/types";
import { ApiErrorNotice, Notice } from "../components/States";
import { navigate } from "../lib/route";

type Field = keyof RunRequest;
const schema = openapi.components.schemas.RunRequest.properties;

const FIELDS: { name: Field; label: string; type: "date" | "number"; step?: string; help: string }[] = [
  { name: "start", label: "Start date", type: "date", help: "first day; empty = the data's start" },
  { name: "end", label: "End date", type: "date", help: "last day; empty = today" },
  { name: "entry_days_before_expiry", label: "Entry (sessions before expiry)", type: "number", step: "1", help: "full trading sessions" },
  { name: "lots", label: "Lots per leg", type: "number", step: "1", help: "lot size comes from the data" },
  { name: "brokerage_per_order_rs", label: "Brokerage (₹ per order)", type: "number", step: "any", help: "an assumption" },
  { name: "slippage_points_per_leg", label: "Slippage (points per leg)", type: "number", step: "any", help: "an assumption" },
  { name: "capital_rs", label: "Starting capital (₹)", type: "number", step: "any", help: "for ROI and the equity curve" },
];

function defaultOf(name: Field): string {
  const value = (schema[name] as { default?: unknown }).default;
  return value === undefined || value === null ? "" : String(value);
}

/** Only the filled-in fields; numbers are sent as numbers, anything else as typed (the API
 *  then explains what is wrong with it). */
export function requestBody(values: Partial<Record<Field, string>>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const field of FIELDS) {
    const raw = values[field.name]?.trim();
    if (!raw) continue;
    body[field.name] = field.type === "number" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
  }
  return body;
}

export function LaunchForm() {
  const [values, setValues] = useState<Partial<Record<Field, string>>>({});
  const [status, setStatus] = useState<{ state: "idle" | "running" } | { state: "error"; error: ApiFailure }>({
    state: "idle",
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setStatus({ state: "running" });
    try {
      const run = await apiPost<RunSummary>("/api/runs", requestBody(values));
      navigate({ page: "run", runId: run.run_id });
    } catch (error) {
      setStatus({
        state: "error",
        error: error instanceof ApiFailure ? error : new ApiFailure(0, String(error)),
      });
    }
  }

  const running = status.state === "running";
  return (
    <form onSubmit={submit} className="max-w-2xl space-y-4" aria-label="Launch a backtest">
      <h1 className="text-xl font-semibold">New short-straddle run</h1>
      <p className="text-sm text-slate-600">
        Leave a field empty to use the default shown. The run is saved like{" "}
        <code className="font-mono">nifty-backtest backtest</code> would save it.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <label key={field.name} className="text-sm">
            <span className="font-medium">{field.label}</span>
            <input
              name={field.name}
              type={field.type}
              step={field.step}
              placeholder={defaultOf(field.name)}
              value={values[field.name] ?? ""}
              disabled={running}
              onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
              className="mt-1 block w-full rounded border border-slate-300 px-2 py-1"
            />
            <span className="text-xs text-slate-500">{field.help}</span>
          </label>
        ))}
      </div>
      <button
        type="submit"
        disabled={running}
        className="rounded bg-indigo-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {running ? "Running…" : "Run backtest"}
      </button>
      {running ? (
        <Notice tone="info" title="Backtest running">
          <p>This takes about 80 seconds for the full five years. The run opens when it is saved.</p>
        </Notice>
      ) : null}
      {status.state === "error" ? <ApiErrorNotice error={status.error} what="launch" /> : null}
    </form>
  );
}
