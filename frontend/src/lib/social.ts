// Typed client for the social presence API. Mirrors backend/app/schemas/social.py.

import { API_BASE as BASE, asJson, authHeaders } from "./api";

const jsonHeaders = () => ({ "Content-Type": "application/json", ...authHeaders() });

// ── Brand kit ────────────────────────────────────────────────────────────────

export type TypeScale = "compact" | "balanced" | "editorial";

export interface BrandColors {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  text: string;
}

export interface BrandTypography {
  heading_family: string;
  body_family: string;
  heading_weight: number;
  body_weight: number;
  scale: TypeScale;
}

export interface BrandKit {
  version: number;
  updated_at: string;
  name: string;
  tagline: string;
  audience: string;
  tone: string;
  positioning: string;
  avoid: string[];
  colors: BrandColors;
  typography: BrandTypography;
  logo_url: string | null;
}

export type BrandKitInput = Omit<BrandKit, "version" | "updated_at">;

// ── Company brain ────────────────────────────────────────────────────────────

export type ContextKind =
  | "company"
  | "product"
  | "customer"
  | "founder"
  | "market"
  | "proof"
  | "other";

export interface ContextItem {
  id: string;
  title: string;
  kind: string;
  summary: string;
  source: string | null;
  date: string | null;
  tags: string[];
  public_safe: boolean;
  created_at: string;
  updated_at: string;
}

export interface ContextList {
  data: ContextItem[];
  total: number;
  public_safe: number;
}

export interface ContextInput {
  title: string;
  kind: ContextKind;
  summary: string;
  source?: string | null;
  date?: string | null;
  tags?: string[];
  public_safe?: boolean;
}

// ── Campaigns ────────────────────────────────────────────────────────────────

export type SocialPlatform = "linkedin" | "x";
export type CampaignStatus = "draft" | "generating" | "active" | "paused" | "completed";

export interface CampaignSlot {
  occurrence: number;
  scheduled_for: string;
  theme: string;
}

export interface SocialCampaign {
  id: string;
  name: string;
  brief: string;
  themes: string[];
  platforms: string[];
  start_at: string;
  timezone: string;
  interval_weeks: number;
  occurrences: number;
  status: CampaignStatus;
  last_error: string | null;
  slots: CampaignSlot[];
  post_count: number;
  created_at: string;
  updated_at: string;
}

export interface CampaignInput {
  name: string;
  brief: string;
  themes: string[];
  platforms: SocialPlatform[];
  start_at: string;
  timezone: string;
  interval_weeks: number;
  occurrences: number;
}

// ── Review queue ─────────────────────────────────────────────────────────────

export type PostStatus = "draft" | "approved" | "rejected" | "staged" | "posted" | "failed";
export type ReviewDecision = "approve" | "revise" | "reject";

export interface ReviewEvent {
  decision: string;
  reason: string;
  note: string | null;
  decided_at: string;
}

export interface SocialPost {
  id: string;
  campaign_id: string | null;
  campaign_occurrence: number | null;
  platform: string;
  topic: string;
  post_text: string;
  hashtags: string[];
  status: PostStatus;
  scheduled_for: string | null;
  posted_at: string | null;
  image_url: string | null;
  alt_text: string | null;
  source_summary: string | null;
  source_references: string[];
  editorial: {
    passed?: boolean;
    verdict?: string;
    errors?: string[];
    warnings?: string[];
  };
  warnings: string[];
  generated_by: string;
  published_url: string | null;
  failure_reason: string | null;
  review_history: ReviewEvent[];
  created_at: string;
}

export interface PublishResult {
  post_id: string;
  ok: boolean;
  status: string;
  message: string;
  provider_post_ids: string[];
  published_url: string | null;
}

// ── Engagement inbox ─────────────────────────────────────────────────────────

export type CommentIntent =
  | "product_question"
  | "sales_lead"
  | "complaint"
  | "praise"
  | "feedback"
  | "spam";
export type CommentStatus = "needs_reply" | "drafted" | "approved" | "resolved";
export type ReplyVariant = "standard" | "shorter" | "warmer";
export type Level = "high" | "medium" | "low";

export interface SocialComment {
  id: string;
  source: "demo" | "manual";
  platform: string;
  post_url: string | null;
  original_post_excerpt: string | null;
  author: string;
  comment: string;
  intent: CommentIntent;
  sentiment: string;
  priority: Level;
  risk: Level;
  recommended_action: string;
  status: CommentStatus;
  suggested_reply: string;
  approved_reply: string | null;
  reply_variant: ReplyVariant;
  reply_version: number;
  evidence: string[];
  created_at: string;
  updated_at: string;
}

export interface CommentList {
  data: SocialComment[];
  total: number;
  needs_reply: number;
  high_priority: number;
  demo_mode: boolean;
}

export interface Briefing {
  leads: number;
  high_risk: number;
  awaiting_reply: number;
  approved_today: number;
  top_topic: string | null;
  top_topic_count: number;
  top_question: string | null;
  recommended_action: string;
  estimated_minutes_saved: number;
  generated_at: string;
}

export interface SocialStatus {
  brand_kit_version: number;
  public_context_count: number;
  buffer_configured: boolean;
  llm_configured: boolean;
  publish_mode: string;
}

