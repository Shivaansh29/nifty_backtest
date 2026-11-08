// M9: the iron condor study page keeps verdicts and descriptions apart and states every
// unverified cost assumption. The fixture is the synthetic study of tests/test_condor_study.py.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { M9_STUDY_ID, m9Study } from "../test/fixtures";
import { mockApi, ok } from "../test/mockApi";
import { StudyPage } from "./StudyPage";

const path = `/api/studies/${M9_STUDY_ID}`;

describe("M9 study page", () => {
  it("separates pre-registered verdicts from descriptive results", async () => {
    mockApi({ [path]: ok(m9Study) });
    render(<StudyPage studyId={M9_STUDY_ID} />);
    expect(await screen.findByRole("heading", { name: "Verdicts (pre-registered rule)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Descriptive only/ })).toBeInTheDocument();
    const q2 = screen.getByRole("table", { name: /primary variants/ });
    expect(within(q2).getAllByRole("row").slice(2)).toHaveLength(3); // C1, C2, C3
  });

  it("states each cost assumption as unverified", async () => {
    mockApi({ [path]: ok(m9Study) });
    render(<StudyPage studyId={M9_STUDY_ID} />);
    expect(await screen.findByText(/not a verified legal fact/)).toBeInTheDocument();
    expect(screen.getByText(/not a confirmed statutory requirement/)).toBeInTheDocument();
    expect(screen.getByText(/IPFT included in GST's base for every run/)).toBeInTheDocument();
  });

  it("shows Q1 on R_P for B0 and every primary, with its verdict", async () => {
    mockApi({ [path]: ok(m9Study) });
    render(<StudyPage studyId={M9_STUDY_ID} />);
    const q1 = await screen.findByRole("table", { name: /own edge/ });
    const rows = within(q1).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(8);
    expect(rows[2]).toHaveTextContent("C1");
    expect(rows[2]).toHaveTextContent("-78.23%"); // the hand-computed trade's R_P
    expect(rows[2]).toHaveTextContent("edge not demonstrated");
  });

  it("shows the risk table, sensitivities and the traced trades as descriptions", async () => {
    mockApi({ [path]: ok(m9Study) });
    render(<StudyPage studyId={M9_STUDY_ID} />);
    expect(await screen.findByRole("table", { name: /risk trade-off/ })).toBeInTheDocument();
    const sens = screen.getByRole("table", { name: /cost-assumption sensitivities/i });
    expect(within(sens).getAllByText("stamp").length).toBeGreaterThan(0);
    expect(screen.getByText(/hypothetical cases, not estimates and not legal limits/i)).toBeInTheDocument();
    expect(screen.getByText("NIFTY-2025-06-05")).toBeInTheDocument();
  });
});
