// Every run of a study, development next to historical validation, and the sensitivity
// families. Values come from study.json; nothing is recomputed here.
import type { ComparisonRow, FamilyRow, StudyFile } from "../api/types";
import { fraction, interval, rupeesWhole, signedPercent } from "../lib/format";
import { href } from "../lib/route";
import { rowsByVariant } from "./Verdicts";

const th = "px-3 py-2 font-medium";
const td = "px-3 py-2";

export function AllVariantsTable({ study }: { study: StudyFile }) {
  const rows = rowsByVariant(study);
  const periods = study.plan.periods;
  // Plan order, each variant once.
  const variants = [...new Map(study.comparison.map((r) => [r.variant, r])).values()];
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Every variant in every period</caption>
        <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className={th} rowSpan={2}>
              Variant
            </th>
            {periods.map((p) => (
              <th key={p.name} className={`${th} border-l border-slate-200`} colSpan={5}>
                {p.name === "validation" ? "validation (previously observed)" : p.name}
              </th>
            ))}
          </tr>
          <tr>
            {periods.map((p) => (
              <PeriodHeads key={p.name} />
            ))}
          </tr>
        </thead>
        <tbody>
          {variants.map((v) => (
            <tr key={v.variant} className="border-t border-slate-100 align-top">
              <td className={td}>
                <div className="font-semibold">{v.variant}</div>
                <div className="text-xs text-slate-500">
                  {v.role} · <span className="font-mono">{v.change}</span>
                </div>
              </td>
              {periods.map((p) => (
                <PeriodCells
                  key={p.name}
                  studyId={study.study_id}
                  row={rows.get(`${v.variant}|${p.name}`)}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PeriodHeads() {
  return (
    <>
      <th className={`${th} border-l border-slate-200 text-right`}>Trades</th>
      <th className={`${th} text-right`}>Net ₹</th>
      <th className={`${th} text-right`}>Max DD</th>
      <th className={`${th} text-right`}>Mean diff vs B0</th>
      <th className={th}>Envelope</th>
    </>
  );
}

function PeriodCells({
  studyId,
  row,
}: {
  studyId: string;
  row: ComparisonRow | undefined;
}) {
  if (!row) {
    return (
      <td className={`${td} border-l border-slate-100 text-slate-400`} colSpan={5}>
        n/a
      </td>
    );
  }
  return (
    <>
      <td className={`${td} border-l border-slate-100 text-right`}>
        <a
          className="text-indigo-700 underline"
          href={href({ page: "run", runId: row.run_id, studyId })}
          title={`open run ${row.run_id}`}
        >
          {row.trades}
        </a>
      </td>
      <td className={`${td} text-right`}>{rupeesWhole(row.net_pnl_rs)}</td>
      <td className={`${td} text-right`}>{fraction(row.max_drawdown_pct)}</td>
      <td className={`${td} text-right`}>
        {row.variant === "B0" ? "—" : signedPercent(row.paired_mean)}
      </td>
      <td className={`${td} whitespace-nowrap text-xs`}>
        {row.variant === "B0" ? "" : interval(row.paired_ci_conservative)}
      </td>
    </>
  );
}

/** Families grouped by (root variant, varying setting), with both periods per value. */
export function FamilyTables({ study }: { study: StudyFile }) {
  const [dev, val] = study.plan.periods;
  if (!dev || !val) return null;
  const groups = new Map<string, FamilyRow[]>();
  for (const f of study.families) {
    const key = `${f.family}|${f.setting}`;
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {[...groups.entries()].map(([key, members]) => {
        const first = members[0];
        if (!first) return null;
        const byVariant = new Map<string, { dev?: FamilyRow; val?: FamilyRow }>();
        for (const m of members) {
          const entry = byVariant.get(m.variant) ?? {};
          if (m.period === dev.name) entry.dev = m;
          if (m.period === val.name) entry.val = m;
          byVariant.set(m.variant, entry);
        }
        const plateau = (row: FamilyRow | undefined) =>
          row?.plateau_same_sign == null ? "n/a" : row.plateau_same_sign ? "yes" : "no";
        const firstDev = [...byVariant.values()][0]?.dev;
        const firstVal = [...byVariant.values()][0]?.val;
        return (
          <div key={key} className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full text-sm">
              <caption className="px-3 pt-2 text-left text-sm font-semibold">
                {first.family}: varying <span className="font-mono">{first.setting}</span>
                <span className="ml-2 text-xs font-normal text-slate-500">
                  plateau (neighbours same sign): {dev.name} {plateau(firstDev)}, {val.name}{" "}
                  {plateau(firstVal)}
                </span>
              </caption>
              <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className={th}>Value</th>
                  <th className={th}>Variant</th>
                  <th className={`${th} text-right`}>{dev.name}</th>
                  <th className={`${th} text-right`}>validation</th>
                </tr>
              </thead>
              <tbody>
                {[...byVariant.entries()].map(([variant, pair]) => (
                  <tr key={variant} className="border-t border-slate-100">
                    <td className={`${td} font-mono`}>{String((pair.dev ?? pair.val)?.value)}</td>
                    <td className={td}>{variant}</td>
                    <FamilyCell row={pair.dev} />
                    <FamilyCell row={pair.val} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

function FamilyCell({ row }: { row: FamilyRow | undefined }) {
  if (!row) return <td className={`${td} text-right text-slate-400`}>n/a</td>;
  return (
    <td className={`${td} text-right`}>
      {row.variant === "B0" ? "baseline" : signedPercent(row.mean_d_pct)}
      <div className="text-xs text-slate-500">
        {row.variant === "B0" ? "" : interval(row.ci_conservative)}
      </div>
    </td>
  );
}