/**
 * Buffer setup state for this business.
 *
 * `connected` is per-business and distinct from `SocialStatus.buffer_configured`,
 * which only reports the deployment-wide key. `oauth_ready` is false until the
 * backend can actually exchange a token, and keeps step 3 disabled until then.
 */
export interface BufferConnect {
  connected: boolean;
  oauth_ready: boolean;
  signup_url: string;
  channels_url: string;
}

// ── Client ───────────────────────────────────────────────────────────────────

export const social = {
  async status(): Promise<SocialStatus> {
    return asJson(await fetch(`${BASE}/api/social/status`, { headers: authHeaders() }));
  },

  async bufferConnect(): Promise<BufferConnect> {
    return asJson(await fetch(`${BASE}/api/social/buffer/connect`, { headers: authHeaders() }));
  },

  async getBrandKit(): Promise<BrandKit> {
    return asJson(await fetch(`${BASE}/api/social/brand-kit`, { headers: authHeaders() }));
  },

  async saveBrandKit(kit: BrandKitInput): Promise<BrandKit> {
    return asJson(
      await fetch(`${BASE}/api/social/brand-kit`, {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify(kit),
      })
    );
  },

  async listContext(): Promise<ContextList> {
    return asJson(await fetch(`${BASE}/api/social/brain`, { headers: authHeaders() }));
  },

  async addContext(item: ContextInput): Promise<ContextItem> {
    return asJson(
      await fetch(`${BASE}/api/social/brain`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(item),
      })
    );
  },

  async setContextPublicSafe(id: string, publicSafe: boolean): Promise<ContextItem> {
    return asJson(
      await fetch(`${BASE}/api/social/brain/${id}?public_safe=${publicSafe}`, {
        method: "PATCH",
        headers: authHeaders(),
      })
    );
  },

  async deleteContext(id: string): Promise<void> {
    const res = await fetch(`${BASE}/api/social/brain/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok && res.status !== 204) throw new Error(`Request failed (${res.status})`);
  },

  async listCampaigns(): Promise<SocialCampaign[]> {
    return asJson(await fetch(`${BASE}/api/social/campaigns`, { headers: authHeaders() }));
  },

  async createCampaign(input: CampaignInput): Promise<SocialCampaign> {
    return asJson(
      await fetch(`${BASE}/api/social/campaigns`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(input),
      })
    );
  },

  async setCampaignStatus(id: string, status: CampaignStatus): Promise<SocialCampaign> {
    return asJson(
      await fetch(`${BASE}/api/social/campaigns/${id}`, {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ status }),
      })
    );
  },

  async generateCampaign(id: string): Promise<SocialCampaign> {
    return asJson(
      await fetch(`${BASE}/api/social/campaigns/${id}/generate`, {
        method: "POST",
        headers: authHeaders(),
      })
    );
  },

  async listPosts(params: { status?: string; platform?: string } = {}): Promise<SocialPost[]> {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.platform) q.set("platform", params.platform);
    const suffix = q.toString() ? `?${q}` : "";
    return asJson(await fetch(`${BASE}/api/social/posts${suffix}`, { headers: authHeaders() }));
  },

  async decidePost(
    id: string,
    decision: ReviewDecision,
    reason: string,
    note?: string
  ): Promise<SocialPost> {
    return asJson(
      await fetch(`${BASE}/api/social/posts/${id}/decision`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ decision, reason, note: note ?? null }),
      })
    );
  },

  async schedulePost(id: string, scheduledFor: string | null): Promise<SocialPost> {
    return asJson(
      await fetch(`${BASE}/api/social/posts/${id}/schedule`, {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({ scheduled_for: scheduledFor }),
      })
    );
  },

  /** Publishing is fail-closed — the backend rejects anything without confirm. */
  async publish(postId: string | null, mode: "now" | "queue" = "now"): Promise<PublishResult[]> {
    return asJson(
      await fetch(`${BASE}/api/social/posts/publish`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ confirm: true, post_id: postId, mode }),
      })
    );
  },

  async listInbox(): Promise<CommentList> {
    return asJson(await fetch(`${BASE}/api/social/inbox`, { headers: authHeaders() }));
  },

  async inboxBriefing(): Promise<Briefing> {
    return asJson(await fetch(`${BASE}/api/social/inbox/briefing`, { headers: authHeaders() }));
  },

  async captureComment(input: {
    platform: string;
    post_url?: string | null;
    author: string;
    comment: string;
  }): Promise<SocialComment> {
    return asJson(
      await fetch(`${BASE}/api/social/inbox`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(input),
      })
    );
  },

  async suggestReply(id: string, variant: ReplyVariant = "standard"): Promise<SocialComment> {
    return asJson(
      await fetch(`${BASE}/api/social/inbox/${id}/suggest`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ variant }),
      })
    );
  },

  async updateComment(
    id: string,
    patch: { status?: CommentStatus; suggested_reply?: string }
  ): Promise<SocialComment> {
    return asJson(
      await fetch(`${BASE}/api/social/inbox/${id}`, {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify(patch),
      })
    );
  },
};
