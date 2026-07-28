import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { social } from "./social";

const originalFetch = globalThis.fetch;

function mockFetch(body: unknown, ok = true, status = 200) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  } as Response);
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("social client", () => {
  it("always confirms explicitly when publishing", async () => {
    const spy = mockFetch([]);
    await social.publish("post-1", "now");

    const [, init] = spy.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({
      confirm: true,
      post_id: "post-1",
      mode: "now",
    });
  });

  it("sends the public_safe flag as a query parameter", async () => {
    const spy = mockFetch({ id: "c1", public_safe: true });
    await social.setContextPublicSafe("c1", true);

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/social/brain/c1?public_safe=true");
    expect(init.method).toBe("PATCH");
  });

  it("never sends server-owned fields when saving a brand kit", async () => {
    const spy = mockFetch({ version: 2 });
    await social.saveBrandKit({
      name: "Hayward Coffee Co.",
      tagline: "Your morning, sorted.",
      audience: "Regulars",
      tone: "warm",
      positioning: "A neighbourhood coffee bar.",
      avoid: [],
      colors: {
        primary: "#B4532A",
        secondary: "#A23B1E",
        accent: "#EFE3D3",
        background: "#FBF6EE",
        text: "#2A211C",
      },
      typography: {
        heading_family: "Spectral",
        body_family: "Hanken Grotesk",
        heading_weight: 600,
        body_weight: 400,
        scale: "balanced",
      },
      logo_url: null,
    });

    const [, init] = spy.mock.calls[0];
    const sent = JSON.parse(init.body);
    expect(sent).not.toHaveProperty("version");
    expect(sent).not.toHaveProperty("updated_at");
    expect(init.method).toBe("PUT");
  });

  it("surfaces the API's error detail", async () => {
    mockFetch({ detail: "Generate or write a reply before approving it." }, false, 422);
    await expect(social.updateComment("c1", { status: "approved" })).rejects.toThrow(
      "Generate or write a reply before approving it."
    );
  });
});
