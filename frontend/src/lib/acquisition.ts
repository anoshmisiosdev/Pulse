import { getMarketingPage } from "./marketingPages";

export interface AcquisitionContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  landing_variant?: string;
  referrer_host?: string;
}

const FIRST_TOUCH_KEY = "churnary_first_touch_v1";
const LAST_TOUCH_KEY = "churnary_last_touch_v1";
const MAX_PARAM_LENGTH = 100;

function bounded(value: string | null | undefined, max = MAX_PARAM_LENGTH): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed.slice(0, max) : undefined;
}

function safeRead(key: string): AcquisitionContext | null {
  try {
    const value = window.localStorage.getItem(key);
    return value ? (JSON.parse(value) as AcquisitionContext) : null;
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: AcquisitionContext) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Attribution is useful, never essential to joining the waitlist.
  }
}

function currentContext(landingVariant?: string): AcquisitionContext {
  const params = new URLSearchParams(window.location.search);
  let referrerHost: string | undefined;
  if (typeof document !== "undefined" && document.referrer) {
    try {
      referrerHost = bounded(new URL(document.referrer).hostname, 253);
    } catch {
      // Invalid referrers are ignored rather than leaking a raw value.
    }
  }
  return {
    source: bounded(params.get("utm_source")),
    medium: bounded(params.get("utm_medium")),
    campaign: bounded(params.get("utm_campaign")),
    content: bounded(params.get("utm_content")),
    landing_variant: bounded(
      params.get("landing_variant") || landingVariant || getMarketingPage(window.location.pathname).key
    ),
    referrer_host: referrerHost,
  };
}

function compact(context: AcquisitionContext): AcquisitionContext {
  return Object.fromEntries(
    Object.entries(context).filter(([, value]) => Boolean(value))
  ) as AcquisitionContext;
}

/** Persist first/last touch locally so a same-browser return keeps its source. */
export function rememberAcquisition(landingVariant?: string): AcquisitionContext {
  const current = compact(currentContext(landingVariant));
  const existingLast = safeRead(LAST_TOUCH_KEY) ?? {};
  const hasCampaignTouch = Boolean(
    current.source || current.medium || current.campaign || current.content || current.referrer_host
  );
  const last = compact({
    ...existingLast,
    ...(hasCampaignTouch ? current : {}),
    landing_variant: current.landing_variant || existingLast.landing_variant,
  });
  if (!safeRead(FIRST_TOUCH_KEY)) safeWrite(FIRST_TOUCH_KEY, last);
  safeWrite(LAST_TOUCH_KEY, last);
  return last;
}

export function acquisitionForSignup(landingVariant?: string): AcquisitionContext {
  return rememberAcquisition(landingVariant);
}

export function firstTouchAcquisition(): AcquisitionContext | null {
  return safeRead(FIRST_TOUCH_KEY);
}
