// How every part of the dashboard shows "still loading", "nothing here", "incomplete" and
// "failed". Messages come from the API's own error body wherever there is one.
import type { ReactNode } from "react";
import type { ApiFailure } from "../api/client";

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="animate-pulse py-6 text-sm text-slate-500">
      Loading {what}…
    </p>
  );
}

type Tone = "info" | "warning" | "error";
const toneClasses: Record<Tone, string> = {
  info: "border-slate-300 bg-slate-100 text-slate-800",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  error: "border-red-300 bg-red-50 text-red-900",
};

export function Notice({
  tone,
  title,
  children,
}: {
  tone: Tone;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "note"}
      className={`rounded-md border px-4 py-3 text-sm ${toneClasses[tone]}`}
    >
      <p className="font-semibold">{title}</p>
      {children ? <div className="mt-1 space-y-1">{children}</div> : null}
    </div>
  );
}

/** Text with `inline code` spans shown as code (the API's hints contain commands). */
export function WithCode({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/);
  return (
    <span>
      {parts.map((part, i) =>
        part.startsWith("`") && part.endsWith("`") ? (
          <code key={i} className="rounded bg-white/70 px-1 font-mono text-xs">
            {part.slice(1, -1)}
          </code>
        ) : (
          part
        ),
      )}
    </span>
  );
}

const titles: Record<number, string> = {
  0: "API not reachable",
  404: "Not found",
  409: "Not computed yet",
  422: "Invalid request",
  500: "Saved results are unreadable",
  503: "Market data not available",
};

/** An API failure: 409 (something not computed yet) is a warning with the API's fix; other
 *  statuses are errors. The error code and the file involved are shown when the API gave them. */
export function ApiErrorNotice({ error, what }: { error: ApiFailure; what?: string }) {
  const tone: Tone = error.status === 409 || error.status === 404 ? "warning" : "error";
  const title = (titles[error.status] ?? `Request failed (HTTP ${error.status})`) +
    (what ? `: ${what}` : "");
  return (
    <Notice tone={tone} title={title}>
      <p>
        <WithCode text={error.message} />
      </p>
      {error.body ? (
        <p className="text-xs opacity-75">
          {error.body.error}
          {error.body.artifact ? ` · ${error.body.artifact}` : ""}
        </p>
      ) : null}
    </Notice>
  );
}
