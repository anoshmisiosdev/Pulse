import { useId } from "react";

/**
 * The Churnary mark — a C-shaped orbit with the customer (the dot) re-entering
 * through the gap. Same artwork as `public/favicon.svg`; keep the two in step.
 *
 * Inline SVG rather than `<img src="/favicon.svg">` for two reasons: it survives
 * the self-contained landing-page export (scripts/inline-preview.mjs has no
 * sibling files to fetch), and it scales without a second asset.
 *
 * `tile` draws the dark rounded-square background. Turn it **off** over a dark
 * surface — the tile is espresso on espresso there and the mark all but
 * vanishes. Bare, the cream arc and terracotta dot carry it on their own.
 */
export default function ChurnaryMark({
  size = 30,
  tile = true,
  className = "",
}: {
  size?: number;
  tile?: boolean;
  className?: string;
}) {
  // A document-unique gradient id: the mark renders more than once per page
  // (header and footer), and duplicate ids make later instances resolve to the
  // first one's def. Colons from useId() are stripped — they're legal in an id
  // but trip up some SVG url(#…) resolvers.
  const gid = `churnary-mark-${useId().replace(/:/g, "")}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      className={className}
      // Decorative: every use sits beside the "Churnary" wordmark, so labelling
      // it here would just make a screen reader say the name twice.
      aria-hidden="true"
      focusable="false"
    >
      {tile && (
        <>
          <defs>
            <radialGradient id={gid} cx="30%" cy="25%" r="90%">
              <stop offset="0%" stopColor="#4A3527" />
              <stop offset="100%" stopColor="#33241B" />
            </radialGradient>
          </defs>
          <rect x="0" y="0" width="120" height="120" rx="27" fill={`url(#${gid})`} />
        </>
      )}
      <g transform="rotate(40 60 60)">
        <circle
          cx="60"
          cy="60"
          r="32"
          fill="none"
          stroke="#F4ECE0"
          strokeWidth="13"
          strokeLinecap="round"
          strokeDasharray="156.3 44.7"
        />
      </g>
      <circle cx="92" cy="60" r="8.5" fill="#C76B3A" />
    </svg>
  );
}
