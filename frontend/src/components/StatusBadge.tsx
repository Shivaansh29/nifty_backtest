import type { RunStatus } from "../api/types";

const styles: Record<RunStatus, string> = {
  complete: "bg-emerald-100 text-emerald-800",
  metrics_missing: "bg-amber-100 text-amber-800",
  invalid: "bg-red-100 text-red-800",
};
const labels: Record<RunStatus, string> = {
  complete: "complete",
  metrics_missing: "metrics missing",
  invalid: "invalid",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}
