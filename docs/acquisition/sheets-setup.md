# Google Sheets operating setup

The live [Churnary Acquisition — Pilot Aug 2026
workbook](https://docs.google.com/spreadsheets/d/1kUQE4rLkDkMvtUPckOlmc1KDg_k-oDjOPzh1Kli4HpM/edit)
is ready to use. It contains `Dashboard`, `Prospects`, `Weekly Scorecard`,
`Content Calendar`, `Lists & Guide`, and `UTM Builder`. The CSV files in this
folder contain no prospect data and remain portability/recovery templates; do
not re-import them over the live tabs.

Before entering a prospect, an owner must manually open **Share** and verify
**General access: Restricted**. A link that opens for a founder does not prove
the workbook is restricted. Only Aditya Kolekar, Riyan Anosh, Pranjal Mishra,
and Soham Dogra receive edit access. Do not enable link sharing or invite
automation/enrichment tools. Review version history periodically and enable
edit notifications if the account offers them. Never store credentials,
private phone numbers, sensitive traits, or copied personal-profile content in
this workbook.

The instructions below describe the live tabs exactly. The portability CSVs
have a wider archival schema and use their own header names; do not apply CSV
column letters to the live workbook.

## Prospects

The tab is a native Google Sheets table with a frozen header and built-in
dropdowns. Use one row per public business contact point and search by business,
website, contact, and source URL before adding anything.

| Columns | Purpose |
| --- | --- |
| A–C | Exclusion/status and founder owner |
| D–N | Business, vertical, location, public contact channel/source, and one observable personalization fact |
| O–Q | Actual touch 1/2/3 dates |
| R | Fully tagged Churnary UTM link |
| S–U | Response, waitlist status, and held feedback-call checkbox |
| V–W | Next action and due date |
| X | Notes |
| Y–Z | Signup timestamp and first human-response timestamp |
| AA | Response hours, calculated automatically from Y/Z |
| AB | Do-not-contact checkbox |

Keep `Locations` between 1 and 5. Website, source, and tracked-link values must
use `https://`; the tracked link must contain `utm_source`, `utm_medium`,
`utm_campaign=pilot_aug_2026`, `utm_content`, and `landing_variant`. Column AA is
formula-controlled. Checking AB grays and strikes through the row.

### Per-row workflow

1. Before entry, search business name, hostname, public contact point, and the
   do-not-contact rows.
2. Record the source URL and neutral observation; verify location count and
   active public presence.
3. Build the UTM URL using the conventions below, test it, then send manually.
4. Enter each sent date immediately. Do not mark a scheduled message as
   sent.
5. On any reply, update S and clear or replace V/W. For an opt-out, set S to
   `Unsubscribed`, check AB, and clear all future actions immediately.
6. Check U only after a feedback call happens. Copy Y/Z from the signup and
   response records; do not estimate them from memory. AA is elapsed clock
   hours for operational review; the two-business-hour SLA is checked manually
   against the 9:00 a.m.–5:00 p.m. PT rule in the runbook.

## UTM Builder

The live `UTM Builder` tab is ready to use:

```text
A Base URL | B Source / platform | C Medium | D Campaign |
E Founder / account | F Message variant | G Landing variant |
H Tracked URL | I Notes
```

Duplicate the example row, keep `pilot_aug_2026` in D, and choose the validated
values in B, C, E, and G. Column H combines the founder/account and message
variant into `utm_content` automatically:

```text
=IF(A2="","",A2&IF(REGEXMATCH(A2,"\?"),"&","?")&"utm_source="&ENCODEURL(B2)&"&utm_medium="&ENCODEURL(C2)&"&utm_campaign="&ENCODEURL(D2)&"&utm_content="&ENCODEURL(LOWER(E2&"_"&F2))&IF(G2="","","&landing_variant="&ENCODEURL(G2)))
```

Do not edit H directly. UTM values never contain prospect information.

## Weekly Scorecard

Rows 4–7 are the four sprint weeks. Enter consented PostHog counts only in D–G
and O. Enter H from unique accepted signup records, not PostHog, so visitors who
declined analytics still count. I–J come from `Prospects` replies and held calls.
K is calculated from `Prospects` touch-1 dates. L–M and P–S calculate conversion
rates, while T shows median elapsed response hours from `Prospects` Y–AA. Review
business-hours SLA compliance manually; T is not a business-hours calculation.

| Columns | Metric |
| --- | --- |
| D–G, O | Consented PostHog funnel counts: sessions, clicks, calculator interactions, form starts, and valid submissions |
| H | Unique accepted signups from the waitlist database/admin queue, including non-consenting visitors |
| I–K | Prospect-tracker replies, held calls, and outreach contacts |
| L–M | Waitlist conversion and reply rate |
| N | Decision or weekly learning |
| O | Valid submissions |
| P–S | Outreach CTR, calculator interaction, form start, and form completion rates |
| T | Median elapsed signup-response hours; blank until a response sample exists |

Use the event definitions in [`utm-and-scorecard.md`](utm-and-scorecard.md); do
not substitute post impressions or raw pageview totals. Evaluate thresholds by
channel/vertical/message in PostHog or copied scorecard rows, not only from the
blended weekly total.

If a portability CSV import renders a formula as plain text, select the range,
change its format to **Automatic**, remove the leading apostrophe if present,
and re-enter the first formula before filling down. Check for `#REF!`,
`#DIV/0!`, `#VALUE!`, `#NAME?`, and `#N/A` before every weekly review.

## Content Calendar

The live table has 28 dated concepts: date/week/author/account/platform/type,
topic, CTA, tracked link, status, published URL, sessions, signups, and notes.
Each week contains four founder LinkedIn posts and three brand concepts for
LinkedIn plus an adapted X version. Only CTA rows contain a tracked link; all
other rows are value-only. Posts 26–28 are September 8–10, so Labor Day remains
clear. For a `LinkedIn + X` CTA concept, create a second X-tagged URL in the UTM
Builder; never reuse the LinkedIn-tagged URL on X. Before approval, verify every
claim against shipped behavior or observed aggregate data and label all
sample/demo content.

## Portability templates

`lead-tracker-template.csv`, `weekly-scorecard-template.csv`, and
`social-calendar.csv` are recovery/export formats with their own headers and
formulas. They are not a second operating system. If the live workbook must be
rebuilt, import them into a new restricted workbook and follow the header names
inside those files rather than the live column letters above. Name the imported
lead-tracker tab exactly `Lead Tracker` before importing the weekly scorecard;
its formulas reference that tab name.

## Weekly access and data hygiene

- Wednesday: owners reconcile their ten-per-day counts and overdue actions.
- Friday: Aditya reviews sharing settings, unexpected editors, formula errors,
  duplicates, and do-not-contact handling.
- September 11: export an access-controlled archive, remove stale access, and
  retain only fields still needed for pilot follow-up. Do not publish the raw
  lead sheet or include prospect-level data in a public sprint retrospective.
