import type { Pattern, Segment } from "./api";

export interface SegmentMeta {
  label: string;
  health: string; // badge label used in the customer table
  color: string; // hex
  text: string; // tailwind text class
  bg: string; // tailwind bg+text chip classes
}

export const SEGMENTS: Record<Segment, SegmentMeta> = {
  needs_attention: {
    label: "Needs Attention",
    health: "Critical",
    color: "#ef4444",
    text: "text-red-600",
    bg: "bg-red-100 text-red-700",
  },
  slipping_away: {
    label: "Slipping Away",
    health: "At Risk",
    color: "#f59e0b",
    text: "text-amber-600",
    bg: "bg-amber-100 text-amber-700",
  },
  keep_an_eye_on: {
    label: "Keep an Eye On",
    health: "Watch",
    color: "#eab308",
    text: "text-yellow-600",
    bg: "bg-yellow-100 text-yellow-700",
  },
  regulars: {
    label: "Regulars",
    health: "Healthy",
    color: "#10b981",
    text: "text-emerald-600",
    bg: "bg-emerald-100 text-emerald-700",
  },
  new: {
    label: "New (Low Data)",
    health: "New",
    color: "#94a3b8",
    text: "text-slate-500",
    bg: "bg-slate-100 text-slate-600",
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

// Urgency tiers used by the retention queue.
export function urgencyOf(segment: Segment): "urgent" | "at_risk" | "watching" | null {
  if (segment === "needs_attention") return "urgent";
  if (segment === "slipping_away") return "at_risk";
  if (segment === "keep_an_eye_on") return "watching";
  return null;
}
