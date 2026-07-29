/**
 * Throwaway entry used only to export the landing page as one static HTML file
 * for design review. Not part of the app build.
 *
 * Two things differ from the real page, both because the export has no backend:
 *   - MemoryRouter, not BrowserRouter — the history API is unreliable on file://
 *     URLs, and the only routed links here ("Sign in") aren't part of the review.
 *   - fetch is stubbed for /api/waitlist so the form still reaches its success
 *     state instead of erroring against a server that isn't there.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import Landing from "../src/pages/Landing";
import "../src/index.css";

const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (url.includes("/api/waitlist")) {
    // Match the shape of WaitlistOut so the form takes its normal happy path.
    await new Promise((r) => setTimeout(r, 700));
    return new Response(JSON.stringify({ ok: true, already_joined: false }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  return realFetch(input as RequestInfo, init);
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MemoryRouter>
      <Landing />
    </MemoryRouter>
  </StrictMode>
);
