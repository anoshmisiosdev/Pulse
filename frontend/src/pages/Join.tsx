import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import {
  inviteTokenFromSearch,
  peekInviteToken,
  stashInviteToken,
  takeInviteToken,
} from "../lib/invites";

/** Signed-out half of the invite flow: keep the token, send them to sign in. */
export function JoinSignedOut() {
  const { search } = useLocation();
  const token = inviteTokenFromSearch(search);
  if (token) stashInviteToken(token);

  return (
    <div className="grid min-h-screen place-items-center px-4" style={{ background: "var(--cream)" }}>
      <div
        className="w-full max-w-md rounded-[20px] border p-8 text-center"
        style={{ borderColor: "var(--line)", background: "var(--card)" }}
      >
        <h1 className="font-display text-[26px] font-bold" style={{ color: "var(--ink)" }}>
          You've been invited to Churnary
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          Sign in or create an account with the email address the invite was sent to,
          and you'll join the team automatically.
        </p>
        <Link
          to="/login"
          className="mt-6 inline-block rounded-full px-6 py-2.5 text-sm font-semibold text-white"
          style={{ background: "var(--accent)" }}
        >
          Sign in to accept
        </Link>
      </div>
    </div>
  );
}

/** Signed-in half: accept the invite from the URL or from before sign-in. */
export default function Join() {
  const { search } = useLocation();
  const [state, setState] = useState<"working" | "joined" | "error">("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    // Strict mode runs effects twice in dev; an invite is single-use, so the
    // second call would fail and overwrite the success message.
    if (started.current) return;
    started.current = true;

    const token = inviteTokenFromSearch(search) ?? takeInviteToken();
    takeInviteToken(); // clear any stashed copy either way
    if (!token) {
      setState("error");
      setMessage("This link doesn't include an invite. Ask whoever invited you to send it again.");
      return;
    }
    api
      .acceptInvite(token)
      .then((member) => {
        setState("joined");
        setMessage(`You've joined as ${member.role === "owner" ? "an owner" : "staff"}.`);
      })
      .catch((e) => {
        setState("error");
        setMessage(e instanceof Error ? e.message : "Couldn't accept this invite.");
      });
  }, [search]);

  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div
        className="w-full max-w-md rounded-[20px] border p-8 text-center"
        style={{ borderColor: "var(--line)", background: "var(--card)" }}
      >
        {state === "working" && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            Joining the team…
          </p>
        )}
        {state === "joined" && (
          <>
            <h1 className="font-display text-[24px] font-bold" style={{ color: "var(--ink)" }}>
              You're in
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
              {message}
            </p>
            {/* A full reload, not a route change: the account you're looking at
                just changed, and every cached screen belongs to the old one. */}
            <button
              onClick={() => window.location.assign("/")}
              className="mt-6 rounded-full px-6 py-2.5 text-sm font-semibold text-white"
              style={{ background: "var(--accent)" }}
            >
              Go to the dashboard
            </button>
          </>
        )}
        {state === "error" && (
          <>
            <h1 className="font-display text-[22px] font-bold" style={{ color: "var(--ink)" }}>
              That invite didn't work
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--accent-dark)" }}>
              {message}
            </p>
            <Link to="/" className="mt-6 inline-block text-sm underline" style={{ color: "var(--muted)" }}>
              Back to the dashboard
            </Link>
          </>
        )}
      </div>
    </div>
  );
}

/** After sign-in the app lands on "/", not /join. If a token was stashed
 * before signing in, take them to accept it. */
export function PendingInviteRedirect() {
  const { pathname } = useLocation();
  if (pathname === "/join") return null;
  return peekInviteToken() ? <Navigate to="/join" replace /> : null;
}
