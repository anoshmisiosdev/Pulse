# Attribution and weekly scorecard

## Campaign link contract

Every outbound link must use this exact grammar:

```text
https://churnary.ai/{destination}?utm_source={platform}&utm_medium={motion}&utm_campaign=pilot_aug_2026&utm_content={owner}_{message_variant}&landing_variant={page_version}
```

Use lowercase ASCII `snake_case`; keep each attribution value at 100 characters
or fewer and `landing_variant` at 80 or fewer. Never place a prospect name,
email, business name, profile URL, or other personal data in a query parameter.
URLs appear in browser history, server logs, analytics, and link previews.

### Allowed values

| Parameter | Allowed value |
| --- | --- |
| `utm_source` | `linkedin`, `x`, `instagram`, `email`, `community` |
| `utm_medium` | `founder_dm`, `organic_social`, `community` |
| `utm_campaign` | `pilot_aug_2026` |
| `utm_content` | `{aditya|riyan|pranjal|soham|brand}_{vertical}_{variant}_v1` |
| `landing_variant` | `home_v1`, `calculator_v1`, `coffee_v1`, `salon_v1`, `gym_v1` |

Use `founder_dm` for a founder's email or DM, `organic_social` for a public
founder/brand post, and `community` only for a rule-compliant community link.
The owner prefix is both attribution and the inbound assignment signal. Brand
posts use `brand`; unowned signups receive a stable, balanced roster owner and
the current inbound-duty founder covers any absence.

Cross-posted brand concepts require two tracked URLs: one with
`utm_source=linkedin` and one with `utm_source=x`. The version-controlled social
calendar stores the LinkedIn URL as the primary link; generate the X sibling in
the UTM Builder before scheduling the adapted X post.

Recommended destinations:

| Audience / intent | Destination | `landing_variant` |
| --- | --- | --- |
| Café owner education | `/coffee-shop-customer-retention` | `coffee_v1` |
| Salon/barbershop education | `/salon-customer-retention` | `salon_v1` |
| Gym/fitness education | `/gym-member-retention` | `gym_v1` |
| Any calculation-led message | `/customer-churn-risk-calculator` | `calculator_v1` |
| General early access | `/` | `home_v1` |

Examples:

```text
https://churnary.ai/customer-churn-risk-calculator?utm_source=linkedin&utm_medium=founder_dm&utm_campaign=pilot_aug_2026&utm_content=aditya_cafe_t1_observation_v1&landing_variant=calculator_v1

https://churnary.ai/salon-customer-retention?utm_source=x&utm_medium=organic_social&utm_campaign=pilot_aug_2026&utm_content=brand_salon_booking_gap_v1&landing_variant=salon_v1

https://churnary.ai/gym-member-retention?utm_source=community&utm_medium=community&utm_campaign=pilot_aug_2026&utm_content=soham_gym_ownerforum_answer_v1&landing_variant=gym_v1
```

Because Buffer's free plan does not include custom UTM parameters, paste the
already-tagged URL into the post. Do not rely on Buffer to append it.

### Google Sheets link builder

The live restricted workbook already contains a validated `UTM Builder` table:

```text
A Base URL | B Source / platform | C Medium | D Campaign |
E Founder / account | F Message variant | G Landing variant |
H Tracked URL | I Notes
```

Duplicate its example row, keep `pilot_aug_2026` in D, and use the dropdowns.
Column H builds the final URL and combines E/F into `utm_content`:

```text
=IF(A2="","",A2&IF(REGEXMATCH(A2,"\?"),"&","?")&"utm_source="&ENCODEURL(B2)&"&utm_medium="&ENCODEURL(C2)&"&utm_campaign="&ENCODEURL(D2)&"&utm_content="&ENCODEURL(LOWER(E2&"_"&F2))&IF(G2="","","&landing_variant="&ENCODEURL(G2)))
```

Validate every generated link in a private/incognito window before sending:
the intended page loads, all five values remain in the address bar, the form
submits without the parameters being visible in the form, and no personal data
appears in the URL.

## Attribution rules

- **First touch** is the earliest bounded acquisition object recorded for an
  email and never changes. Use it for primary acquisition credit.
- **Last touch** is the most recent bounded acquisition object and may update
  on a later submission. Use it to understand assists.
- A touch contains only source, medium, campaign, content, landing variant, and
  the referrer's hostname. Never store a full referrer path or query.
- A repeated submission updates permitted enrichment and last touch but is not
  a second signup. Filter confirmed signup reporting to `already_joined=false`.
