import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { JoinSignedOut } from "./Join";

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
  return store;
}

describe("JoinSignedOut", () => {
  let store: Map<string, string>;
  beforeEach(() => {
    store = installStorage();
  });
  afterEach(() => {
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage;
  });

  it("keeps the invite token so it survives signing in", () => {
    renderToStaticMarkup(
      <MemoryRouter initialEntries={["/join?token=tok_abc"]}>
        <JoinSignedOut />
      </MemoryRouter>
    );
    expect([...store.values()]).toContain("tok_abc");
  });

  it("tells the invitee to use the address the invite went to", () => {
    // The backend binds invites to an email; signing in with a different one
    // fails, so the page has to say so up front.
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/join?token=tok_abc"]}>
        <JoinSignedOut />
      </MemoryRouter>
    );
    expect(html).toContain("the email address the invite was sent to");
    expect(html).toContain('href="/login"');
  });
});
