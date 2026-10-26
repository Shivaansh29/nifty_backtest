// A small hash router: the page lives in the URL after "#", so links can be shared and the
// browser's back button works, without a routing library.
import { useEffect, useState } from "react";

// A run is either a top-level run (runs/) or one of a study's runs (studies/<id>/runs/):
// `studyId` says which. The same run pages show both.
export type Route =
  | { page: "runs" }
  | { page: "launch" }
  | { page: "run"; runId: string; studyId?: string }
  | { page: "trade"; runId: string; tradeId: string; studyId?: string }
  | { page: "studies" }
  | { page: "study"; studyId: string }
  | { page: "not-found"; hash: string };

const part = (text: string) => decodeURIComponent(text);
const scope = (studyId: string | undefined) => (studyId ? { studyId } : {});

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  if (path === "/" || path === "/runs") return { page: "runs" };
  if (path === "/new") return { page: "launch" };
  if (path === "/studies") return { page: "studies" };
  // Optional "/studies/<id>" prefix, then the run (and trade) path.
  const trade = path.match(/^(?:\/studies\/([^/]+))?\/runs\/([^/]+)\/trades\/([^/]+)$/);
  if (trade?.[2] && trade[3]) {
    return {
      page: "trade",
      runId: part(trade[2]),
      tradeId: part(trade[3]),
      ...scope(trade[1] && part(trade[1])),
    };
  }
  const run = path.match(/^(?:\/studies\/([^/]+))?\/runs\/([^/]+)$/);
  if (run?.[2]) return { page: "run", runId: part(run[2]), ...scope(run[1] && part(run[1])) };
  const study = path.match(/^\/studies\/([^/]+)$/);
  if (study?.[1]) return { page: "study", studyId: part(study[1]) };
  return { page: "not-found", hash: path };
}

export function href(route: Exclude<Route, { page: "not-found" }>): string {
  switch (route.page) {
    case "runs":
      return "#/";
    case "launch":
      return "#/new";
    case "run":
      return `#${studyPrefix(route.studyId)}/runs/${encodeURIComponent(route.runId)}`;
    case "trade":
      return `#${studyPrefix(route.studyId)}/runs/${encodeURIComponent(route.runId)}/trades/${encodeURIComponent(route.tradeId)}`;
    case "studies":
      return "#/studies";
    case "study":
      return `#/studies/${encodeURIComponent(route.studyId)}`;
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

function studyPrefix(studyId: string | undefined): string {
  return studyId ? `/studies/${encodeURIComponent(studyId)}` : "";
}

/** API path for a run, top-level or within a study (ids are already safe, but encode
 *  anyway). */
export function runPath(runId: string, suffix = "", studyId?: string): string {
  return `/api${studyPrefix(studyId)}/runs/${encodeURIComponent(runId)}${suffix}`;
}

/** API path for a study. */
export function studyPath(studyId: string): string {
  return `/api/studies/${encodeURIComponent(studyId)}`;
}
