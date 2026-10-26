// Display formatting only. Every number arrives from the API already computed; these
// functions decide how it is written, never what it is.
//
// Units matter: the API uses FRACTIONS for returns, ROI, CAGR, win rate and drawdown %
// (0.0177 = 1.77%), but trade-level percentages (pnl_pct_premium_*, nifty_move_pct) are
// already in PERCENT (3.46 = 3.46%). Use `fraction` for the first kind and `percentValue`
// for the second.

export const NA = "n/a";

const rupeeFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const rupeeWholeFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const fractionFormat = new Intl.NumberFormat("en-IN", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const dayFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const monthFormat = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const savedAtFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

type Maybe = number | null | undefined;

/** ₹ with Indian digit grouping: 279138.52 -> ₹2,79,138.52. */
export function rupees(value: Maybe): string {
  return value == null ? NA : rupeeFormat.format(value);
}

/** ₹ without paise, for chart axes. */
export function rupeesWhole(value: Maybe): string {
  return value == null ? NA : rupeeWholeFormat.format(value);
}

/** A fraction written as a percentage: 0.5583 -> 55.83%. */
export function fraction(value: Maybe): string {
  return value == null ? NA : fractionFormat.format(value);
}

/** A value that is already a percentage: 3.46 -> 3.46%. */
export function percentValue(value: Maybe): string {
  return value == null ? NA : `${value.toFixed(2)}%`;
}

/** A plain number such as a Sharpe ratio or t-statistic. */
export function decimal(value: Maybe, digits = 2): string {
  return value == null ? NA : value.toFixed(digits);
}

/** "2025-08-04" -> "4 Aug 2025". Dates are calendar dates, so they are read as UTC to avoid
 *  the browser's time zone shifting them by a day. */
export function day(iso: string | null | undefined): string {
  return iso ? dayFormat.format(new Date(`${iso}T00:00:00Z`)) : NA;
}

/** "2025-08" -> "Aug 2025". */
export function month(yearMonth: string): string {
  return monthFormat.format(new Date(`${yearMonth}-01T00:00:00Z`));
}

/** When a run was saved. The API sends the local time from the run id without a zone, so it
 *  is shown as written rather than converted. */
export function savedAt(localIso: string): string {
  return savedAtFormat.format(new Date(`${localIso}Z`));
}

/** A difference that is already in percent, with its sign: 2.4 -> "+2.40%". */
export function signedPercent(value: Maybe): string {
  if (value == null) return NA;
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** A confidence interval in percent: [-4.93, 10.31] -> "[-4.93%, +10.31%]". */
export function interval(value: readonly [number, number] | null | undefined): string {
  return value ? `[${signedPercent(value[0])}, ${signedPercent(value[1])}]` : NA;
}

/** A p-value: three decimals, or "< 0.001". */
export function pValue(value: Maybe): string {
  if (value == null) return NA;
  return value < 0.001 ? "< 0.001" : value.toFixed(3);
}
