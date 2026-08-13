import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearOptionalTrackingData,
  PRIVACY_PREFERENCE_KEY,
} from "../lib/privacyPreferences";

afterEach(() => vi.unstubAllGlobals());

describe("session-recording privacy", () => {
  it("removes known Clarity cookies with other optional tracking data", () => {
    const removed: string[] = [];
    vi.stubGlobal("window", {
      localStorage: { removeItem: () => undefined },
      sessionStorage: { removeItem: () => undefined },
      location: { hostname: "churnary.ai" },
    });
    vi.stubGlobal("document", {
      get cookie() { return ""; },
      set cookie(value: string) { removed.push(value); },
    });

    clearOptionalTrackingData();

    expect(removed.some((value) => value.startsWith("_clck="))).toBe(true);
    expect(removed.some((value) => value.startsWith("_clsk="))).toBe(true);
  });

  it("does not treat a stored preference key as implicit consent", () => {
    vi.stubGlobal("window", {
      localStorage: { getItem: (key: string) => key === PRIVACY_PREFERENCE_KEY ? null : null },
    });
    expect(window.localStorage.getItem(PRIVACY_PREFERENCE_KEY)).toBeNull();
  });
});
