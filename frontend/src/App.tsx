import { LaunchForm } from "./pages/LaunchForm";
import { RunList } from "./pages/RunList";
import { RunOverview } from "./pages/RunOverview";
import { TradeDrillDown } from "./pages/TradeDrillDown";
import { Notice } from "./components/States";
import { href, useRoute } from "./lib/route";

export function App() {
  const route = useRoute();
  return (
    <div className="min-h-screen">
      <nav className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <a href={href({ page: "runs" })} className="font-semibold">
            NIFTY Options Backtester
          </a>
          <a href={href({ page: "runs" })} className="text-sm text-slate-600 hover:text-slate-900">
            Runs
          </a>
          <a href={href({ page: "launch" })} className="text-sm text-slate-600 hover:text-slate-900">
            New run
          </a>
        </div>
      </nav>
      <main className="mx-auto max-w-7xl px-4 py-6">
        {route.page === "runs" ? <RunList /> : null}
        {route.page === "launch" ? <LaunchForm /> : null}
        {route.page === "run" ? <RunOverview key={route.runId} runId={route.runId} /> : null}
        {route.page === "trade" ? (
          <TradeDrillDown key={`${route.runId}/${route.tradeId}`} runId={route.runId} tradeId={route.tradeId} />
        ) : null}
        {route.page === "not-found" ? (
          <Notice tone="warning" title="Page not found">
            <p>
              Nothing at <code className="font-mono">{route.hash}</code>.{" "}
              <a className="underline" href={href({ page: "runs" })}>
                Back to runs
              </a>
            </p>
          </Notice>
        ) : null}
      </main>
    </div>
  );
}
