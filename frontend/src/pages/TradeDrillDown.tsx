// One trade: its facts as logged, its costs line by line, and its daily marks.
import type { TradeDetail } from "../api/types";
import { useApi } from "../api/useApi";
import { TradeMarksChart } from "../charts/TradeMarksChart";
import { Section } from "../components/MetricCard";
import { ApiErrorNotice, Loading } from "../components/States";
import { day, decimal, percentValue, rupees } from "../lib/format";
import { href, runPath } from "../lib/route";

export function TradeDrillDown({ runId, tradeId }: { runId: string; tradeId: string }) {
  const detail = useApi<TradeDetail>(runPath(runId, `/trades/${encodeURIComponent(tradeId)}`));
  return (
    <div className="space-y-6">
      <a className="text-sm text-indigo-700 underline" href={href({ page: "run", runId })}>
        ← back to run {runId}
      </a>
      {detail.state === "loading" ? <Loading what="trade" /> : null}
      {detail.state === "error" ? <ApiErrorNotice error={detail.error} what={tradeId} /> : null}
      {detail.state === "ok" ? <TradeView detail={detail.data} /> : null}
    </div>
  );
}

function TradeView({ detail }: { detail: TradeDetail }) {
  const t = detail.trade;
  const facts: [string, string][] = [
    ["Entry", `${day(t.entry_date)} at NIFTY ${t.nifty_close_at_entry.toLocaleString("en-IN")}`],
    ["Expiry", `${day(t.expiry)} (${t.expiry_weekday})${t.relabelled ? `, re-dated from ${day(t.stated_expiry_on_entry)}` : ""}`],
    ["Strike", t.strike.toLocaleString("en-IN")],
    ["Lot size", `${t.lot_size} × ${t.lots} lot = ${t.quantity} units (${t.lot_size_source})`],
    ["India VIX at entry", decimal(t.vix_at_entry)],
    ["Premium", `CE ${decimal(t.ce_entry_close)} + PE ${decimal(t.pe_entry_close)} = ${decimal(t.premium_close_points)} pts at the close; ${decimal(t.premium_fill_points)} pts filled`],
    ["Settlement", `${t.settlement_level.toLocaleString("en-IN")} (NIFTY move ${percentValue(t.nifty_move_pct)})`],
    ["Value at expiry", `CE ${decimal(t.ce_value_at_expiry)} + PE ${decimal(t.pe_value_at_expiry)} = ${decimal(t.value_at_expiry_points)} pts`],
    ["Events in window", t.event_in_window ? (t.events ?? "") : "none"],
  ];
  const pnl: [string, string][] = [
    ["Gross P&L", `${rupees(t.pnl_rs_gross)} (${decimal(t.pnl_points_gross)} pts, ${percentValue(t.pnl_pct_premium_gross)} of premium)`],
    ["Slippage", rupees(t.slippage_rs)],
    ["Charges", rupees(t.charges_rs)],
    ["Net P&L", `${rupees(t.pnl_rs_net)} (${decimal(t.pnl_points_net)} pts, ${percentValue(t.pnl_pct_premium_net)} of premium)`],
  ];
  const charges: [string, number][] = [
    ["Brokerage", t.brokerage_rs],
    ["STT", t.stt_rs],
    ["NSE transaction", t.exchange_rs],
    ["IPFT", t.ipft_rs],
    ["SEBI fee", t.sebi_rs],
    ["Stamp duty", t.stamp_rs],
    ["GST", t.gst_rs],
  ];
  return (
    <>
      <h1 className="font-mono text-xl font-semibold">{t.trade_id}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          {pnl.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd className="tabular-nums">{v}</dd>
            </div>
          ))}
          {charges.map(([k, v]) => (
            <div key={k} className="contents text-slate-500">
              <dt className="pl-3">{k}</dt>
              <dd className="tabular-nums">{rupees(v)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <Section title="Daily marks">
        <TradeMarksChart marks={detail.marks} />
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full text-sm" aria-label="Daily marks">
            <thead className="bg-slate-100 text-right text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2">CE</th>
                <th className="px-3 py-2">PE</th>
                <th className="px-3 py-2">Position (pts)</th>
                <th className="px-3 py-2">MTM gross (pts)</th>
                <th className="px-3 py-2">MTM net (₹)</th>
                <th className="px-3 py-2 text-left">Flags</th>
              </tr>
            </thead>
            <tbody className="text-right tabular-nums">
              {detail.marks.map((m) => (
                <tr key={m.date} className="border-t border-slate-100">
                  <td className="px-3 py-1.5 text-left">{day(m.date)}</td>
                  <td className="px-3 py-1.5">{decimal(m.ce_mark)}</td>
                  <td className="px-3 py-1.5">{decimal(m.pe_mark)}</td>
                  <td className="px-3 py-1.5">{decimal(m.position_value_points)}</td>
                  <td className="px-3 py-1.5">{decimal(m.mtm_points_gross)}</td>
                  <td className="px-3 py-1.5">{rupees(m.mtm_rs_net)}</td>
                  <td className="px-3 py-1.5 text-left text-xs text-amber-700">
                    {[m.stale_mark ? "stale price" : "", m.missing_mark ? "missing mark" : ""].filter(Boolean).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
