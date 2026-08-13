import { afterEach, describe, expect, it, vi } from "vitest";
import { subscribeRafScroll } from "./Landing";

/**
 * Regression test for the useRafScroll fan-out bug: every scroll-driven
 * effect on the landing page (nav, hero curtain, 9x ScrubWords headline)
 * used to register its own "scroll" listener and rAF chain instead of
 * sharing one, turning a single wheel spin into a forced-layout storm that
 * froze the tab. subscribeRafScroll is the shared scheduler behind
 * useRafScroll — this checks it binds window's "scroll" listener exactly
 * once no matter how many call sites subscribe.
 */
describe("subscribeRafScroll", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("registers exactly one scroll listener total, regardless of subscriber count", () => {
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    vi.stubGlobal("window", { addEventListener, removeEventListener });
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));

    const unsubscribers = Array.from({ length: 11 }, () => subscribeRafScroll(() => {}));

    const scrollListenerCalls = addEventListener.mock.calls.filter(([type]) => type === "scroll");
    expect(scrollListenerCalls).toHaveLength(1);

    unsubscribers.forEach((unsubscribe) => unsubscribe());
  });
});
