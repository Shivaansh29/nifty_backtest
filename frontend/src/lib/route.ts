// A small hash router: the page lives in the URL after "#", so links can be shared and the
// browser's back button works, without a routing library.
import { useEffect, useState } from "react";

export type Route =
  | { page: "runs" }
  | { page: "launch" }
  | { page: "run"; runId: string }
  | { page: "trade"; runId: string; tradeId: string }
  | { page: "not-found"; hash: string };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  if (path === "/" || path === "/runs") return { page: "runs" };
  if (path === "/new") return { page: "launch" };
  const trade = path.match(/^\/runs\/([^/]+)\/trades\/([^/]+)$/);
  if (trade?.[1] && trade[2]) {
    return {
      page: "trade",
      runId: decodeURIComponent(trade[1]),
      tradeId: decodeURIComponent(trade[2]),
    };
  }
  const run = path.match(/^\/runs\/([^/]+)$/);
  if (run?.[1]) return { page: "run", runId: decodeURIComponent(run[1]) };
  return { page: "not-found", hash: path };
}

export function href(route: Exclude<Route, { page: "not-found" }>): string {
  switch (route.page) {
    case "runs":
      return "#/";
    case "launch":
      return "#/new";
    case "run":
      return `#/runs/${encodeURIComponent(route.runId)}`;
    case "trade":
      return `#/runs/${encodeURIComponent(route.runId)}/trades/${encodeURIComponent(route.tradeId)}`;
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

export function navigate(route: Exclude<Route, { page: "not-found" }>): void {
  window.location.hash = href(route);
}

/** API path for a run (ids are already safe, but encode anyway). */
export function runPath(runId: string, suffix = ""): string {
  return `/api/runs/${encodeURIComponent(runId)}${suffix}`;
}
