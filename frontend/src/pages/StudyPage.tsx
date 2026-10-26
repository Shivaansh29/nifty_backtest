// One research study (M7): the pre-registered plan, the baseline's edge, the primary
// variants with their verdicts, every run side by side, sensitivity families, the cost grid
// and the regime breakdowns. All statistics and verdicts are computed in Python and served
// from study.json; this page only lays them out.
import type { StudyFile } from "../api/types";
import { useApi } from "../api/useApi";
import { Section } from "../components/MetricCard";
import { ApiErrorNotice, Loading, Notice } from "../components/States";
import { day, savedAt } from "../lib/format";
import { href, studyPath } from "../lib/route";
import { AllVariantsTable, FamilyTables } from "../research/Comparisons";
import { CostGrid, RegimeTables } from "../research/CostAndRegimes";
import { EdgeTable, VerdictTable } from "../research/Verdicts";

export function StudyPage({ studyId }: { studyId: string }) {
  const study = useApi<StudyFile>(studyPath(studyId));
  if (study.state === "loading") return <Loading what="study" />;
  if (study.state === "error") return <ApiErrorNotice error={study.error} what={studyId} />;
  const s = study.data;
  return (
    <div className="space-y-8">
      <a className="text-sm text-indigo-700 underline" href={href({ page: "studies" })}>
        ← all studies
      </a>
      <StudyHeader study={s} />
      <Section title="Does the baseline have an edge?">
        <EdgeTable study={s} />
      </Section>
      <Section title="Pre-registered variants (paired with the baseline, % of its premium)">
        <VerdictTable study={s} />
      </Section>
      <Section title="Every run">
        <AllVariantsTable study={s} />
      </Section>
      <Section title="Sensitivity families (reported in full, never used to choose)">
        <FamilyTables study={s} />
      </Section>
      <Section title="Cost grid (mean net % of premium, net ₹, t)">
        <CostGrid study={s} />
      </Section>
      <Section title="Baseline by regime (descriptive)">
        <RegimeTables study={s} />
      </Section>
    </div>
  );
}

function StudyHeader({ study }: { study: StudyFile }) {
  const plan = study.plan;
  const forward = plan.forward_holdout;
  return (
    <header className="space-y-3">
      <h1 className="font-mono text-xl font-semibold">{study.study_id}</h1>
      <Notice tone="warning" title="Nothing on this page is confirmed">
        <p>
          The validation period was already seen while building M4, so it can show that a result
          does not hold up, but it cannot confirm one. A variant can only be confirmed on the
          forward holdout: trades entered from {day(forward.first_entry)}, evaluated once at{" "}
          {forward.min_trades} completed trades or on {day(forward.latest_evaluation)}, whichever
          comes first.
        </p>
      </Notice>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm md:grid-cols-[max-content_1fr]">
        <dt className="text-slate-500">Periods</dt>
        <dd>
          {plan.periods.map((p) => `${p.name} ${day(p.start)} – ${day(p.end)}`).join("; ")}
        </dd>
        <dt className="text-slate-500">Statistics</dt>
        <dd>
          Two-sided paired t-test, Holm across {plan.holm_family.join(", ")} (alpha {plan.alpha});
          95% percentile bootstrap, {plan.bootstrap_resamples.toLocaleString("en-IN")} resamples,
          seed {plan.seed}, i.i.d. and circular blocks of {plan.block_length}. Verdicts use the
          conservative envelope of the two intervals (lower of the lower bounds, higher of the
          upper bounds).
        </dd>
        <dt className="text-slate-500">Unit</dt>
        <dd>
          Paired differences are in % of the baseline's premium for the same expiry; a week the
          variant skipped counts as 0 points.
        </dd>
        <dt className="text-slate-500">Plan</dt>
        <dd className="font-mono text-xs">
          {plan.path} (sha256 {plan.sha256.slice(0, 12)}), {plan.preregistration_path} (sha256{" "}
          {plan.preregistration_sha256.slice(0, 12)})
        </dd>
        <dt className="text-slate-500">Code</dt>
        <dd className="font-mono text-xs">
          {plan.git.head.slice(0, 7) || "unknown"}
          {plan.git.uncommitted_changes ? (
            <span className="ml-1 text-amber-700">+ uncommitted plan changes</span>
          ) : null}
          , run {savedAt(study.created_at)}, {study.runs.length} runs
        </dd>
      </dl>
    </header>
  );
}
