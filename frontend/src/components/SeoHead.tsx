import { useEffect } from "react";

const DEFAULT_SITE_URL = "https://churnary.ai";
const SOCIAL_IMAGE_PATH = "/churnary-social-card.png";

export interface SeoHeadProps {
  title: string;
  description: string;
  path: string;
  pageType?: "website" | "software";
  noIndex?: boolean;
}

function upsertMeta(selector: string, attributes: Record<string, string>) {
  let node = document.head.querySelector<HTMLMetaElement>(selector);
  if (!node) {
    node = document.createElement("meta");
    document.head.appendChild(node);
  }
  Object.entries(attributes).forEach(([name, value]) => node?.setAttribute(name, value));
}

function upsertLink(rel: string, href: string) {
  let node = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!node) {
    node = document.createElement("link");
    node.rel = rel;
    document.head.appendChild(node);
  }
  node.href = href;
}

export default function SeoHead({
  title,
  description,
  path,
  pageType = "website",
  noIndex = false,
}: SeoHeadProps) {
  useEffect(() => {
    const siteUrl = String(import.meta.env.VITE_PUBLIC_SITE_URL || DEFAULT_SITE_URL).replace(/\/$/, "");
    const canonical = `${siteUrl}${path === "/" ? "" : path}`;
    const socialImage = `${siteUrl}${SOCIAL_IMAGE_PATH}`;
    document.title = title;

    upsertMeta('meta[name="description"]', { name: "description", content: description });
    upsertMeta('meta[name="robots"]', {
      name: "robots",
      content: noIndex ? "noindex, nofollow" : "index, follow, max-image-preview:large",
    });
    upsertMeta('meta[property="og:title"]', { property: "og:title", content: title });
    upsertMeta('meta[property="og:description"]', { property: "og:description", content: description });
    upsertMeta('meta[property="og:type"]', { property: "og:type", content: "website" });
    upsertMeta('meta[property="og:url"]', { property: "og:url", content: canonical });
    upsertMeta('meta[property="og:image"]', { property: "og:image", content: socialImage });
    upsertMeta('meta[property="og:image:width"]', { property: "og:image:width", content: "1200" });
    upsertMeta('meta[property="og:image:height"]', { property: "og:image:height", content: "630" });
    upsertMeta('meta[property="og:image:alt"]', {
      property: "og:image:alt",
      content: "Churnary customer-retention dashboard illustration",
    });
    upsertMeta('meta[name="twitter:card"]', { name: "twitter:card", content: "summary_large_image" });
    upsertMeta('meta[name="twitter:title"]', { name: "twitter:title", content: title });
    upsertMeta('meta[name="twitter:description"]', { name: "twitter:description", content: description });
    upsertMeta('meta[name="twitter:image"]', { name: "twitter:image", content: socialImage });
    upsertLink("canonical", canonical);

    document.querySelectorAll("script[data-churnary-schema]").forEach((node) => node.remove());
    const schemas = [
      {
        "@context": "https://schema.org",
        "@type": "Organization",
        name: "Churnary",
        url: siteUrl,
        logo: `${siteUrl}/apple-touch-icon.png`,
        description: "Customer-retention software for repeat-visit local businesses.",
      },
      {
        "@context": "https://schema.org",
        "@type": pageType === "software" ? "SoftwareApplication" : "WebSite",
        name: pageType === "software" ? "Churnary" : title,
        url: canonical,
        description,
        ...(pageType === "software"
          ? {
              applicationCategory: "BusinessApplication",
              operatingSystem: "Web",
              offers: { "@type": "Offer", price: "0", priceCurrency: "USD", description: "Free early access" },
            }
          : {}),
      },
    ];
    schemas.forEach((schema) => {
      const script = document.createElement("script");
      script.type = "application/ld+json";
      script.dataset.churnarySchema = "true";
      script.text = JSON.stringify(schema);
      document.head.appendChild(script);
    });
  }, [description, noIndex, pageType, path, title]);

  return null;
}
