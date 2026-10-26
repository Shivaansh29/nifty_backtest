import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { STUDY_ID, studies } from "../test/fixtures";
import { mockApi, ok } from "../test/mockApi";
import { StudyList } from "./StudyList";

describe("study list", () => {
  it("lists each study with the verdicts the API reports", async () => {
    mockApi({ "/api/studies": ok(studies) });
    render(<StudyList />);
    const link = await screen.findByRole("link", { name: STUDY_ID });
    expect(link).toHaveAttribute("href", `#/studies/${STUDY_ID}`);
    expect(screen.getByText("edge not demonstrated")).toBeInTheDocument();
    expect(screen.getByText("V1a").parentElement).toHaveTextContent("V1a: inconclusive");
    expect(screen.getByText("V3").parentElement).toHaveTextContent("V3: inconclusive");
  });

  it("shows an unreadable study with its problem", async () => {
    mockApi({
      "/api/studies": ok([
        { ...studies[0], status: "invalid", problems: ["study.json is missing"], statuses: {} },
      ]),
    });
    render(<StudyList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("study.json is missing");
  });

  it("says how to run a study when there are none", async () => {
    mockApi({ "/api/studies": ok([]) });
    render(<StudyList />);
    expect(await screen.findByText("No studies yet")).toBeInTheDocument();
    expect(screen.getByText("uv run nifty-backtest study")).toBeInTheDocument();
  });
});
