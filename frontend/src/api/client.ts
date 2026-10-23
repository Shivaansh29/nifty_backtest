// The only place the dashboard talks to the API. URLs are relative (/api/...): in development
// Vite forwards them to `nifty-backtest serve` (see vite.config.ts), so no CORS is involved.
import type { ErrorBody } from "./types";

/** A failed request: the HTTP status (0 if the API could not be reached at all) and, when
 *  the API answered with its standard error shape, that body. */
export class ApiFailure extends Error {
  readonly status: number;
  readonly body: ErrorBody | null;

  constructor(status: number, message: string, body: ErrorBody | null = null) {
    super(message);
    this.name = "ApiFailure";
    this.status = status;
    this.body = body;
  }
}

export const UNREACHABLE =
  "Cannot reach the API. Start it with `uv run nifty-backtest serve` and reload.";

function isErrorBody(value: unknown): value is ErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).error === "string" &&
    typeof (value as Record<string, unknown>).detail === "string"
  );
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { Accept: "application/json", ...init.headers } });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiFailure(0, UNREACHABLE);
  }
  if (response.ok) return response;
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: the request never reached FastAPI (e.g. the dev proxy found no server).
  }
  if (isErrorBody(body)) throw new ApiFailure(response.status, body.detail, body);
  throw new ApiFailure(response.status, `${UNREACHABLE} (HTTP ${response.status})`);
}

// The response types are trusted, not re-validated: they are generated from the same schema
// the API validates its own responses against, and CI fails if the two drift apart.
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await send(path, signal ? { signal } : {});
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await response.json()) as T;
}
