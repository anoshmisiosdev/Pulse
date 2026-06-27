import { describe, expect, it } from "vitest";
import { formatCurrency } from "./api";

describe("formatCurrency", () => {
  it("formats whole dollars with no cents", () => {
    expect(formatCurrency(2100)).toBe("$2,100");
  });

  it("rounds to the nearest dollar", () => {
    expect(formatCurrency(155901.49)).toBe("$155,901");
  });

  it("handles zero", () => {
    expect(formatCurrency(0)).toBe("$0");
  });
});
