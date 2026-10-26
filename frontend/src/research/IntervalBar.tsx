// A one-row "forest plot": an interval and its mean against a zero line. Presentation only:
// the interval and mean are the API's; this only decides where to draw them.
//
// Deliberately one neutral colour. An interval that happens to exclude zero is NOT a verdict
// (the verdict also needs the Holm-adjusted p-value and the tail checks), so the plot does
// not colour it as one.
import type { Interval } from "../api/types";
import { interval, signedPercent } from "../lib/format";

const WIDTH = 160;
const HEIGHT = 14;

/** The [low, high] range that fits every interval and zero, so rows share one scale. */
export function sharedDomain(intervals: (Interval | null | undefined)[]): Interval {
  let low = 0;
  let high = 0;
  for (const ci of intervals) {
    if (!ci) continue;
    low = Math.min(low, ci[0]);
    high = Math.max(high, ci[1]);
  }
  return low === high ? [low - 1, high + 1] : [low, high];
}

export function IntervalBar({
  ci,
  mean,
  domain,
}: {
  ci: Interval | null | undefined;
  mean: number | null | undefined;
  domain: Interval;
}) {
  if (!ci) return <span className="text-slate-400">n/a</span>;
  const x = (v: number) => ((v - domain[0]) / (domain[1] - domain[0])) * WIDTH;
  return (
    <svg
      width={WIDTH}
      height={HEIGHT}
      role="img"
      aria-label={`mean ${signedPercent(mean)}, interval ${interval(ci)}`}
    >
      <line x1={x(0)} x2={x(0)} y1={0} y2={HEIGHT} stroke="#94a3b8" strokeDasharray="2 2" />
      <line x1={x(ci[0])} x2={x(ci[1])} y1={HEIGHT / 2} y2={HEIGHT / 2} stroke="#334155" strokeWidth={2} />
      <line x1={x(ci[0])} x2={x(ci[0])} y1={3} y2={HEIGHT - 3} stroke="#334155" strokeWidth={2} />
      <line x1={x(ci[1])} x2={x(ci[1])} y1={3} y2={HEIGHT - 3} stroke="#334155" strokeWidth={2} />
      {mean != null ? <circle cx={x(mean)} cy={HEIGHT / 2} r={3} fill="#4338ca" /> : null}
    </svg>
  );
}
