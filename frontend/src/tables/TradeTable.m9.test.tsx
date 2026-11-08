// M9: a condor's Strike column shows its four strikes, from legs.csv; nothing is guessed.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CONDOR_RUN_ID, condorLegs, condorTrades, RUN_ID, trades } from "../test/fixtures";
import { TradeTable } from "./TradeTable";

function strikeCell(): string | null {
  const table = screen.getByRole("table", { name: "Trades" });
  const row = within(table).getAllByRole("row")[1]!;
  return within(row).getAllByRole("cell")[4]!.textContent;
}

describe("trade table strikes", () => {
  it("shows the four strikes of a condor, put wing to call wing", () => {
    render(<TradeTable trades={condorTrades} legs={condorLegs} runId={CONDOR_RUN_ID} />);
    expect(strikeCell()).toBe("24,000 / 24,250 · 24,750 / 25,000");
  });

  it("shows a dash, never a made-up strike, when no strike is known", () => {
    render(<TradeTable trades={condorTrades} runId={CONDOR_RUN_ID} />);
    expect(strikeCell()).toBe("—");
  });

  it("shows the straddle's one strike as before", () => {
    render(<TradeTable trades={trades} runId={RUN_ID} />);
    expect(strikeCell()).toBe("25,000");
  });
});
