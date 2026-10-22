// Carrying an invite token across sign-in.
//
// An invite link is /join?token=…, but most people who click one aren't signed
// in yet. The signed-out site has a catch-all redirect to "/", so without this
// the token would be dropped on the floor. It's stashed in sessionStorage —
// per-tab, gone when the tab closes, and it survives the same-tab redirect a
// Google sign-in does — then picked up once the app knows who they are.

const KEY = "pulse_pending_invite";

export function inviteTokenFromSearch(search: string): string | null {
  const token = new URLSearchParams(search).get("token");
  return token && token.trim() ? token.trim() : null;
}

export function stashInviteToken(token: string): void {
  try {
    sessionStorage.setItem(KEY, token);
  } catch {
    // Storage blocked (private mode): the user can still open the link again
    // after signing in, so this degrades rather than breaks.
  }
}

/** Read and clear the pending token, so it's used at most once. */
export function takeInviteToken(): string | null {
  try {
    const token = sessionStorage.getItem(KEY);
    if (token) sessionStorage.removeItem(KEY);
    return token;
  } catch {
    return null;
  }
}

export function peekInviteToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}
