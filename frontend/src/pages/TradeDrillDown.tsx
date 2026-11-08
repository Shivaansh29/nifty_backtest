// One trade: its facts as logged, its costs line by line, and its daily marks. A multi-leg
// trade (M9) also shows every leg (legs.csv) and every leg's daily mark (leg_marks.csv); all
// numbers come from the API, nothing is computed here.
import type { LegMark, LegRecord, TradeDetail, TradeRecord } from "../api/types";
import { useApi } from "../api/useApi";
import { TradeMarksChart } from "../charts/TradeMarksChart";
import { Section } from "../components/MetricCard";
import { ApiErrorNotice, Loading } from "../components/States";
import { day, decimal, percentValue, rupees } from "../lib/format";
import { href, runPath } from "../lib/route";

export function TradeDrillDown({
  runId,
  tradeId,
  studyId,
}: {
  runId: string;
  tradeId: string;
  studyId?: string;
}) {
  const detail = useApi<TradeDetail>(
    runPath(runId, `/trades/${encodeURIComponent(tradeId)}`, studyId),
  );
  return (
    <div className="space-y-6">
      <a className="text-sm text-indigo-700 underline" href={href({ page: "run", runId, studyId })}>
        ← back to run {runId}
      </a>
      {detail.state === "loading" ? <Loading what="trade" /> : null}
      {detail.state === "error" ? <ApiErrorNotice error={detail.error} what={tradeId} /> : null}
      {detail.state === "ok" ? (
        detail.data.legs ? (
          <MultiLegView detail={detail.data} legs={detail.data.legs} />
        ) : (
          <TradeView detail={detail.data} />
        )
      ) : null}
    </div>
  );
}

const REASONS: Record<string, string> = { stop: "stopped", take_profit: "took profit", expiry: "held to expiry" };

function legExit(reason: string | null | undefined, date: string | null | undefined, price: number | null | undefined): string {
  if (!reason) return "n/a";
  return `${REASONS[reason] ?? reason}, ${day(date)} at ${decimal(price)}`;
}

function TradeView({ detail }: { detail: TradeDetail }) {
  const t = detail.trade;
  const exited = t.ce_exit_reason != null || t.pe_exit_reason != null;
  const facts: [string, string][] = [
    ["Entry", `${day(t.entry_date)} at NIFTY ${t.nifty_close_at_entry.toLocaleString("en-IN")}`],
    ["Expiry", `${day(t.expiry)} (${t.expiry_weekday})${t.relabelled ? `, re-dated from ${day(t.stated_expiry_on_entry)}` : ""}`],
    ["Strike", t.strike != null ? t.strike.toLocaleString("en-IN") : "—"],
    ["Lot size", `${t.lot_size} × ${t.lots} lot = ${t.quantity} units (${t.lot_size_source})`],
    ["India VIX at entry", decimal(t.vix_at_entry)],
    ["Premium", `CE ${decimal(t.ce_entry_close)} + PE ${decimal(t.pe_entry_close)} = ${decimal(t.premium_close_points)} pts at the close; ${decimal(t.premium_fill_points)} pts filled`],
    ["Settlement", `${t.settlement_level.toLocaleString("en-IN")} (NIFTY move ${percentValue(t.nifty_move_pct)})`],
    // With an M7 exit rule, a leg may be bought back before expiry; its "value at expiry"
    // column then holds its buy-back price, so the row says "at exit" and the exits are listed.
    ...(exited
      ? ([
          ["Exits", `CE ${legExit(t.ce_exit_reason, t.ce_exit_date, t.ce_exit_price)}; PE ${legExit(t.pe_exit_reason, t.pe_exit_date, t.pe_exit_price)}`],
          ["Value at exit", `CE ${decimal(t.ce_value_at_expiry)} + PE ${decimal(t.pe_value_at_expiry)} = ${decimal(t.value_at_expiry_points)} pts`],
        ] as [string, string][])
      : ([
          ["Value at expiry", `CE ${decimal(t.ce_value_at_expiry)} + PE ${decimal(t.pe_value_at_expiry)} = ${decimal(t.value_at_expiry_points)} pts`],
        ] as [string, string][])),
    ["Events in window", t.event_in_window ? (t.events ?? "") : "none"],
  ];
  const pnl: [string, string][] = [
    ["Gross P&L", `${rupees(t.pnl_rs_gross)} (${decimal(t.pnl_points_gross)} pts, ${percentValue(t.pnl_pct_premium_gross)} of premium)`],
    ["Slippage", rupees(t.slippage_rs)],
    [
      "Charges",
      `${rupees(t.charges_rs)}${t.exit_charges_rs ? ` (of which buy-back ${rupees(t.exit_charges_rs)})` : ""}`,
    ],
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

const STATUS: Record<string, string> = {
  worthless: "worthless",
  assigned: "assigned",
  exercised: "exercised",
};

function chargeLines(t: TradeRecord): [string, number][] {
  return [
    ["Brokerage", t.brokerage_rs],
    ["STT", t.stt_rs],
    ["NSE transaction", t.exchange_rs],
    ["IPFT", t.ipft_rs],
    ["SEBI fee", t.sebi_rs],
    ["Stamp duty", t.stamp_rs],
    ["GST", t.gst_rs],
  ];
}

function FactList({ items, numeric = false }: { items: [string, string][]; numeric?: boolean }) {
  return (
    <>
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className={numeric ? "tabular-nums" : undefined}>{v}</dd>
        </div>
      ))}
    </>
  );
}

