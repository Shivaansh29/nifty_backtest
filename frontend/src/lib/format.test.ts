import { describe, expect, it } from "vitest";
import { day, decimal, fraction, month, NA, percentValue, rupees, savedAt } from "./format";

describe("format", () => {
  it("writes rupees with Indian digit grouping", () => {
    expect(rupees(279138.515828206)).toBe("₹2,79,138.52");
    expect(rupees(8852.28050405)).toBe("₹8,852.28");
    expect(rupees(-41067.44104031697)).toBe("-₹41,067.44");
  });

  it("writes fractions as percentages, but leaves percent values as they are", () => {
    // ROI 0.5583 is a fraction; % of premium 3.46 is already a percentage.
    expect(fraction(0.558277031656)).toBe("55.83%");
    expect(percentValue(3.46)).toBe("3.46%");
  });

  it("shows n/a for missing values instead of 0", () => {
    for (const formatter of [rupees, fraction, percentValue, decimal]) {
      expect(formatter(null)).toBe(NA);
      expect(formatter(undefined)).toBe(NA);
    }
  });

  it("reads dates as calendar dates, whatever the browser's time zone", () => {
    expect(day("2025-08-04")).toBe("4 Aug 2025");
    expect(month("2025-08")).toBe("Aug 2025");
    expect(savedAt("2025-08-07T16:00:00")).toBe("7 Aug 2025, 16:00");
  });
});