- Missing attribution is `direct_or_unknown`; do not guess a channel from a
  person's email domain or business identity.

## PostHog acquisition dashboard

Create one dashboard named **Free acquisition — Aug 13–Sep 11, 2026**. Exclude
known team traffic and obvious bots, set the reporting timezone to Pacific,
and save these insights:

1. **Primary funnel, unique sessions:** `landing_viewed` →
   `landing_demo_interacted` → `landing_waitlist_started` →
   `landing_waitlist_submitted` → `landing_waitlist_joined` with
   `already_joined=false`. Treat the first demo/calculator interaction per
   session as the calculator step.
2. **Conversion by landing page:** the same funnel broken down by
   `landing_variant` (and path as a QA cross-check).
3. **Conversion by acquisition:** breakdowns for `utm_source`, `utm_medium`, and
   `utm_content`, filtered to `utm_campaign=pilot_aug_2026`.
4. **Conversion by vertical:** confirmed signups broken down by the bounded
   vertical bucket. Before optional enrichment, a coffee/salon/gym landing
   variant supplies the audience bucket; general pages remain “not provided.”
5. **Failure monitor:** trends for `landing_waitlist_validation_failed` and
   `landing_waitlist_submit_failed`; annotate releases and outages.

Use the `utm_content` owner prefix for founder segmentation unless a dedicated
bounded `founder` property exists. Never send names, emails, free-text notes, or
full URLs to PostHog. Analytics and behavior recording must remain off until the
visitor grants analytics consent.

## Metric definitions and formulas

The [`weekly-scorecard-template.csv`](weekly-scorecard-template.csv) separates
manually entered PostHog counts from lead-sheet counts. Percentages use unique
sessions or unique prospects, never raw event totals.

| Metric | Formula |
| --- | --- |
| Outreach link click rate | `tracked_click_sessions / new_prospects_contacted` |
| Calculator interaction rate | `calculator_interaction_sessions / qualified_sessions` |
| Form start rate | `waitlist_form_start_sessions / qualified_sessions` |
| Form completion rate | `valid_waitlist_submissions / waitlist_form_start_sessions` |
| Waitlist conversion rate | `new_confirmed_signups / qualified_sessions` |
| Replies per 100 contacts | `substantive_replies / new_prospects_contacted * 100` |
| Feedback calls per 100 contacts | `feedback_calls_held / new_prospects_contacted * 100` |
| Median elapsed signup response hours | median of `(human_response_at - signup_at) * 24`; use only as an operational clock-hours view |

A substantive reply is `interested`, `not_now`, `not_a_fit`, or
`do_not_contact`; an automated bounce or reaction emoji is not a reply. A
feedback call counts only after it happens, not when booked. A tracked click is
a unique session landing from the sprint campaign, not an email-provider open.

Use these Google Sheets formulas in scorecard row 2, then fill down. Columns
refer to the supplied template:

```text
N2  =IFERROR(G2/E2,0)
O2  =IFERROR(H2/F2,0)
P2  =IFERROR(I2/F2,0)
Q2  =IFERROR(J2/I2,0)
R2  =IFERROR(K2/F2,0)
S2  =IFERROR(L2/E2*100,0)
T2  =IFERROR(M2/E2*100,0)
```

Format N:R as percentages and S:T as numbers with one decimal place. A zero
denominator may remain 0 for rate fields, but response-time formulas must remain
blank until a response sample exists; no sample is not a perfect zero-hour SLA.

## Decisions and thresholds

- **Scale a vertical, channel, or message:** only after at least five new
  confirmed signups **and** at least 5% landing conversion for that segment.
- **Stop a message:** after 100 unique prospects if it has zero substantive
  replies **or** zero qualified tracked-click sessions. Record the stop date;
  do not rewrite history by deleting its rows.
- **Keep learning:** segments below 100 contacts or five signups remain
  inconclusive. Do not call them winners or losers.
- **A/B testing:** change one major landing variable in a week and wait for at
  least 200 unique visitors per variant before treating the comparison as an
  experiment. Before that point, report directional observations only.
- **Response SLA:** target a median of two business hours or less, measured
  manually within 9:00 a.m.–5:00 p.m. PT business windows. The template's
  elapsed-hours column is a triage aid, not the business-hours SLA calculation.
- **Sprint success:** 500 qualified sessions, 25 unique confirmed signups,
  at least 5% conversion, 800 unique first touches, and 10 held feedback calls.

At each Wednesday review, apply the thresholds exactly. The September 11
report should include misses and uncertainty plainly; sample/demo outcomes are
never substituted for observed acquisition data.
