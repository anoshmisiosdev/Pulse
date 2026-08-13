# Payment-data product opportunities

Payment history can do more than label customers “high risk.” The useful product
is a decision system: identify what changed, choose the smallest sensible action,
and measure whether that action caused another profitable visit.

This backlog separates what Churnary can ship from the current customer/payment
model from ideas that require richer provider objects. Research links are primary
documentation or published studies unless explicitly labeled practitioner input.

## Recommended sequence

| Priority | Product | User decision it improves | Data needed | First success metric |
|---|---|---|---|---|
| P1 | Reason-aware retention queue | “What should I do for this customer today?” | Existing visits, payments, failures, refunds | Incremental repeat visits per 100 actions |
| P1 | Personal habit clock | “Are they actually late for *their* cadence?” | Existing transaction timestamps | Precision of 30-day return labels by risk band |
| P1 | Payment recovery desk | “Is this a relationship problem or a recoverable payment failure?” | Failure code, status transitions, later success | Recovered amount / failed amount |
| P1 | Holdouts and outcome attribution | “Did the outreach cause the return?” | Campaign assignment, send, cost, next purchase | Incremental profit versus control |
| P2 | Margin-aware customer value | “Who is worth an incentive, and how much?” | COGS/margin, discounts, refunds, outreach cost | Incremental gross profit, not revenue |
| P2 | Refund rescue workflow | “Which refund needs service recovery?” | Refund reason, items, original order, support event | 60-day repurchase after refund |
| P2 | Next-basket win-back | “What should the message recommend?” | Orders, line items, catalog/category | Incremental basket conversion and margin |
| P2 | Loyalty optimizer | “Do points change behavior or subsidize existing regulars?” | Loyalty enrollment, accrual/redemption, promotion exposure | Incremental frequency versus matched/control group |
| P3 | Location/daypart migration | “Did they churn, or move to another location/time?” | Location, channel, timestamp, unified identity | False-risk reduction; cross-location retention |
| P3 | Discount-dependency guardrail | “Will another coupon create a full-price return?” | Promotion/discount line items and treatment history | Full-price repeat rate; offer cost per incremental visit |

## 1. Split behavioral churn from payment failure

