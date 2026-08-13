# Manual outreach templates

These templates are starting points, not mail merge. Before sending, replace
every bracketed field, confirm the observation on a public source, and generate
the link using [`utm-and-scorecard.md`](utm-and-scorecard.md). If a message
cannot be genuinely personalized in two minutes, do not send it.

## Required fields

- `[first_name]`: a public owner/operator name; use “Hi there” rather than
  guessing.
- `[business]`: public business name.
- `[observation]`: one specific, neutral fact such as a weekly class, online
  booking flow, loyalty offer, or menu item.
- `[tracked_calculator_link]`: calculator route with the sender, channel,
  campaign, message variant, and landing variant encoded.
- `[tracked_early_access_link]`: relevant vertical page or homepage, generated
  with the same attribution grammar.
- `[founder]`: the actual sender.

Never insert estimated revenue, an assumed churn problem, a fake customer
example, or a claim that another owner got a particular result.

## Vertical copy blocks

Use the block matching the current weekly cohort.

| Vertical | Problem line for touch 1 | Transparent example for touch 2 | Call question for touch 3 |
| --- | --- | --- | --- |
| Café / coffee shop | “A regular’s normal cadence can change well before a generic 30-day inactive list notices.” | “Sample logic only: someone moving from a five-day visit rhythm to nine days may deserve attention sooner than someone who normally visits monthly.” | “Could your existing Square, Stripe, or CSV history make a signal like that useful?” |
| Salon / barbershop | “Booking gaps are different for every client and service, so one blanket inactive window can miss the people who are actually drifting.” | “Sample logic only: an eight-week gap means something different for a client who normally returns every four weeks than for one who books seasonally.” | “Would a cadence-based flag be useful before the next expected booking passes?” |
| Gym / fitness studio | “A member’s payment or visit rhythm can soften before a cancellation, but the useful signal depends on that member’s own pattern.” | “Sample logic only: a steady weekly routine fading over several weeks is a different signal from a member whose pattern was always occasional.” | “Would an explainable early flag help if every message still required your approval?” |
| Week-four mixed validation | Use the line for the prospect’s actual vertical. | Use the example for the prospect’s actual vertical. | Use the question for the prospect’s actual vertical. |

## Email: three touches

Use `utm_source=email` and `utm_medium=founder_dm`.

**Email is not launch-ready until Churnary supplies a valid physical postal
address.** CAN-SPAM applies to one-to-one and B2B commercial email. Before any
founder uses this channel, replace `[churnary_postal_address]` below with
Churnary's real street address, registered U.S. Postal Service P.O. box, or
registered commercial mailbox. Every message must use truthful sender/routing
information, an accurate subject, the commercial-message disclosure, the
postal address, and the opt-out line. Do not invent an address or delete the
footer. See the [FTC CAN-SPAM compliance guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business).

Append this footer to **all three** email touches:

> Commercial message from Churnary. Churnary · [churnary_postal_address]
>
> To stop all marketing email from Churnary, reply “unsubscribe.” We will honor
> that request promptly and will not send another outreach message.

### Touch 1 — day 0

Subject: `Quick question about regulars at [business]`

> Hi [first_name] — I noticed [observation]. [Problem line for touch 1]
>
> I’m one of the founders of Churnary. We’re building a tool that looks at a
> local business’s existing customer rhythm, explains who may be drifting, and
> drafts a win-back note for the owner to approve. We made a small sample
> calculator here: [tracked_calculator_link]
>
> Is that problem recognizable at [business], or am I off base?
>
> — [founder]
>
> If this is not relevant, reply “no” and I will not follow up.
>
> [required commercial-message footer]

### Touch 2 — day 3

Reply in the same thread. Do not add a new subject.

> One concrete example, [first_name]: [Transparent example for touch 2]
>
> That is the kind of change Churnary is designed to explain. It is sample
> logic, not a customer result, and nothing sends without a person approving
> it. If useful, the calculator is still here: [tracked_calculator_link]
>
> [required commercial-message footer]

### Touch 3 — day 7

