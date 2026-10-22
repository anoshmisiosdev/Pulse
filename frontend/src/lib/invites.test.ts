import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  inviteTokenFromSearch,
  peekInviteToken,
  stashInviteToken,
  takeInviteToken,
} from "./invites";

/** Minimal sessionStorage for the node test environment. */
function installStorage() {
  const store = new Map<string, string>();
  (globalThis as { sessionStorage?: Storage }).sessionStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: () => null,
    length: 0,
  } as Storage;
}

describe("invite token handling", () => {
  beforeEach(installStorage);
  afterEach(() => {
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage;
  });

  it("reads the token from the query string", () => {
    expect(inviteTokenFromSearch("?token=abc123")).toBe("abc123");
    expect(inviteTokenFromSearch("?token=%20abc%20")).toBe("abc");
  });

  it("treats a missing or blank token as no token", () => {
    expect(inviteTokenFromSearch("")).toBeNull();
    expect(inviteTokenFromSearch("?token=")).toBeNull();
    expect(inviteTokenFromSearch("?other=1")).toBeNull();
  });

  it("survives a round trip through storage and is used only once", () => {
    // The signed-out site redirects everything to "/", so the token has to
    // outlive that redirect -- and must not be replayed on every later load.
    stashInviteToken("tok_1");
    expect(peekInviteToken()).toBe("tok_1");
    expect(takeInviteToken()).toBe("tok_1");
    expect(takeInviteToken()).toBeNull();
    expect(peekInviteToken()).toBeNull();
  });

  it("degrades to nothing when storage is unavailable rather than throwing", () => {
    // Private-mode browsers can throw on any storage access.
    (globalThis as { sessionStorage?: Storage }).sessionStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(() => stashInviteToken("x")).not.toThrow();
    expect(takeInviteToken()).toBeNull();
    expect(peekInviteToken()).toBeNull();
  });
});
