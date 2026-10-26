// The baseline's own edge and the pre-registered primary variants with their verdicts. Every
// number, interval, p-value and verdict comes from study.json (computed in Python); this file
// only lays them out.
import type { ComparisonRow, StudyFile } from "../api/types";
import { decimal, fraction, interval, pValue, signedPercent } from "../lib/format";
import { IntervalBar, sharedDomain } from "./IntervalBar";

const th = "px-3 py-2 font-medium";
const td = "px-3 py-2";

export function rowsByVariant(study: StudyFile): Map<string, ComparisonRow> {
  return new Map(study.comparison.map((r) => [`${r.variant}|${r.period}`, r]));
}

export function EdgeTable({ study }: { study: StudyFile }) {
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <caption className="sr-only">The baseline's mean net result per trade, in % of premium</caption>
          <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className={th}>Period</th>
              <th className={`${th} text-right`}>Trades</th>
              <th className={`${th} text-right`}>Mean net % of premium</th>
              <th className={`${th} text-right`}>t</th>
              <th className={`${th} text-right`}>p</th>
              <th className={th}>95% CI, i.i.d.</th>
              <th className={th}>95% CI, blocks</th>
              <th className={th}>Conservative envelope</th>
              <th className={`${th} text-right`}>Lag-1 autocorr.</th>
            </tr>
          </thead>
          <tbody>
            {study.edge.periods.map((p) => (
              <tr key={p.period} className="border-t border-slate-100">
                <td className={td}>{p.period}</td>
                <td className={`${td} text-right`}>{p.n}</td>
                <td className={`${td} text-right`}>{signedPercent(p.mean)}</td>
                <td className={`${td} text-right`}>{decimal(p.t)}</td>
                <td className={`${td} text-right`}>{pValue(p.p)}</td>
                <td className={td}>{interval(p.ci_iid)}</td>
                <td className={td}>{interval(p.ci_block)}</td>
                <td className={`${td} font-medium`}>{interval(p.ci_conservative)}</td>
                <td className={`${td} text-right`}>{decimal(p.lag1_autocorrelation, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm">
        <span className="text-slate-500">Verdict:</span>{" "}
        <strong data-testid="edge-verdict">{study.edge.verdict}</strong>
      </p>
    </div>
  );
}

export function VerdictTable({ study }: { study: StudyFile }) {
  const rows = rowsByVariant(study);
  const [dev, val] = study.plan.periods;
  if (!dev || !val) return null;
  const pick = (variant: string, period: string) => rows.get(`${variant}|${period}`);
  const base = pick("B0", dev.name);
  const domain = sharedDomain(
    study.plan.holm_family.flatMap((v) => [
      pick(v, dev.name)?.paired_ci_conservative,
      pick(v, val.name)?.paired_ci_conservative,
    ]),
  );
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Pre-registered primary variants against the baseline</caption>
        <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className={th} rowSpan={2}>
              Variant
            </th>
            <th className={`${th} border-l border-slate-200`} colSpan={6}>
              Development
            </th>
            <th className={`${th} border-l border-slate-200`} colSpan={2}>
              Historical validation (previously observed)
            </th>
            <th className={`${th} border-l border-slate-200`} rowSpan={2}>
              Pre-registered verdict
            </th>
          </tr>
          <tr>
            <th className={`${th} border-l border-slate-200 text-right`}>Mean diff</th>
            <th className={`${th} text-right`}>p</th>
            <th className={`${th} text-right`}>Holm p</th>
            <th className={th}>Envelope (95%)</th>
            <th className={`${th} text-right`}>Max DD vs B0</th>
            <th className={`${th} text-right`}>Worst 5% vs B0</th>
            <th className={`${th} border-l border-slate-200 text-right`}>Mean diff</th>
            <th className={th}>Envelope (95%)</th>
          </tr>
        </thead>
        <tbody>
          {study.plan.holm_family.map((variant) => {
            const d = pick(variant, dev.name);
            const w = pick(variant, val.name);
            const verdict = study.verdicts[variant];
            return (
              <tr key={variant} className="border-t border-slate-100 align-top">
                <td className={td}>
                  <div className="font-semibold">{variant}</div>
                  <div className="font-mono text-xs text-slate-500">{d?.change}</div>
                </td>
                <td className={`${td} border-l border-slate-100 text-right`}>
                  {signedPercent(d?.paired_mean)}
                </td>
                <td className={`${td} text-right`}>{pValue(d?.paired_p)}</td>
                <td className={`${td} text-right font-medium`}>{pValue(d?.paired_p_holm)}</td>
                <td className={td}>
                  <IntervalBar ci={d?.paired_ci_conservative} mean={d?.paired_mean} domain={domain} />
                  <div className="text-xs text-slate-600">{interval(d?.paired_ci_conservative)}</div>
                </td>
                <td className={`${td} text-right`}>
                  {fraction(d?.max_drawdown_pct)}
                  <div className="text-xs text-slate-500">vs {fraction(base?.max_drawdown_pct)}</div>
                </td>
                <td className={`${td} text-right`}>
                  {signedPercent(d?.paired_tail5_variant)}
                  <div className="text-xs text-slate-500">vs {signedPercent(d?.paired_tail5_baseline)}</div>
                </td>
                <td className={`${td} border-l border-slate-100 text-right`}>
                  {signedPercent(w?.paired_mean)}
                </td>
                <td className={td}>
                  <IntervalBar ci={w?.paired_ci_conservative} mean={w?.paired_mean} domain={domain} />
                  <div className="text-xs text-slate-600">{interval(w?.paired_ci_conservative)}</div>
                </td>
                <td className={`${td} border-l border-slate-100`}>
                  <div className="font-semibold">{verdict?.status}</div>
                  <div className="text-xs text-slate-600">{verdict?.development}</div>
                  {verdict?.validation ? (
                    <div className="text-xs text-slate-600">{verdict.validation}</div>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
