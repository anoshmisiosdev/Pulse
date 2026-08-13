import { describe, expect, it } from "vitest";
import { buildRb2bScriptUrl } from "./Rb2bLoader";

describe("buildRb2bScriptUrl", () => {
  it("builds the documented default script URL", () => {
    expect(buildRb2bScriptUrl("account_123")).toBe(
      "https://s3-us-west-2.amazonaws.com/b2bjsstore/b/account_123/reb2b.js.gz"
    );
  });

  it("supports RB2B's CloudFront template and rejects unrelated hosts", () => {
    expect(
      buildRb2bScriptUrl(
        "account_123",
        "https://ddwl4m2hdecbv.cloudfront.net/b/{key}/{key}.js.gz"
      )
    ).toBe(
      "https://ddwl4m2hdecbv.cloudfront.net/b/account_123/account_123.js.gz"
    );
    expect(
      buildRb2bScriptUrl("account_123", "https://example.com/{key}.js")
    ).toBeNull();
  });
});
