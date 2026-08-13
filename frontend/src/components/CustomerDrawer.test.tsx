import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CustomerDrawer from "./CustomerDrawer";
import { PulseProvider } from "../context/PulseContext";
import type { CustomerRisk } from "../lib/api";

const CUSTOMER: CustomerRisk = {
  customer_id: "dana@example.com",
  db_customer_id: "3f6c1e6e-9c5e-4e8b-9c3f-2b1a5c7d8e90",
  name: "Dana Reyes",
  email: "dana@example.com",
  phone: null,
  score: 84,
  band: "high",
  reasons: ["Last visit 31 days ago — 3.1× their usual 10-day gap"],
  estimated_annual_value: 1240,
  days_since_last_visit: 31,
  last_visit: "2026-05-26",
  visit_count: 18,
  total_spend: 980,
  segment: "needs_attention",
  pattern: "fading_away",
  confidence: "high",
  trend_pct: -62,
  favorite_item: "Oat flat white",
  return_likelihood: 16,
  expected_next_visit: "2026-06-05",
  days_overdue: 21,
  payment_issue: false,
  recommended_action: "owner_call",
  action_reason:
    "Worth about $1,240/yr and away 31 days — one of your most valuable at-risk customers.",
};

/** Static render only (matching KnowledgeChat.test.tsx) — effects don't run, so
 * the timeline is caught mid-load, which is the state we want to assert about. */
function render(customer: CustomerRisk): string {
  return renderToStaticMarkup(
    <PulseProvider>
      <CustomerDrawer customer={customer} onClose={() => {}} />
    </PulseProvider>
  );
}

describe("CustomerDrawer", () => {
  it("shows the recommended action and the reason behind it", () => {
    const html = render(CUSTOMER);
    expect(html).toContain("Call them yourself");
    expect(html).toContain("$1,240/yr");
  });

  it("offers a history section when the customer has a persisted row", () => {
    expect(render(CUSTOMER)).toContain("History");
  });

  it("hides history entirely for in-memory demo rows", () => {
    // The demo and CSV-preview paths persist nothing, so there is no row to read
    // a timeline from — offering one would 404.
    const html = render({ ...CUSTOMER, db_customer_id: null });
    expect(html).not.toContain("Loading history");
  });

  it("never renders the string 'undefined' when the API is missing newer fields", () => {
    // A frontend can outrun its backend: mid-deploy, or pointed at a stale API,
    // fields added by recent releases are simply absent. That used to surface as
    // "undefined/100" in the Return likelihood tile.
    const stale = { ...CUSTOMER };
    for (const key of [
      "return_likelihood",
      "expected_next_visit",
      "days_overdue",
      "payment_issue",
      "recommended_action",
      "action_reason",
    ]) {
      delete (stale as Record<string, unknown>)[key];
    }
    const html = render(stale as CustomerRisk);
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
    // Still a usable panel rather than a blank one.
    expect(html).toContain("Dana Reyes");
    expect(html).toContain("Return likelihood");
  });

  it("falls back to a safe action label if the backend adds a new action", () => {
    const html = render({
      ...CUSTOMER,
      // Deliberately not a RecommendedAction — an older frontend must not crash
      // on a value a newer backend starts sending.
      recommended_action: "some_future_action" as CustomerRisk["recommended_action"],
    });
    expect(html).toContain("Send a win-back email");
  });
});
