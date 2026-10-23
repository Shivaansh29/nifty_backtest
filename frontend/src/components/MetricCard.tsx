import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  detail,
  badge,
}: {
  label: string;
  value: string;
  detail?: ReactNode;
  badge?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
        {badge ? (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] normal-case text-slate-600">
            {badge}
          </span>
        ) : null}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums" data-testid={`metric-${label}`}>
        {value}
      </p>
      {detail ? <div className="mt-1 text-xs text-slate-600">{detail}</div> : null}
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3" aria-label={title}>
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}
