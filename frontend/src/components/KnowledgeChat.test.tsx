import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import KnowledgeChat from "./KnowledgeChat";

describe("KnowledgeChat floating button", () => {
  it("renders closed by default with the launcher button, no panel", () => {
    const html = renderToStaticMarkup(<KnowledgeChat />);
    expect(html).toContain("Teach Churnary about your business");
    expect(html).not.toContain("Personalizes AI-written win-back campaigns");
  });
});
