import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";

// ── helpers ──────────────────────────────────────────────────────────────────
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

async function pbkdf2(password: string, saltHex: string): Promise<string> {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    enc.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: hexToBytes(saltHex), iterations: 100_000, hash: "SHA-256" },
    keyMaterial,
    256,
  );
  return bytesToHex(new Uint8Array(bits));
}

function randomSaltHex(): string {
  return bytesToHex(crypto.getRandomValues(new Uint8Array(16)));
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "tenant"
  );
}

// The backend (FastAPI) is the only caller; it presents the shared key.
function authorized(req: Request): boolean {
  const key = req.headers.get("x-pulse-key");
  return !!process.env.PULSE_API_KEY && key === process.env.PULSE_API_KEY;
}

// ── routes ───────────────────────────────────────────────────────────────────
const http = httpRouter();

http.route({
  path: "/auth/login",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    if (!authorized(req)) return json({ error: "forbidden" }, 403);
    const { email, password } = await req.json();
    if (!email || !password) return json({ error: "missing fields" }, 400);

    const user = await ctx.runQuery(internal.users.byEmail, { email });
    if (!user) return json({ error: "invalid credentials" }, 401);

    const computed = await pbkdf2(password, user.salt);
    if (!timingSafeEqual(computed, user.passwordHash)) {
      return json({ error: "invalid credentials" }, 401);
    }

    const business = await ctx.runQuery(internal.businesses.byId, { id: user.businessId });
    return json({
      userId: user._id,
      businessId: user.businessId,
      businessName: business?.name ?? "My Business",
      email: user.email,
      role: user.role,
    });
  }),
});

http.route({
  path: "/auth/register",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    if (!authorized(req)) return json({ error: "forbidden" }, 403);
    const { email, password, businessName } = await req.json();
    if (!email || !password || !businessName) return json({ error: "missing fields" }, 400);

    const existing = await ctx.runQuery(internal.users.byEmail, { email });
    if (existing) return json({ error: "email already registered" }, 409);

    const businessId = await ctx.runMutation(internal.businesses.create, {
      name: businessName,
      slug: slugify(businessName),
    });
    const salt = randomSaltHex();
    const passwordHash = await pbkdf2(password, salt);
    const userId = await ctx.runMutation(internal.users.create, {
      email,
      passwordHash,
      salt,
      businessId,
      role: "owner",
    });

    return json({ userId, businessId, businessName, email, role: "owner" });
  }),
});

export default http;
