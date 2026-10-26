// Saved research studies (M7), newest first, with the verdicts Python reached.
import type { StudySummary } from "../api/types";
import { useApi } from "../api/useApi";
import { ApiErrorNotice, Loading, Notice } from "../components/States";
import { day, savedAt } from "../lib/format";
import { href } from "../lib/route";

export function StudyList() {
  const studies = useApi<StudySummary[]>("/api/studies");

  if (studies.state === "loading") return <Loading what="studies" />;
  if (studies.state === "error") return <ApiErrorNotice error={studies.error} what="studies" />;
  if (studies.data.length === 0) {
    return (
      <Notice tone="info" title="No studies yet">
        <p>
          Run the pre-registered study with{" "}
          <code className="font-mono">uv run nifty-backtest study</code> (it needs the local data
          cache and takes about an hour).
        </p>
      </Notice>
    );
  }
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Research studies</h1>
      {studies.data.map((study) => (
        <StudyCard key={study.study_id} study={study} />
      ))}
    </div>
  );
}

function StudyCard({ study }: { study: StudySummary }) {
  if (study.status === "invalid") {
    return (
      <Notice tone="error" title={`Study ${study.study_id} cannot be read`}>
        {study.problems.map((p) => (
          <p key={p}>{p}</p>
        ))}
      </Notice>
    );
  }
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="font-mono text-sm">
        <a className="text-indigo-700 underline" href={href({ page: "study", studyId: study.study_id })}>
          {study.study_id}
        </a>
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        {study.created_at ? `Run ${savedAt(study.created_at)}` : null}
        {study.git_head ? ` from commit ${study.git_head.slice(0, 7)}` : null} · {study.run_count}{" "}
        runs · {study.periods.map((p) => `${p.name} ${day(p.start)} – ${day(p.end)}`).join("; ")}
      </p>
      <p className="mt-2 text-sm">
        <span className="text-slate-500">Baseline edge:</span> {study.edge_verdict}
      </p>
      <ul className="mt-2 flex flex-wrap gap-2 text-xs">
        {Object.entries(study.statuses).map(([variant, status]) => (
          <li key={variant} className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
            <span className="font-semibold">{variant}</span>: {status}
          </li>
        ))}
      </ul>
    </article>
  );
}
