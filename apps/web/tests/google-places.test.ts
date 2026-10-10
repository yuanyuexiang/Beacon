import { describe, expect, it } from "vitest";
import { formatMoney, formatPriceRange, PRICE_LEVEL } from "../src/lib/google-places";

describe("Google price reference", () => {
  it("keeps missing values unknown and does not invent a midpoint", () => {
    expect(formatPriceRange(null)).toBe("未知");
    expect(formatPriceRange({})).toBe("未知");
    expect(PRICE_LEVEL.PRICE_LEVEL_UNSPECIFIED).toBeUndefined();
  });
  it("preserves currency, decimals and unbounded ranges", () => {
    const startPrice = { currencyCode: "GBP", units: "20", nanos: 500000000 };
    expect(formatMoney(startPrice)).toContain("20.5");
    expect(formatPriceRange({ startPrice })).toContain("以上");
    expect(formatPriceRange({ endPrice: startPrice })).toContain("以下");
    expect(formatPriceRange({ startPrice, endPrice: { currencyCode: "GBP", units: "50" } })).toContain("–");
    expect(formatMoney({ currencyCode: "USD", units: "0" })).toContain("0");
  });
});