function MultiLegView({ detail, legs }: { detail: TradeDetail; legs: LegRecord[] }) {
  const t = detail.trade;
  const facts: [string, string][] = [
    ["Entry", `${day(t.entry_date)} at NIFTY ${t.nifty_close_at_entry.toLocaleString("en-IN")}`],
    ["Expiry", `${day(t.expiry)} (${t.expiry_weekday})${t.relabelled ? `, re-dated from ${day(t.stated_expiry_on_entry)}` : ""}`],
    [
      "Reference",
      `ATM ${t.reference_atm?.toLocaleString("en-IN") ?? "n/a"}, P = ${decimal(t.reference_premium_points)} pts on ${day(t.reference_date)} (ATM call + put close; not traded)`,
    ],
    [
      "Wings",
      `call ${t.wing_call_points?.toLocaleString("en-IN") ?? "n/a"} pts, put ${t.wing_put_points?.toLocaleString("en-IN") ?? "n/a"} pts; maximum loss ${decimal(t.max_loss_points)} pts`,
    ],
    ["Lot size", `${t.lot_size} × ${t.lots} lot = ${t.quantity} units per leg (${t.lot_size_source})`],
    ["India VIX at entry", decimal(t.vix_at_entry)],
    ["Net credit", `${decimal(t.premium_close_points)} pts at the close; ${decimal(t.premium_fill_points)} pts filled`],
    ["Settlement", `${t.settlement_level.toLocaleString("en-IN")} (NIFTY move ${percentValue(t.nifty_move_pct)})`],
    ["Value at expiry", `${decimal(t.value_at_expiry_points)} pts (sold legs +, bought legs −)`],
    ["Events in window", t.event_in_window ? (t.events ?? "") : "none"],
  ];
  const pnl: [string, string][] = [
    ["Gross P&L", `${rupees(t.pnl_rs_gross)} (${decimal(t.pnl_points_gross)} pts)`],
    ["Slippage", rupees(t.slippage_rs)],
    ["Charges", rupees(t.charges_rs)],
    [
      "Net P&L",
      `${rupees(t.pnl_rs_net)} (${decimal(t.pnl_points_net)} pts; ${percentValue(t.pnl_pct_reference_premium_net)} of P (R_P); ${percentValue(t.pnl_pct_max_loss_net)} of maximum loss (R_ML))`,
    ],
    ["% of net credit", percentValue(t.pnl_pct_premium_net)],
  ];
  return (
    <>
      <h1 className="font-mono text-xl font-semibold">{t.trade_id}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <FactList items={facts} />
        </dl>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <FactList items={pnl} numeric />
          {chargeLines(t).map(([k, v]) => (
            <div key={k} className="contents text-slate-500">
              <dt className="pl-3">{k}</dt>
              <dd className="tabular-nums">{rupees(v)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <Section title="Legs">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full text-sm" aria-label="Legs">
            <thead className="bg-slate-100 text-right text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left">Side</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2">Strike</th>
                <th className="px-3 py-2">Close</th>
                <th className="px-3 py-2">Fill</th>
                <th className="px-3 py-2">Value at expiry</th>
                <th className="px-3 py-2 text-left">At expiry</th>
                <th className="px-3 py-2">Gross ₹</th>
                <th className="px-3 py-2">STT ₹</th>
                <th className="px-3 py-2">Charges ₹</th>
                <th className="px-3 py-2">Net ₹</th>
              </tr>
            </thead>
            <tbody className="text-right tabular-nums">
              {legs.map((l) => (
                <tr key={l.leg_id} className="border-t border-slate-100">
                  <td className="px-3 py-1.5 text-left">{l.side}</td>
                  <td className="px-3 py-1.5 text-left">{l.option_type}</td>
                  <td className="px-3 py-1.5">{l.strike.toLocaleString("en-IN")}</td>
                  <td className="px-3 py-1.5">{decimal(l.entry_close)}</td>
                  <td className="px-3 py-1.5">{decimal(l.entry_fill)}</td>
                  <td className="px-3 py-1.5">{decimal(l.intrinsic_at_expiry)}</td>
                  <td className="px-3 py-1.5 text-left">{STATUS[l.expiry_status] ?? l.expiry_status}</td>
                  <td className="px-3 py-1.5">{rupees(l.pnl_rs_gross)}</td>
                  <td className="px-3 py-1.5">{rupees(l.stt_rs)}</td>
                  <td className="px-3 py-1.5">{rupees(l.charges_rs)}</td>
                  <td className="px-3 py-1.5">{rupees(l.pnl_rs_net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Daily marks">
        <TradeMarksChart marks={detail.marks} />
        <LegMarksTable legs={legs} marks={detail.leg_marks ?? []} positions={detail.marks} />
      </Section>
    </>
  );
}

function LegMarksTable({
  legs,
  marks,
  positions,
}: {
  legs: LegRecord[];
  marks: LegMark[];
  positions: TradeDetail["marks"];
}) {
  const at = new Map(marks.map((m) => [`${m.leg_id}|${m.date}`, m]));
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm" aria-label="Daily leg marks">
        <thead className="bg-slate-100 text-right text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2 text-left">Date</th>
            {legs.map((l) => (
              <th key={l.leg_id} className="px-3 py-2">
                {l.side} {l.option_type} {l.strike.toLocaleString("en-IN")}
              </th>
            ))}
            <th className="px-3 py-2">Position (pts)</th>
            <th className="px-3 py-2">MTM net (₹)</th>
            <th className="px-3 py-2 text-left">Flags</th>
          </tr>
        </thead>
        <tbody className="text-right tabular-nums">
          {positions.map((p) => (
            <tr key={p.date} className="border-t border-slate-100">
              <td className="px-3 py-1.5 text-left">{day(p.date)}</td>
              {legs.map((l) => {
                const m = at.get(`${l.leg_id}|${p.date}`);
                return (
                  <td key={l.leg_id} className={`px-3 py-1.5 ${m?.stale ? "text-amber-700" : ""}`}>
                    {m?.missing ? "missing" : decimal(m?.close)}
                  </td>
                );
              })}
              <td className="px-3 py-1.5">{decimal(p.position_value_points)}</td>
              <td className="px-3 py-1.5">{rupees(p.mtm_rs_net)}</td>
              <td className="px-3 py-1.5 text-left text-xs text-amber-700">
                {[p.stale_mark ? "stale price" : "", p.missing_mark ? "missing mark" : ""].filter(Boolean).join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
