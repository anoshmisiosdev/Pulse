# Free account setup checklists

These steps configure free acquisition infrastructure; they do not register a
new domain. They assume Churnary already controls `churnary.ai`. Keep recovery
methods with the company, use MFA, give each founder an individual login where
the service permits it, and never put credentials or tokens in the acquisition
sheet or repository.

## Google Search Console

**Owner:** Aditya Kolekar
**Backup owner:** Soham Dogra
**Cost:** free

- [ ] After deploying this PR, confirm `https://churnary.ai/robots.txt` returns
  200 as plain text and visibly begins with `User-agent:`, and confirm
  `https://churnary.ai/sitemap.xml` returns 200 as XML and contains `<urlset>`.
  A 200 response serving the SPA's HTML shell does not pass this check.
- [ ] In [Google Search Console](https://search.google.com/search-console), add
  a **Domain property** for `churnary.ai`—do not enter a protocol or path.
- [ ] Copy the provided DNS TXT verification record into the domain provider;
  keep it in place after verification. Domain verification covers protocols and
  subdomains. [Google's property setup guide](https://support.google.com/webmasters/answer/34592)
- [ ] Add the backup as an owner after the primary property is verified. Do not
  share the primary login.
- [ ] Open **Sitemaps**, submit `https://churnary.ai/sitemap.xml`, and confirm
  it is fetched without error.
- [ ] Use URL Inspection on `/`, `/customer-churn-risk-calculator`,
  `/coffee-shop-customer-retention`, `/salon-customer-retention`, and
  `/gym-member-retention`; request indexing only after the deployed canonical
  page is accessible.
- [ ] View source for each inspected route and confirm its route-specific title,
  description, canonical URL, visible H1 copy, and structured data are present
  in the delivered HTML before submitting the sitemap.
- [ ] Enable email notifications. Each Wednesday, record clicks, impressions,
  CTR, top queries/pages, indexing problems, manual actions, and security issues.
- [ ] After a release, inspect the changed URL and monitor its sitemap/indexing
  status; a sitemap helps discovery but does not guarantee ranking or indexing.

Google recommends the domain-level property when DNS verification is possible
and provides sitemap monitoring through the Sitemaps report.
[Official Search Console tasks](https://support.google.com/webmasters/answer/10351509)

## Bing Webmaster Tools

**Owner:** Aditya Kolekar
**Backup:** Soham Dogra
**Cost:** free

- [ ] Sign into [Bing Webmaster Tools](https://www.bing.com/webmasters/) with a
  company-controlled/recoverable Microsoft account.
- [ ] Choose **Import from Google Search Console**, authorize only the required
  property access, and select `churnary.ai`. This can import the verified site
  and its sitemap. [Bing add/verify guide](https://www.bing.com/webmasters/help/add-and-verify-site-12184f8b)
- [ ] If import is unavailable, add the site manually and use the DNS
  verification method shown by Bing; do not remove an existing Google token.
- [ ] Confirm `/sitemap.xml` appears under Sitemaps and has no processing error.
  Submit it manually if it was not imported.
  [Bing sitemap guide](https://www.bing.com/webmasters/help/Sitemaps-3b5cf6ed)
- [ ] Inspect the same five public acquisition URLs and note crawl/indexing
  errors; do not repeatedly submit unchanged URLs.
- [ ] Each Wednesday, review search performance, crawl/index coverage, security
  notices, and sitemap status. Record aggregate learnings, not visitor identity.
- [ ] Quarterly, review the Google connection and owner access; disconnect
  integrations no longer needed.

## LinkedIn company page and founder profiles

**Page super admins:** Soham Dogra (primary), Aditya Kolekar (backup)
**Content admins:** all four founders
**Cost:** free; do not start Premium for this sprint

LinkedIn allows creation of a company Page for free. The creator becomes its
super admin and can assign other admins.
[Official LinkedIn Page setup](https://www.linkedin.com/help/linkedin/answer/a545752)

Company Page:

- [ ] Search LinkedIn for an existing Churnary listing before creating a
  duplicate. If none exists, Soham selects **For Business → Create a Company
  Page → Company** on desktop.
- [ ] Use the public name `Churnary`, official logo, `https://churnary.ai`, U.S.
  location, and only factual company details. Suggested tagline: “Explainable
  customer retention for local businesses.”
- [ ] Add Aditya as a backup super admin and Riyan/Pranjal as content admins;
  each person uses their own account and MFA.
- [ ] Publish a short introduction that says the product is early-stage and
  examples are demos. Use a pre-built campaign URL, not an untagged homepage.
- [ ] Connect the Page—not a founder profile—to Buffer. Pin/feature up to the
  allowed number of high-value Page posts if the option is available.
- [ ] Weekly, record Page impressions, link clicks, follows, and replies in
  aggregate. Do not call reactions leads unless the person actually converts.

Each founder profile:

- [ ] Add a truthful `Co-founder · Churnary` Experience entry, a concise About
  sentence explaining the local-business retention problem, and the Churnary
  Page association.
- [ ] Publish one founder introduction post with the same destination and
  campaign but founder-specific `utm_content`, for example
  `aditya_general_profile_v1`; personalization preserves assignment.
- [ ] Add that public post/link to a profile section available on the founder's
  current free account (for example Projects/media or Featured if offered). Do
  not upgrade solely for a custom/Featured button; availability can differ by
  account and product tier.
- [ ] Verify the public link in a signed-out browser and ensure the profile does
  not claim pilots, results, or integrations that do not exist.
- [ ] Post the founder rows in `social-calendar.csv` manually. Do not give a
  shared automation tool access to personal profiles for this sprint.

## Buffer

**Operator/account owner:** Soham Dogra
**Recovery owner:** Aditya Kolekar
**Cost:** free; no card and no paid upgrade

As of July 15, 2026, Buffer documents three connected channels, one user, and
ten queued posts per channel on its Free plan. It also documents a lifetime
limit of eight unique channel connections. Automatic custom UTM parameters and
team approvals are not included, so Churnary must pre-tag links and keep
approval in the restricted sheet.
[Buffer free-plan features](https://support.buffer.com/article/595-features-available-on-each-buffer-plan)

- [ ] Create the Buffer workspace under the company-controlled social-operator
  login. If Buffer starts a paid trial, set a calendar reminder before it ends
  and confirm the workspace returns to Free; do not enter a card.
- [ ] Connect exactly two channels: the **Churnary LinkedIn Page** and the
  **Churnary X account**. Leave the third slot unused unless the weekly review
  explicitly approves a durable brand channel; reconnecting disposable test
  channels consumes the documented lifetime limit.
- [ ] To connect LinkedIn, sign in through a Page super admin, then select the
  company Page rather than the personal profile.
  [Buffer's LinkedIn connection steps](https://support.buffer.com/article/560-using-linkedin-with-buffer)
- [ ] Set a conservative brand posting schedule matching the three dated brand
  rows each week. Queue no more than ten posts per channel.
- [ ] Draft/review in `Social Calendar`: founder writes, a second founder checks
  claims and links, Soham marks `approved`, then schedules. The free Buffer
  workspace has one operator; no shared password substitutes for approvals.
- [ ] Paste the fully tagged URL from `UTM Builder`, open the preview, and click
  the preview link before scheduling. Adapt the X version for length; do not
  simply truncate a claim or disclosure. For a cross-posted CTA, build one URL
  with `utm_source=linkedin` and a second with `utm_source=x`; never reuse one
  platform's URL on the other.
- [ ] After publishing, set the calendar row to `published` and record platform
  results during the weekly review. Keep PostHog as the source of truth for
  onsite clicks and signups.
- [ ] If a channel disconnects, troubleshoot the existing connection before
  deleting/re-adding it. Never connect founder profiles for this sprint.

## Final pre-launch check

- [ ] All five public URLs, robots, sitemap, social image, and consent controls
  are deployed and tested before submitting/indexing/scheduling.
- [ ] Every outbound link follows `pilot_aug_2026` conventions and contains no
  prospect data.
- [ ] Search Console and Bing have two owners; LinkedIn has two super admins;
  Buffer has a documented recovery owner without a shared password.
- [ ] The restricted Sheet contains the source of truth for approval, outreach,
  do-not-contact, and follow-up status.
- [ ] No paid trial, paid list, scraping tool, or paid automation is active.
