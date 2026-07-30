// Typed client for the public waitlist endpoint.
// Mirrors backend/app/schemas/waitlist.py.

import { API_BASE as BASE, authHeaders } from "./api";

export interface WaitlistInput {
  name: string;
  email: string;
  business_name?: string;
  vertical?: string;
  note?: string;
}

export interface WaitlistResult {
  ok: boolean;
  already_joined: boolean;
}

/** Same shape the backend validates with, so the two agree on what's valid. */
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/**
 * FastAPI validation errors arrive as `detail: [{loc, msg, ...}]`, and the
 * shared `asJson` helper would stringify that array into "[object Object]".
 * Pull out the first human-readable message instead.
 */
function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string } | undefined;
    if (first?.msg) return first.msg.replace(/^Value error,\s*/, "");
  }
  return `Something went wrong (${status}). Please try again.`;
}

export const waitlist = {
  async join(input: WaitlistInput): Promise<WaitlistResult> {
    // `website` is the honeypot — always sent empty from a real form so the
    // backend can treat a filled one as a bot without a visible captcha.
    const res = await fetch(`${BASE}/api/waitlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ website: "", ...input }),
    });
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        /* non-JSON error body */
      }
      throw new Error(messageFrom(body, res.status));
    }
    return res.json() as Promise<WaitlistResult>;
  },
};