> Last note from me, [first_name]. [Call question for touch 3]
>
> If yes, you can get early access here: [tracked_early_access_link]. I would
> also value 15 minutes of candid feedback; a simple “call” reply is enough.
> If I do not hear back, I will close the loop.
>
> [required commercial-message footer]

## LinkedIn DM: three touches

Use `utm_source=linkedin` and `utm_medium=founder_dm`. Do not send a blank
connection request followed by a pitch. Send the sequence only when messaging
is available and the recipient is clearly connected to the business.

### Touch 1 — day 0

> Hi [first_name] — noticed [observation] at [business]. [Problem line for touch
> 1] I’m building Churnary to flag that change, explain it, and leave every
> win-back message for the owner to approve. Sample calculator:
> [tracked_calculator_link]. Does this feel relevant to your day-to-day?

### Touch 2 — day 3

> A quick example of what I mean: [Transparent example for touch 2] This is
> demo logic, not a claimed customer result. Happy to send a screenshot if that
> would be more useful than another pitch.

### Touch 3 — day 7

> Closing the loop: [Call question for touch 3] If so, early access is here:
> [tracked_early_access_link], or reply “call” for a 15-minute feedback chat. No
> worries if not—I will not keep nudging.

## Instagram DM: three touches

Use `utm_source=instagram` and `utm_medium=founder_dm`. Contact a public
business account, not a private personal account.

### Touch 1 — day 0

> Hi! I liked [observation] from [business]. [Problem line for touch 1] I’m a
> founder of Churnary, an early tool that flags that shift and drafts a note the
> owner chooses whether to send. Here is a sample calculator if useful:
> [tracked_calculator_link]

### Touch 2 — day 3

> One example so this is less abstract: [Transparent example for touch 2] It is
> sample logic only—not a result we are claiming. Would a simple screenshot of
> the owner view be useful?

### Touch 3 — day 7

> Last message from me: [Call question for touch 3] If yes, here is early
> access: [tracked_early_access_link], or reply “call” for a short feedback chat.
> If not, I will close the loop.

## Community participation: three steps

Use `utm_source=community`, `utm_medium=community`, and the community slug in
`utm_content`; never put a member name in the URL. These are three levels of
participation in a community, **not** three unsolicited messages to one person.

1. **Contribute without a link.** Answer the actual question using the relevant
   transparent example. State that you are building Churnary if product context
   is relevant.
2. **Share only after permission or a direct request.** “I made a free sample
   calculator for this exact cadence question. The moderators allow resources
   here, so I can share it: [tracked_calculator_link]. It does not require
   customer data.”
3. **Invite feedback only in an allowed promotion thread.** “I’m looking for
   [café / salon / gym] owners willing to challenge an early retention workflow.
   It flags a change, explains why, and keeps outreach human-approved. Early
   access: [tracked_early_access_link]. Demo examples are labeled; we are not
   claiming customer outcomes yet.”

If rules prohibit promotion, stop after step 1 and record no outbound link.

## Reply handling

| Reply | Send | Tracker action |
| --- | --- | --- |
| Interested | “Thanks—what system holds your customer or payment history today, and would you prefer early access or a 15-minute feedback call?” | `response_status=interested`; set the requested next action. |
| Not now | “Understood. I’ll close the loop for this sprint. Thanks for the direct answer.” | `response_status=not_now`; no further touches. |
| Not a fit | “Thanks for letting me know. I won’t keep following up.” | `response_status=not_a_fit`; no further touches. |
| Stop / unsubscribe | “Understood—you will not receive another outreach message from us.” | `response_status=do_not_contact`; set `do_not_contact=TRUE`; clear future actions. |
| Asks for evidence | “We do not have a publishable customer outcome yet. What I can show is a labeled demo and the exact workflow we want pilots to test.” | Answer truthfully; never substitute sample results for proof. |
| Asks about data or automation | “Churnary can work from connected Square/Stripe history or a CSV. It proposes outreach; a person approves it. I can share our privacy page before you submit anything.” | Link the public privacy page if requested. |

Do not keep a prospect in a sequence after any substantive reply. Continue as a
human conversation owned by the assigned founder.