A failed card, a refund, and a customer whose normal visit rhythm stopped should
not receive the same message. Stripe treats automated retries, payment-method
updates, and failed-payment analytics as a distinct revenue-recovery workflow;
its Smart Retries use dynamic timing signals rather than a fixed retry rule.
([Stripe revenue recovery](https://docs.stripe.com/billing/revenue-recovery),
[Smart Retries](https://docs.stripe.com/billing/revenue-recovery/smart-retries))

Churnary should expose one primary reason code and playbook:

- `payment_recovery`: recent unresolved failure → update-payment link/retry;
- `service_recovery`: refund/cancellation → check the experience before offering;
- `cadence_break`: overdue versus personal rhythm → timely reminder;
- `frequency_decline`: visits slowing over several cycles → relationship outreach;
- `new_customer_activation`: first purchase but no expected second visit; and
- `healthy`: suppress outreach.

The first four are partially derivable today. Provider-native failure reasons,
invoice/subscription state, and refund reasons would make them substantially
better.

## 2. Make expected-return timing the product’s “habit clock”

Non-contractual businesses do not receive an explicit cancellation event. A
single global “30 days absent” rule mislabels both daily coffee customers and
quarterly boutique shoppers. Published retail churn work frames this as a
time-to-event problem, and next-basket research explicitly models timestamps and
repeat-purchase intervals.
([Retail churn as survival prediction](https://arxiv.org/abs/2304.00575),
[temporal next-basket modeling](https://jcst.ict.ac.cn/article/doi/10.1007/s11390-019-1972-2))

The current median-gap estimate is a good explainable baseline. The next version
should add interval variability, weekday/daypart preference, seasonality,
customer tenure, and a backtested “returned within N days” calibration report.
Display an expected window and days overdue—not a fake probability when the
model has not been calibrated.

## 3. Optimize actions, not risk scores

High risk does not imply persuadability. Some customers return without help;
some cannot be saved; some can even be annoyed by unnecessary outreach. Uplift
research argues for estimating the incremental effect of an intervention, and
profit-focused churn work combines treatment effect, CLV, and intervention cost.
([uplift versus churn prediction](https://doi.org/10.1016/j.ins.2019.12.075),
[Managing Churn to Maximize Profits](https://www.hbs.edu/ris/Publication%20Files/14-020_2d6c9da0-94d3-4dd5-9952-d81feb432f61.pdf))

Before building an uplift model, Churnary should make randomized holdouts a
first-class automation option. Record eligibility, assignment, exact treatment,
send/delivery, incentive cost, and subsequent purchases. Report incremental
visits, revenue, gross profit, unsubscribes, and refunds versus control. This
creates the training data the advanced model actually needs.

## 4. Rank by recoverable profit

Revenue at risk can over-prioritize high-revenue/low-margin customers and justify
discounts that destroy value. Add business-level default margin plus optional
product/category margins, subtract refunds and incentive/contact cost, and rank
on:

`expected incremental return × expected contribution margin − intervention cost`

This also makes the offer ladder safer: no discount, useful reminder, low-cost
perk, then monetary incentive only when expected incremental profit stays
positive.

## 5. Turn orders into useful message content

Payment objects answer *whether* and *how much*; orders/catalog answer *what*.
Next-basket research finds that future baskets contain both repeated and new
items, so the product should distinguish replenishment from cross-sell instead
of filling a generic recommendation slot.
([next-basket reality check](https://arxiv.org/abs/2109.14233),
[M2 next-basket study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10117693/))

An incremental first version needs no deep model:

1. customer’s most repeated item/category;
2. median repurchase interval for that item;
3. frequently co-purchased items among similar customers;
4. in-stock and positive-margin guardrails; and
5. separate “reorder” and “try next” suggestions.

This requires Stripe invoice/subscription line items and Products/Prices, plus
Square Orders and Catalog—not only Charges/Payments.

## 6. Treat refunds as a service-recovery moment

A refund is not automatically churn, fraud, or a failed card. It is a reason to
ask whether the product, fulfillment, or service failed. Connect a refund to its
original order and items; suppress ordinary win-back automation; route high-value
or repeated-refund cases to a human; then measure repurchase after resolution.
Do not assume a “service recovery paradox”—the safe product claim is that good
recovery can protect satisfaction, while results must be measured locally.

## 7. Measure loyalty incrementally

Square reports that enrolled Loyalty customers spend 53% more and visit 40% more
often in its global 2022 data, and its dashboard compares loyalty and non-loyalty
spend and frequency.
([Square Loyalty](https://squareup.com/us/en/software/loyalty),
[Square loyalty reporting](https://squareup.com/help/us/en/article/6467-view-your-square-loyalty-metrics))
Those are associations, not proof that enrollment caused the entire difference:
the most engaged customers may self-select. Churnary’s opportunity is to combine
loyalty events with holdouts or matched cohorts and answer which reward, tier,
or bonus-point promotion generated incremental visits at acceptable cost.

## Practitioner signals worth testing, not treating as facts

Practitioners repeatedly warn that generic high-frequency email can turn an
otherwise repeat buyer into an unsubscribe, while individualized purchase cycles
and product-relevant post-purchase help feel less like spam. These are qualitative
inputs for experiment design, not benchmarks.
([customer account of over-messaging](https://www.reddit.com/r/TalesFromTheCustomer/comments/nphfdd/reverse_customer_retention_psychology/),
[data-science discussion of intervention experiments](https://www.reddit.com/r/datascience/comments/1k80mxy/question_about_how_to_use_churn_prediction/))

## Public datasets for the next evaluation stages

The checked-in UCI sample is the best immediate retention smoke test because it
has repeat customers, timestamps, products, amounts, and cancellations. Other
public datasets answer different questions and should stay separate rather than
being blended into one artificial “ground truth”:

| Dataset | Best use | Important limitation |
|---|---|---|
| [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail) | Current end-to-end cadence, value, cancellation, and next-item tests | Historical UK non-store retailer; no outreach treatments or payment failures |
| [Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | Orders, payments/installments, delivery, product, seller, and review joins across about 100k orders | CC BY-NC-SA 4.0 and marketplace-specific; evaluate internally before any redistribution/commercial use |
| [Criteo Uplift](https://ailab.criteo.com/ressources/) | Large randomized treatment/control benchmark for uplift and causal targeting | Advertising visits/conversions, not merchant payment history or SMB retention |
| [CDNOW customer transactions](https://brucehardie.com/notes/026/notes_on_CDNOW_master.pdf) | Repeat-purchase/CLV and buy-till-you-die model benchmarking | Older music-retail setting with limited operational context |

Use provider Sandboxes for failure codes, refunds tied to original charges,
webhook ordering, OAuth, and incremental sync. Public flat files cannot validate
those provider contracts.

## Data-contract additions

The next provider expansion should normalize these entities instead of packing
provider JSON into scoring code:

- `orders` and `order_line_items` with quantity, discount, tax, location, channel;
- `products`/`categories` with optional unit cost or margin;
- `subscriptions`/`invoices` and payment-attempt lifecycle;
- `refunds` linked to original transaction/order with reason;
- `loyalty_events` and balances;
- `campaign_eligibility`, randomized assignment, treatment, cost, delivery; and
- `outcomes` linking a later transaction to an evaluation window, not claiming
  causality from last-touch attribution.

Never ingest full card numbers, CVC, raw magnetic-stripe data, or use card
fingerprints for cross-merchant tracking. Keep provider IDs tenant-scoped,
minimize retained webhook payloads, and make source deletion propagate through
derived scores and campaign eligibility.
