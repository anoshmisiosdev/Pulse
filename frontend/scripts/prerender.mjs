import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const siteUrl = (process.env.VITE_PUBLIC_SITE_URL || "https://churnary.ai").replace(/\/$/, "");
const shell = await readFile(path.join(dist, "index.html"), "utf8");
const pages = JSON.parse(await readFile(path.join(root, "src/content/marketing-pages.json"), "utf8"));

const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

function setHead(html, page) {
  const canonical = `${siteUrl}${page.path === "/" ? "/" : page.path}`;
  const image = `${siteUrl}/churnary-social-card.png`;
  const schema = [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "Churnary",
      url: siteUrl,
      logo: `${siteUrl}/apple-touch-icon.png`,
    },
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: "Churnary",
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url: canonical,
      description: page.description,
      offers: { "@type": "Offer", price: "0", priceCurrency: "USD", description: "Free early access" },
    },
  ];
  const tags = `
    <link rel="canonical" href="${escapeHtml(canonical)}" />
    <meta property="og:title" content="${escapeHtml(page.title)}" />
    <meta property="og:description" content="${escapeHtml(page.description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${escapeHtml(canonical)}" />
    <meta property="og:image" content="${escapeHtml(image)}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="Churnary — know which regulars are drifting before they disappear" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${escapeHtml(page.title)}" />
    <meta name="twitter:description" content="${escapeHtml(page.description)}" />
    <meta name="twitter:image" content="${escapeHtml(image)}" />
    ${schema.map((entry) => `<script type="application/ld+json" data-churnary-schema>${JSON.stringify(entry).replaceAll("<", "\\u003c")}</script>`).join("\n    ")}`;
  return html
    .replace(/<title>.*?<\/title>/s, `<title>${escapeHtml(page.title)}</title>`)
    .replace(/<meta name="description"[^>]*>/, `<meta name="description" content="${escapeHtml(page.description)}" />`)
    .replace(/\s*<link rel="canonical"[^>]*>/, "")
    .replace(/\s*<meta property="og:[^>]*>/g, "")
    .replace(/\s*<meta name="twitter:[^>]*>/g, "")
    .replace("</head>", `${tags}\n  </head>`);
}

function visibleMarkup(page) {
  return `<div data-prerendered="true" style="max-width:1120px;margin:0 auto;padding:72px 24px;font-family:system-ui;color:#2a211c">
    <header><a href="/" style="color:#2a211c;font-weight:800;text-decoration:none">Churnary</a></header>
    <main>
      <p style="margin-top:80px;color:#b4532a;font-weight:800;text-transform:uppercase;letter-spacing:.12em">${escapeHtml(page.eyebrow)}</p>
      <h1 style="max-width:820px;font:600 clamp(44px,7vw,80px)/1.02 Georgia,serif;letter-spacing:-.04em">${escapeHtml(page.headline)}</h1>
      <p style="max-width:720px;font-size:20px;line-height:1.6;color:#6f5d50">${escapeHtml(page.lede)}</p>
      <section><h2>Estimate customer retention risk</h2><p>Use the free calculator, then join early access with just your email.</p><a href="#early-access">Get early access</a></section>
      <section><h2>Connect, understand, approve</h2><p>Connect Square, Stripe, or a CSV. See transparent customer-level signals. Review every message before it is sent.</p></section>
      <section id="early-access"><h2>Get early access</h2><p>Free while we learn with early businesses. No card required.</p></section>
    </main>
  </div>`;
}

function documentFor(page) {
  return setHead(shell, page).replace('<div id="root"></div>', `<div id="root">${visibleMarkup(page)}</div>`);
}

async function emit(route, html) {
  if (route === "/") {
    await writeFile(path.join(dist, "index.html"), html);
    return;
  }
  const relative = route.replace(/^\//, "");
  const routeDir = path.join(dist, relative);
  await mkdir(routeDir, { recursive: true });
  await writeFile(path.join(routeDir, "index.html"), html);
  await writeFile(path.join(dist, `${relative}.html`), html);
}

for (const page of pages) await emit(page.path, documentFor(page));
await emit("/landing", documentFor(pages[0]));

const privacy = {
  path: "/privacy",
  title: "Privacy Policy | Churnary",
  description: "Learn what Churnary collects, why we use it, and how to control optional analytics and session insights.",
  eyebrow: "Privacy in plain language",
  headline: "Privacy, in plain language.",
  lede: "Understand how Churnary handles website, waitlist, and business customer information.",
};
await emit(privacy.path, documentFor(privacy));

const notFound = {
  path: "/404",
  title: "Page not found | Churnary",
  description: "The page you requested could not be found. Return to Churnary customer retention.",
  eyebrow: "404 · Page not found",
  headline: "This customer took a different route.",
  lede: "Return home or open the free customer churn risk calculator.",
};
let notFoundHtml = documentFor(notFound).replace('content="index, follow, max-image-preview:large"', 'content="noindex, nofollow"');
await writeFile(path.join(dist, "404.html"), notFoundHtml);

console.log(`Prerendered ${pages.length + 3} public acquisition documents.`);
