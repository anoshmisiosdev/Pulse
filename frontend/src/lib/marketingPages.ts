import pages from "../content/marketing-pages.json";

export type MarketingVertical = "cafe" | "salon" | "fitness";

export interface MarketingPage {
  key: "general" | "coffee" | "salon" | "gym" | "calculator";
  path: string;
  title: string;
  description: string;
  eyebrow: string;
  headline: string;
  lede: string;
  defaultVertical: MarketingVertical;
  audienceLabel: string;
}

export const MARKETING_PAGES = pages as MarketingPage[];
export const MARKETING_PATHS = MARKETING_PAGES.map((page) => page.path);

export function getMarketingPage(pathname: string): MarketingPage {
  const normalized = pathname === "/landing" ? "/" : pathname.replace(/\/$/, "") || "/";
  return MARKETING_PAGES.find((page) => page.path === normalized) ?? MARKETING_PAGES[0];
}

export function isMarketingPath(pathname: string): boolean {
  const normalized = pathname === "/landing" ? "/" : pathname.replace(/\/$/, "") || "/";
  return MARKETING_PATHS.includes(normalized);
}
