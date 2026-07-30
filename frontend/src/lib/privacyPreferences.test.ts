import { beforeEach, describe, expect, it } from "vitest";
import {
  ANALYTICS_ID_STORAGE_KEY,
  PRIVACY_PREFERENCE_KEY,
  VISITOR_SESSION_STORAGE_KEY,
  effectivePrivacyPreference,
  hasAnalyticsConsent,
  savePrivacyPreference,
} from "./privacyPreferences";

class MemoryStorage {
  private values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

function setGpc(enabled: boolean) {
  Object.defineProperty(navigator, "globalPrivacyControl", {
    configurable: true,
    value: enabled,
  });
}

describe("privacy preferences", () => {
  beforeEach(() => {
    const localStorage = new MemoryStorage();
    const sessionStorage = new MemoryStorage();
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage,
        sessionStorage,
        location: { hostname: "churnary.test" },
        dispatchEvent: () => true,
      },
    });
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "" },
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: {},
    });
    Object.defineProperty(globalThis, "CustomEvent", {
      configurable: true,
      value: class TestCustomEvent {
        constructor(
          public type: string,
          public init?: { detail?: unknown }
        ) {}
      },
    });
    window.localStorage.clear();
    window.sessionStorage.clear();
    setGpc(false);
  });

  it("allows analytics only after an explicit choice", () => {
    expect(effectivePrivacyPreference()).toBeNull();
    expect(hasAnalyticsConsent()).toBe(false);

    savePrivacyPreference("granted");

    expect(hasAnalyticsConsent()).toBe(true);
    expect(JSON.parse(window.localStorage.getItem(PRIVACY_PREFERENCE_KEY) ?? "{}")).toMatchObject({
      analytics: "granted",
      source: "choice",
    });
  });

  it("lets Global Privacy Control override a stored grant", () => {
    savePrivacyPreference("granted");
    setGpc(true);

    expect(effectivePrivacyPreference()).toMatchObject({
      analytics: "denied",
      source: "gpc",
    });
    expect(hasAnalyticsConsent()).toBe(false);
  });

  it("cannot grant analytics while GPC is active and clears optional identifiers", () => {
    window.localStorage.setItem(ANALYTICS_ID_STORAGE_KEY, "browser-id");
    window.sessionStorage.setItem(VISITOR_SESSION_STORAGE_KEY, "session-id");
    setGpc(true);

    const saved = savePrivacyPreference("granted");

    expect(saved).toMatchObject({ analytics: "denied", source: "gpc" });
    expect(window.localStorage.getItem(ANALYTICS_ID_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(VISITOR_SESSION_STORAGE_KEY)).toBeNull();
  });
});
