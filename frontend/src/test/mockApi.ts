// A fake `fetch` that answers from the recorded API fixtures (fixtures.ts), so components are
// tested against exactly what the real API sends. Unknown paths get the API's 404 shape.
import { vi } from "vitest";
import type { ErrorFixture } from "./fixtures";

export type Reply = { status: number; body: unknown } | "unreachable" | "pending";
export type Routes = Record<string, Reply>;

export const ok = (body: unknown): Reply => ({ status: 200, body });
export const fail = (fixture: ErrorFixture): Reply => ({ status: fixture.status, body: fixture.body });

export function mockApi(routes: Routes) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const reply = routes[`${method} ${path}`] ?? routes[path];
    if (reply === "unreachable") throw new TypeError("Failed to fetch");
    if (reply === "pending") return new Promise<Response>(() => {});
    const { status, body } = reply ?? {
      status: 404,
      body: { error: "not_found", detail: "Not Found", run_id: null, artifact: null },
    };
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
