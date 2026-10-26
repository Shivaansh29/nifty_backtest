import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StudyFile } from "../api/types";
import { errorStudyNotFound, STUDY_ID, study } from "../test/fixtures";
import { fail, mockApi, ok } from "../test/mockApi";
import { StudyPage } from "./StudyPage";

const path = `/api/studies/${STUDY_ID}`;

/** The fixture study with real-looking statistics for V3 in development (the synthetic study
 *  has one trade, so its own p-values and intervals are null). */
function withStatistics(): StudyFile {
  return {
    ...study,
    comparison: study.comparison.map((r) =>
      r.variant === "V3" && r.period === "development"
        ? { ...r, paired_mean: -7.352, paired_p: 0.0166, paired_p_holm: 0.0997, paired_ci_conservative: [-13.16, -1.05] }
        : r,
    ),
  };
}

describe("study page", () => {
  it("states that nothing is confirmed and labels validation as previously observed", async () => {
    mockApi({ [path]: ok(study) });
    render(<StudyPage studyId={STUDY_ID} />);
    expect(await screen.findByText("Nothing on this page is confirmed")).toBeInTheDocument();
    expect(screen.getByText(/forward holdout: trades entered from 15 Aug 2025/)).toBeInTheDocument();
    expect(screen.getByText("Historical validation (previously observed)")).toBeInTheDocument();
    expect(screen.getByText(/circular blocks of 2/)).toBeInTheDocument();
  });

  it("shows the baseline edge and every primary's verdict as the API reports them", async () => {
    mockApi({ [path]: ok(study) });
    render(<StudyPage studyId={STUDY_ID} />);
    expect(await screen.findByTestId("edge-verdict")).toHaveTextContent("edge not demonstrated");
    const verdicts = screen.getByRole("table", { name: /primary variants/ });
    const rows = within(verdicts).getAllByRole("row").slice(2);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0]?.textContent)).toEqual([
      "V1avix_min=16.0",
      "V3stop_multiple=1.25",
    ]);
    // V1a skipped the only week: the paired difference is minus the baseline's result.
    expect(rows[0]).toHaveTextContent("-53.90%");
    // One trade: no test and no interval are possible, and the page says so.
    expect(rows[0]).toHaveTextContent("n/a");
    expect(rows[0]).toHaveTextContent("inconclusive on development");
  });

  it("shows Holm p-values and envelope intervals unchanged", async () => {
    mockApi({ [path]: ok(withStatistics()) });
    render(<StudyPage studyId={STUDY_ID} />);
    const verdicts = await screen.findByRole("table", { name: /primary variants/ });
    const v3 = within(verdicts).getAllByRole("row")[3];
    expect(v3).toHaveTextContent("-7.35%");
    expect(v3).toHaveTextContent("0.017"); // raw p
    expect(v3).toHaveTextContent("0.100"); // Holm-adjusted p
    expect(v3).toHaveTextContent("[-13.16%, -1.05%]");
    expect(within(v3!).getAllByRole("img")[0]).toHaveAccessibleName(
      "mean -7.35%, interval [-13.16%, -1.05%]",
    );
    // The verdict is the API's, not re-derived from the interval.
    expect(v3).toHaveTextContent("inconclusive on development");
  });

  it("links every run to its page inside the study", async () => {
    mockApi({ [path]: ok(study) });
    render(<StudyPage studyId={STUDY_ID} />);
    const runs = await screen.findByRole("table", { name: "Every variant in every period" });
    const first = study.comparison[0]!;
    expect(within(runs).getAllByTitle(`open run ${first.run_id}`)[0]).toHaveAttribute(
      "href",
      `#/studies/${STUDY_ID}/runs/${first.run_id}`,
    );
  });

  it("shows families, the cost grid and regime tables", async () => {
    mockApi({ [path]: ok(study) });
    render(<StudyPage studyId={STUDY_ID} />);
    expect(await screen.findByText(/plateau \(neighbours same sign\): development n\/a/)).toBeInTheDocument();
    const grid = screen.getByRole("table", { name: "Cost grid for B0, development" });
    expect(grid).toHaveTextContent("53.90%");
    expect(grid).toHaveTextContent("₹8,852");
    expect(screen.getByText("vix_tercile")).toBeInTheDocument();
  });

  it("explains a missing study", async () => {
    mockApi({ [path]: fail(errorStudyNotFound) });
    render(<StudyPage studyId={STUDY_ID} />);
    expect(await screen.findByText(errorStudyNotFound.body.detail)).toBeInTheDocument();
    expect(screen.getByText(`Not found: ${STUDY_ID}`)).toBeInTheDocument();
  });
});
