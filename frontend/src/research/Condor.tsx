// The M9 iron condor study (plan §7): verdicts (Q2's pre-registered rule, Q1's edge rule) are
// laid out apart from everything descriptive (Q3, C1-R, cost grid, cost-assumption
// sensitivities), and every unverified cost assumption is stated. All numbers, intervals and
// verdicts come from study.json, computed in Python; this file only lays them out.
import type { ReactNode } from "react";
import type { Q1Row, Q3Row, SensitivityRow, StudyFile } from "../api/types";
import { Section } from "../components/MetricCard";
import { Notice } from "../components/States";
import { decimal, fraction, interval, percentValue, pValue, rupees, signedPercent } from "../lib/format";
import { AllVariantsTable } from "./Comparisons";
import { CostGrid } from "./CostAndRegimes";
import { rowsByVariant, VerdictTable } from "./Verdicts";

const th = "px-3 py-2 font-medium";
const td = "px-3 py-2";

function Sub({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="font-semibold">{title}</h3>
      {children}
    </div>
  );
}

function Table({ label, head, children }: { label: string; head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <caption className="sr-only">{label}</caption>
        <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            {head.map((h) => (
              <th key={h} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function CondorAssumptions({ study }: { study: StudyFile }) {
  const statuses = study.plan.assumptions ?? {};
  return (
    <Notice tone="warning" title="Stated cost assumptions (unverified)">
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Stamp duty on cash exercise is taken as ₹0: a modelling assumption from statutory
          interpretation, not a verified legal fact. Hypothetical cases are below.
        </li>
        <li>
          IPFT {study.plan.gst_on_ipft ? "included" : "excluded"} in GST's base for every run: an
          unverified modelling assumption, not a confirmed statutory requirement. The other base
          is a sensitivity below.
        </li>
        <li>
          SEBI's fee on exercised and assigned options uses settlement level × quantity as notional
          value: an unverified modelling assumption; two alternatives are below.
        </li>
        <li>Brokerage on exercise is ₹0 (no order is placed): an assumption.</li>
      </ul>
      <p className="mt-2 text-xs text-slate-600">
        Status in the frozen plan:{" "}
        {Object.entries(statuses)
          .map(([name, a]) => `${name.replaceAll("_", " ")}: ${String(a.status ?? "").replaceAll("_", " ")}`)
          .join("; ")}
      </p>
    </Notice>
  );
}

export function Q1Table({ rows }: { rows: Q1Row[] }) {
  return (
    <Table
      label="Each variant's own edge, in R_P (% of the ATM reference premium P)"
      head={["Variant", "Period", "Trades", "Mean R_P", "Envelope", "Mean R_ML (descr.)", "% of net credit (descr.)", "Verdict"]}
    >
      {rows.map((r) => (
        <tr key={`${r.variant}|${r.period}`} className="border-t border-slate-100">
          <td className={`${td} font-medium`}>{r.variant}</td>
          <td className={td}>{r.period}</td>
          <td className={td}>{r.n}</td>
          <td className={td}>{signedPercent(r.mean)}</td>
          <td className={td}>{interval(r.ci_conservative)}</td>
          <td className={td}>{percentValue(r.mean_r_ml)}</td>
          <td className={td}>{percentValue(r.mean_pct_net_credit)}</td>
          <td className={td}>{r.verdict}</td>
        </tr>
      ))}
    </Table>
  );
}

export function Q3Table({ rows }: { rows: Q3Row[] }) {
  return (
    <Table
      label="Q3 risk trade-off (descriptive)"
      head={["Variant", "Period", "Trades", "Net ₹", "Max DD %", "Lot-free DD", "Net / max DD", "Worst ₹", "Worst 5% (B0 premium)", "Win rate", "Max-loss hits"]}
    >
      {rows.map((r) => (
        <tr key={`${r.variant}|${r.period}`} className="border-t border-slate-100">
          <td className={`${td} font-medium`}>{r.variant}</td>
          <td className={td}>{r.period}</td>
          <td className={td}>{r.trades}</td>
          <td className={td}>{rupees(r.net_pnl_rs)}</td>
          <td className={td}>{fraction(r.max_drawdown_pct)}</td>
          <td className={td}>
            {decimal(r.lot_free_max_drawdown, 4)}
            {r.lot_free_drawdown_lower_bound ? " (lower bound)" : ""}
          </td>
          <td className={td}>{decimal(r.net_over_max_drawdown)}</td>
          <td className={td}>{rupees(r.worst_trade_rs)}</td>
          <td className={td}>{percentValue(r.tail5_common)}</td>
          <td className={td}>{fraction(r.win_rate)}</td>
          <td className={td}>{r.max_loss_hits ?? "n/a"}</td>
        </tr>
      ))}
    </Table>
  );
}

export function SensitivityTable({ rows }: { rows: SensitivityRow[] }) {
  return (
    <Table
      label="Cost-assumption sensitivities (descriptive)"
      head={["Sensitivity", "Case", "Variant", "Period", "Extra cost ₹", "Mean R_P", "Mean d_pct", "Holm p", "Status would be", "Changes?"]}
    >
      {rows.map((r) => (
        <tr key={`${r.sensitivity}|${r.case}|${r.variant}|${r.period}`} className="border-t border-slate-100">
          <td className={td}>{r.sensitivity}</td>
          <td className={`${td} font-mono text-xs`}>{r.case}</td>
          <td className={td}>{r.variant}</td>
          <td className={td}>{r.period}</td>
          <td className={td}>{decimal(r.extra_cost_rs, 4)}</td>
          <td className={td}>{signedPercent(r.mean_r_p)}</td>
          <td className={td}>{signedPercent(r.paired_mean)}</td>
          <td className={td}>{pValue(r.p_holm)}</td>
          <td className={td}>{r.status_would_be ?? ""}</td>
          <td className={td}>{r.verdict_changes == null ? "" : r.verdict_changes ? "yes" : "no"}</td>
        </tr>
      ))}
    </Table>
  );
}

export function CondorStudyBody({ study }: { study: StudyFile }) {
  const rows = rowsByVariant(study);
  const realism = study.plan.periods
    .map((p) => rows.get(`C1-R|${p.name}`))
    .filter((r) => r != null);
  const trace = study.trace;
  return (
    <>
      <CondorAssumptions study={study} />
      <Section title="Verdicts (pre-registered rule)">
        <Sub title="Q2. Does a condor improve on B0? (M7's rule, unchanged; d_pct in % of B0's premium)">
          <VerdictTable study={study} />
          <p className="text-sm text-slate-600">
            A condor gives up premium, so "worse than baseline" may only mean "collected less":
            read this beside Q3. Inconclusive means the data cannot tell, not that there is no effect.
          </p>
        </Sub>
        <Sub title="Q1. Does it have an edge on its own? (R_P)">
          <Q1Table rows={study.q1 ?? []} />
        </Sub>
      </Section>
      <Section title="Descriptive only (no verdict, never used to choose a setting)">
        <Sub title="Q3. Risk trade-off">
          <Q3Table rows={study.q3 ?? []} />
          <p className="text-sm text-slate-600">
            Rupee totals use each trade's own lot size (25 to 75), so they weigh years unequally;
            the lot-free drawdown (cumulative return on notional) does not.
          </p>
        </Sub>
        <Sub title="C1-R realism check (strikes from the previous session, paired with C1 in B0's premium)">
          <ul className="list-disc pl-5 text-sm">
            {realism.map((r) => (
              <li key={r.period}>
                {r.period}: mean {signedPercent(r.paired_mean)}, envelope {interval(r.paired_ci_conservative)},{" "}
                {r.trades} trades
              </li>
            ))}
          </ul>
        </Sub>
        <Sub title="Every run">
          <AllVariantsTable study={study} />
        </Sub>
        <Sub title="Cost grid (mean R_P, net ₹, t)">
          <CostGrid study={study} metric="mean_r_p" />
        </Sub>
        <Sub title="Cost-assumption sensitivities">
          <p className="text-sm text-slate-600">
            Hypothetical cases, not estimates and not legal limits. Verdicts above are computed on
            the stated assumptions; "status would be" only says what the rule would give.
          </p>
          <SensitivityTable rows={study.sensitivities ?? []} />
        </Sub>
        {trace ? (
          <Sub title="Trades traced by hand (picked by code)">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 text-sm">
              <dt className="text-slate-500">
                {trace.variant}, {trace.period}: first with a bought leg in the money
              </dt>
              <dd className="font-mono">{trace.bought_leg_in_the_money ?? "none"}</dd>
              <dt className="text-slate-500">first with none</dt>
              <dd className="font-mono">{trace.no_bought_leg_in_the_money ?? "none"}</dd>
            </dl>
          </Sub>
        ) : null}
      </Section>
    </>
  );
}
