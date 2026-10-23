import { useEffect, useState } from "react";
import { ApiFailure, apiGet } from "./client";

export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; error: ApiFailure }
  | { state: "ok"; data: T };

/** Fetch one API path and track its loading / error / data state. A new path cancels the
 *  previous request, so a slow answer for an old run can never overwrite a newer one. */
export function useApi<T>(path: string): Loadable<T> {
  const [result, setResult] = useState<{ path: string; value: Loadable<T> }>({
    path,
    value: { state: "loading" },
  });

  useEffect(() => {
    const controller = new AbortController();
    apiGet<T>(path, controller.signal).then(
      (data) => setResult({ path, value: { state: "ok", data } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const failure =
          error instanceof ApiFailure ? error : new ApiFailure(0, String(error));
        setResult({ path, value: { state: "error", error: failure } });
      },
    );
    return () => controller.abort();
  }, [path]);

  // Until the effect for a new path has answered, report loading rather than old data.
  return result.path === path ? result.value : { state: "loading" };
}
