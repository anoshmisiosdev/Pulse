import type { Pattern, Segment } from "./api";

export interface SegmentMeta {
  label: string;
  health: string; // badge label used in the customer table
  color: string; // chart/dot hex
  badgeText: string; // badge text hex
  badgeBg: string; // badge background hex
}

export const SEGMENTS: Record<Segment, SegmentMeta> = {
  needs_attention: {
    label: "Needs Attention",
    health: "Critical",
    color: "#A23B1E",
    badgeText: "#A23B1E",
    badgeBg: "#F7E3DC",
  },
  slipping_away: {
    label: "Slipping Away",
    health: "At Risk",
    color: "#C76B3A",
    badgeText: "#C0632F",
    badgeBg: "#F7E6DA",
  },
  keep_an_eye_on: {
    label: "Keep an Eye On",
    health: "Watch",
    color: "#D99A4E",
    badgeText: "#A9781F",
    badgeBg: "#F4EAD1",
  },
  regulars: {
    label: "Regulars",
    health: "Healthy",
    color: "#5C8A4A",
    badgeText: "#4F7A40",
    badgeBg: "#E6EFDF",
  },
  new: {
    label: "New (Low Data)",
    health: "New",
    color: "#C9B39A",
    badgeText: "#8A7565",
    badgeBg: "#EFE6D8",
  },
};

export const SEGMENT_ORDER: Segment[] = [
  "needs_attention",
  "slipping_away",
  "keep_an_eye_on",
  "regulars",
  "new",
];

export const PATTERNS: Record<Exclude<Pattern, null>, string> = {
  fading_away: "Fading Away",
  stopped_suddenly: "Stopped Suddenly",
  group_left: "Group Left",
  not_enough_data: "Not Enough Data",
};

// Warm ramp used for the "Why They Leave" bars, by rank.
export const PATTERN_BAR_COLORS = ["#B4532A", "#C76B3A", "#D99A4E", "#C9B39A"];

// Urgency tiers used by the retention queue.
export function urgencyOf(segment: Segment): "urgent" | "at_risk" | "watching" | null {
  if (segment === "needs_attention") return "urgent";
  if (segment === "slipping_away") return "at_risk";
  if (segment === "keep_an_eye_on") return "watching";
  return null;
}
