import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import AskChurnary from "./AskChurnary";

/** Replaces the old KnowledgeChat test. That component looked like a chat but
 * only filed knowledge snippets and replied with a fixed acknowledgement; this
 * one is the real assistant, with the knowledge capture kept as its "Teach" tab. */

describe("AskChurnary launcher", () => {
  const render = () =>
    renderToStaticMarkup(
      <MemoryRouter>
        <AskChurnary />
      </MemoryRouter>
    );

  it("renders closed by default, showing only the launcher", () => {
    const html = render();
    expect(html).toContain("Ask Churnary");
    // The panel's copy must not be in the markup while it's closed.
    expect(html).not.toContain("Answers from your own customer data");
    expect(html).not.toContain("Past conversations");
  });

  it("does not fetch or render conversation content on mount", () => {
    // Nothing should leak into the closed launcher — no thread titles, no
    // suggestions, no message bubbles.
    const html = render();
    expect(html).not.toContain("Thinking");
    expect(html).not.toContain("Review the drafted messages");
  });
});
