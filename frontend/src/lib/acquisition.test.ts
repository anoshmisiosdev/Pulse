import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  acquisitionForSignup,
  firstTouchAcquisition,
  rememberAcquisition,
} from "./acquisition";

class MemoryStorage {
  private values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

describe("acquisition attribution", () => {
  beforeEach(() => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", {
      location: {
        pathname: "/coffee-shop-customer-retention",
        search: "?utm_source=linkedin&utm_medium=founder_dm&utm_campaign=pilot_aug_2026&utm_content=aditya_a",
      },
      localStorage: storage,
    });
    vi.stubGlobal("document", { referrer: "https://www.linkedin.com/feed/?private=value" });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps bounded campaign fields and only the referrer hostname", () => {
    expect(acquisitionForSignup("coffee")).toEqual({
      source: "linkedin",
      medium: "founder_dm",
      campaign: "pilot_aug_2026",
      content: "aditya_a",
      landing_variant: "coffee",
      referrer_host: "www.linkedin.com",
    });
  });

  it("preserves the first touch while refreshing the last landing variant", () => {
    rememberAcquisition("coffee");
    window.location.search = "";
    window.location.pathname = "/gym-member-retention";

    const last = rememberAcquisition("gym");

    expect(firstTouchAcquisition()?.landing_variant).toBe("coffee");
    expect(last).toMatchObject({ source: "linkedin", landing_variant: "gym" });
  });
});
