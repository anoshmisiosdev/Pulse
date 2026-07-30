import { useEffect } from "react";
import { Link } from "react-router-dom";
import ChurnaryMark from "../components/ChurnaryMark";
import { openPrivacyChoices } from "../lib/privacyPreferences";

const EFFECTIVE_DATE = "July 30, 2026";
const PRIVACY_EMAIL = "privacy@churnary.com";

const SECTIONS = [
  ["scope", "Scope and our role"],
  ["information", "Information we collect"],
  ["use", "How we use information"],
  ["ai", "AI and automated analysis"],
  ["sharing", "How we disclose information"],
  ["tracking", "Cookies and analytics"],
  ["retention", "Retention"],
  ["rights", "Your choices and rights"],
  ["security", "Security and transfers"],
  ["children", "Children"],
  ["changes", "Changes and contact"],
] as const;

function PolicySection({
  id,
  number,
  title,
  children,
}: {
  id: string;
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="privacy-section" id={id}>
      <div className="privacy-section-heading">
        <span>{String(number).padStart(2, "0")}</span>
        <h2>{title}</h2>
      </div>
      <div className="privacy-section-copy">{children}</div>
    </section>
  );
}

export default function Privacy() {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Privacy Policy — Churnary";
    const hashTarget = window.location.hash
      ? document.querySelector(window.location.hash)
      : null;
    if (hashTarget) {
      hashTarget.scrollIntoView();
    } else {
      window.scrollTo({ top: 0, behavior: "auto" });
    }
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <div className="privacy-page">
      <style>{PRIVACY_CSS}</style>

      <header className="privacy-header">
        <Link to="/" className="privacy-brand" aria-label="Churnary home">
          <ChurnaryMark size={30} />
          <span className="font-display">Churnary</span>
        </Link>
        <Link to="/" className="privacy-back">
          Back to Churnary <span aria-hidden>↗</span>
        </Link>
      </header>

      <main>
        <div className="privacy-hero">
          <p className="privacy-kicker">Legal · Privacy</p>
          <h1 className="font-display">Privacy, in plain language.</h1>
          <p className="privacy-deck">
            This policy explains what Churnary collects, why we use it, and the choices available
            to website visitors, waitlist members, account users, and people whose information a
            business processes through Churnary.
          </p>
          <div className="privacy-date">
            <span>Effective</span>
            <strong>{EFFECTIVE_DATE}</strong>
          </div>
        </div>

        <div className="privacy-summary" aria-label="Privacy highlights">
          <article>
            <span className="privacy-summary-number">01</span>
            <h2 className="font-display">We do not sell information for money.</h2>
            <p>
              Optional visitor identification may be treated as a “sale” or “sharing” under some
              U.S. state laws. It stays off until permission is given, and you can opt out.
            </p>
          </article>
          <article>
            <span className="privacy-summary-number">02</span>
            <h2 className="font-display">Businesses control their customer data.</h2>
            <p>
              When a business imports customer records, Churnary processes them to provide the
              service and on that business&apos;s instructions.
            </p>
          </article>
          <article>
            <span className="privacy-summary-number">03</span>
            <h2 className="font-display">You control optional measurement.</h2>
            <p>
              Marketing analytics and visitor identification load only after you allow them. We
              honor Global Privacy Control and keep essential site functions available either way.
            </p>
          </article>
        </div>

        <div className="privacy-layout">
          <aside className="privacy-aside">
            <nav aria-label="Privacy policy contents">
              <p>On this page</p>
              <ol>
                {SECTIONS.map(([id, label], index) => (
                  <li key={id}>
                    <a href={`#${id}`}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      {label}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          <article className="privacy-policy">
            <div className="privacy-intro">
              <p>
                Churnary (&quot;Churnary,&quot; &quot;we,&quot; &quot;us,&quot; or
                &quot;our&quot;) provides customer-retention software for local businesses. This
                Privacy Policy applies to our website, application, waitlist, and related services
                (collectively, the &quot;Services&quot;).
              </p>
              <p>
                By using the Services, you acknowledge the practices described here. If you use
                Churnary for a business or organization, you represent that you are authorized to
                provide information to us and to instruct us to process it.
              </p>
            </div>

            <PolicySection id="scope" number={1} title="Scope and our role">
              <h3>Information Churnary controls</h3>
              <p>
                Churnary determines how and why we process information about our website visitors,
                waitlist members, account holders, billing contacts, and people who communicate
                directly with us.
              </p>

              <h3>Information a Churnary customer controls</h3>
              <p>
                Businesses may connect a point-of-sale, payment, booking, marketing, or social
                service, or upload customer records to Churnary. For that information, the business
                is the controller or &quot;business&quot; and Churnary acts as its processor or
                service provider. The business decides what is imported, why it is used, how long
                it is kept, and whether outreach is sent.
              </p>
              <p>
                If you are a customer of a business that uses Churnary and want to exercise a
                privacy right regarding information that business holds about you, contact the
                business first. We will support verified requests from our business customers as
                required by law and our agreements.
              </p>
            </PolicySection>

            <PolicySection id="information" number={2} title="Information we collect">
              <div className="privacy-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Examples</th>
                      <th>How we receive it</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Account and contact information</td>
                      <td>
                        Name, work email, business name, role, account identifier, and support
                        communications. Authentication credentials are handled by our
                        authentication provider; we do not receive your plain-text password.
                      </td>
                      <td>Directly from you or your identity provider.</td>
                    </tr>
                    <tr>
                      <td>Waitlist information</td>
                      <td>
                        Name, email address, business name, business type, and any note you choose
                        to provide.
                      </td>
                      <td>Directly from the waitlist form.</td>
                    </tr>
                    <tr>
                      <td>Business and connected-service information</td>
                      <td>
                        Business profile, location, products, brand settings, connected account
                        identifiers, encrypted access tokens, and integration status.
                      </td>
                      <td>From you and services you authorize Churnary to connect to.</td>
                    </tr>
                    <tr>
                      <td>Customer and transaction records</td>
                      <td>
                        Customer names and contact details, purchases, visit dates, spend, loyalty
                        or consent status, and campaign engagement. We ask customers not to upload
                        medical, treatment, or other unnecessary sensitive information.
                      </td>
                      <td>From business users, CSV uploads, and authorized integrations.</td>
                    </tr>
                    <tr>
                      <td>Service content</td>
                      <td>
                        Business knowledge, campaign instructions, generated messages, social
                        content, approvals, responses, and support requests.
                      </td>
                      <td>From users and from outputs generated at their request.</td>
                    </tr>
                    <tr>
                      <td>Payment and subscription information</td>
                      <td>
                        Plan, subscription status, billing contact, and transaction identifiers.
                        Payment processors handle complete card details.
                      </td>
                      <td>From you and our payment processor.</td>
                    </tr>
                    <tr>
                      <td>Website, product, and device activity</td>
                      <td>
                        Pseudonymous browser ID, pages and features used, clicks, timestamps,
                        referring hostname, campaign parameters, browser/device data, IP address,
                        approximate location derived from IP, and security logs.
                      </td>
                      <td>Automatically from your browser, device, and our service providers.</td>
                    </tr>
                    <tr>
                      <td>Business visitor identity information</td>
                      <td>
                        When optional visitor identification is enabled and a match is available:
                        name, professional profile URL, job title, business email, employer,
                        company website, industry, company size, estimated company revenue,
                        approximate business location, referring page, and page visited.
                      </td>
                      <td>
                        From a visitor-identification provider after you allow optional analytics.
                      </td>
                    </tr>
                    <tr>
                      <td>Inferences and recommendations</td>
                      <td>
                        Churn risk indicators, customer segments, recommended next actions, content
                        suggestions, and account-level engagement signals.
                      </td>
                      <td>Generated from information processed through the Services.</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <h3>Information from public and third-party sources</h3>
              <p>
                Some features research publicly available business information, such as local
                competitor offerings and pricing. We may also receive information from
                integrations you choose, identity providers, payment processors, and
                communications providers.
              </p>
            </PolicySection>

            <PolicySection id="use" number={3} title="How we use information">
              <p>We use information to:</p>
              <ul>
                <li>provide, operate, personalize, and improve the Services;</li>
                <li>authenticate users, maintain accounts, and secure connected services;</li>
                <li>
                  import and organize business records, calculate retention insights, and generate
                  requested recommendations or content;
                </li>
                <li>
                  send emails, text messages, or social content when an authorized business user
                  requests or configures that action;
                </li>
                <li>process waitlist requests, subscriptions, and customer support;</li>
                <li>
                  understand product and marketing performance, diagnose errors, and prevent fraud
                  or abuse;
                </li>
                <li>comply with law, enforce agreements, and protect users and the public; and</li>
                <li>
                  create aggregated or de-identified statistics that are not reasonably linkable to
                  a person.
                </li>
              </ul>

              <h3>Legal bases for EEA, UK, and similar jurisdictions</h3>
              <p>
                Where a legal basis is required, we rely on performance of a contract, our
                legitimate interests in operating and securing the Services, consent when the law
                requires it, and compliance with legal obligations. You may withdraw consent at any
                time, without affecting processing already completed.
              </p>
            </PolicySection>

            <PolicySection id="ai" number={4} title="AI and automated analysis">
              <p>
                Churnary uses automated systems and AI providers to estimate customer retention
                risk, summarize business activity, research market information, and draft
                recommendations or communications. Depending on the feature and configuration,
                relevant inputs may be sent to model, search, or embedding providers acting on our
                behalf.
              </p>
              <p>
                These outputs are recommendations for business users. Churnary does not intend them
                to make decisions that produce legal or similarly significant effects about a
                person. Business users should review outputs for accuracy, appropriateness, and
                compliance before acting on them.
              </p>
              <div className="privacy-callout">
                <strong>Data minimization matters.</strong>
                <span>
                  Do not upload health, treatment, government ID, financial-account credentials, or
                  other sensitive information that Churnary does not need to provide the requested
                  service.
                </span>
              </div>
            </PolicySection>

            <PolicySection id="sharing" number={5} title="How we disclose information">
              <p>We may disclose information to the following recipients:</p>
              <ul>
                <li>
                  <strong>Service providers.</strong> Hosting, database, authentication, analytics,
                  security, model, search, communications, storage, billing, visitor
                  identification, and support providers process information for us. Depending on
                  the features enabled, examples include Supabase, Vercel, Render, PostHog,
                  RB2B/Retention.com, AI/model-routing providers, AWS, Perplexity, Google, Resend,
                  Twilio, Stripe, Square, and Buffer.
                </li>
                <li>
                  <strong>Services you connect.</strong> We exchange information with a platform
                  when you direct us to connect, import, publish, send, or synchronize data with
                  that platform.
                </li>
                <li>
                  <strong>Your organization.</strong> Account owners and authorized teammates may
                  access information associated with their business workspace.
                </li>
                <li>
                  <strong>Legal and safety recipients.</strong> We may disclose information when we
                  reasonably believe it is necessary to comply with law, respond to lawful process,
                  investigate abuse, or protect rights, safety, and security.
                </li>
                <li>
                  <strong>Business transactions.</strong> Information may be reviewed or
                  transferred in connection with financing, due diligence, a merger, acquisition,
                  reorganization, or sale of assets, subject to appropriate safeguards.
                </li>
                <li>
                  <strong>At your direction.</strong> We may disclose information when you ask us
                  to or give consent.
                </li>
              </ul>

              <h3>Sale, sharing, and targeted advertising disclosures</h3>
              <p>
                Churnary does not sell personal information for money and does not offer financial
                incentives for personal information. If we enable RB2B/Retention.com after a
                visitor allows optional analytics, our site may disclose identifiers, device or
                network signals, and website activity so the provider can attempt to return a
                professional or company match. California and other U.S. state laws may define
                that disclosure as a &quot;sale,&quot; &quot;sharing,&quot; or targeted advertising
                even when no money is exchanged.
              </p>
              <p>
                You can opt out at any time through{" "}
                <button
                  type="button"
                  className="privacy-inline-button"
                  onClick={openPrivacyChoices}
                >
                  Privacy choices
                </button>
                , by enabling a supported Global Privacy Control signal, or through
                RB2B/Retention.com&apos;s{" "}
                <a href="https://app.retention.com/optout" target="_blank" rel="noreferrer">
                  provider opt-out page
                </a>
                . Optional visitor identification will not load when your Churnary preference is
                set to Essential only or while a supported Global Privacy Control signal is active.
              </p>
            </PolicySection>

            <PolicySection id="tracking" number={6} title="Cookies, local storage, and analytics">
              <p>
                Churnary uses browser storage and similar technologies for authentication,
                security, and your privacy preferences. The signed-in service also records limited
                server-side operational events—such as connecting a data source, generating a
                campaign, or approving an action—against an account identifier so we can provide,
                secure, and improve the service. Essential only does not disable account,
                transaction, or security records needed to operate Churnary.
              </p>
              <p>
                If you select Allow analytics, the public website assigns a random, pseudonymous
                browser identifier and a session identifier so meaningful marketing actions can be
                understood across visits. We send limited event details—such as page, referring
                hostname, campaign parameters, and interactions—to PostHog through our server, and
                we retain a minimized first-party event history for Churnary&apos;s platform
                administrators.
              </p>
              <p>
                Waitlist names, email addresses, and free-form form contents are stored with the
                waitlist record and are not sent to PostHog. If analytics were allowed, we may
                connect earlier pseudonymous activity to an opaque waitlist record or signed-in
                account. Churnary&apos;s own administrator view may display the contact
                information you submitted next to that first-party history.
              </p>
              <p>
                If configured, RB2B/Retention.com loads only after you select Allow analytics and
                only on our public marketing page. The provider may use first-party cookies,
                device or network identifiers, IP-derived location, referring information, and
                other matching signals to recognize repeat visits and attempt a professional or
                company match. Person-level matching is limited by the provider to eligible U.S.
                traffic. A returned match can include the professional and company fields
                described above; not every visitor is identified.
              </p>
              <p>
                Select{" "}
                <button
                  type="button"
                  className="privacy-inline-button"
                  onClick={openPrivacyChoices}
                >
                  Privacy choices
                </button>{" "}
                to change your setting. Choosing Essential only removes Churnary&apos;s optional
                browser and session IDs and attempts to remove known RB2B cookies from this site.
                You can also clear or block browser storage in your browser. Blocking essential
                storage may prevent authentication or preferences from working.
              </p>
            </PolicySection>

            <PolicySection id="retention" number={7} title="How long we keep information">
              <p>
                We retain each category only as long as reasonably necessary for the purpose for
                which it was collected. The criteria we use include:
              </p>
              <dl className="privacy-retention">
                <div>
                  <dt>Waitlist and direct communications</dt>
                  <dd>
                    While your request remains relevant, until you ask us to delete it, and for a
                    limited period afterward for suppression, security, or legal records.
                  </dd>
                </div>
                <div>
                  <dt>Account and business information</dt>
                  <dd>
                    While the account is active and for the period reasonably needed to close the
                    account, provide exports, resolve disputes, and meet legal obligations.
                  </dd>
                </div>
                <div>
                  <dt>Business customer data</dt>
                  <dd>
                    According to the business customer&apos;s instructions, account lifecycle, and
                    applicable agreement, subject to backup and legal-retention requirements.
                  </dd>
                </div>
                <div>
                  <dt>Analytics and security data</dt>
                  <dd>
                    For the period configured with our providers and reasonably needed to measure
                    performance, maintain security, investigate abuse, and preserve service
                    reliability.
                  </dd>
                </div>
                <div>
                  <dt>Marketing visitor profiles</dt>
                  <dd>
                    While reasonably useful to evaluate interest and follow up on an expressed
                    request, then deleted, de-identified, or suppressed. A one-way identifier hash
                    may remain after suppression so later provider data does not recreate the
                    erased profile.
                  </dd>
                </div>
                <div>
                  <dt>Billing and compliance records</dt>
                  <dd>
                    For the periods required by tax, accounting, communications, and other
                    applicable laws.
                  </dd>
                </div>
              </dl>
              <p>
                We may retain information longer when required by law, subject to a legal hold, or
                needed to establish or defend legal claims. We may retain aggregated or
                de-identified information where it cannot reasonably be linked back to a person.
              </p>
            </PolicySection>

            <PolicySection id="rights" number={8} title="Your choices and privacy rights">
              <p>
                Depending on where you live and subject to legal exceptions, you may have the right
                to request access to, correction of, deletion of, or a portable copy of your
                personal information; to restrict or object to certain processing; to withdraw
                consent; and to appeal a denied request. You may also have the right to opt out of
                sale, sharing, targeted advertising, or qualifying profiling. Use Privacy choices
                or a supported Global Privacy Control signal to opt out of optional analytics and
                visitor identification. A Global Privacy Control signal takes precedence while it
                remains active.
              </p>

              <h3>How to exercise a right</h3>
              <p>
                Email{" "}
                <a href={`mailto:${PRIVACY_EMAIL}?subject=Privacy%20request`}>
                  {PRIVACY_EMAIL}
                </a>{" "}
                with the subject &quot;Privacy request&quot; and describe your request. We may need
                to verify your identity and authority before completing it. Authorized agents may
                submit requests where permitted by law. We will not discriminate against you for
                exercising a privacy right.
              </p>

              <h3>Communication choices</h3>
              <ul>
                <li>
                  Open{" "}
                  <button
                    type="button"
                    className="privacy-inline-button"
                    onClick={openPrivacyChoices}
                  >
                    Privacy choices
                  </button>{" "}
                  to allow or disable optional analytics and visitor identification.
                </li>
                <li>
                  Use the unsubscribe link in a marketing email or reply to ask us to stop
                  non-transactional email.
                </li>
                <li>Reply STOP to an automated marketing text message.</li>
                <li>
                  Account owners can disconnect integrations or ask us to close an account and
                  delete associated information, subject to legal exceptions.
                </li>
              </ul>

              <h3>California disclosures</h3>
              <p>
                In the preceding 12 months, Churnary may have collected the categories described
                above, including identifiers, customer-record information, commercial information,
                internet or electronic-network activity, approximate geolocation, professional
                information, account login information, and inferences. We collect and disclose
                these categories for the business purposes described in this policy. We do not use
                sensitive personal information to infer characteristics about people.
              </p>
              <p>
                For purposes of California law, the categories Churnary may sell or share after
                optional analytics permission are identifiers, internet or electronic-network
                activity, approximate geolocation, and professional or employment information. The
                recipient category is a visitor-identification or advertising partner, and the
                purpose is to attempt a business identity match and measure interest in Churnary.
                We do not knowingly sell or share personal information about people under 16.
              </p>
            </PolicySection>

            <PolicySection id="security" number={9} title="Security and international transfers">
              <p>
                We use administrative, technical, and organizational safeguards designed to
                protect information, including access controls, tenant separation, encryption in
                transit, encryption of connected-service credentials at rest, server-side secret
                handling, and monitoring. No security measure is perfect, so we cannot guarantee
                absolute security.
              </p>
              <p>
                Churnary and many of our providers operate in the United States. If information is
                transferred from another country, we use safeguards required by applicable law.
                Those locations may have data-protection laws different from the laws where you
                live.
              </p>
            </PolicySection>

            <PolicySection id="children" number={10} title="Children">
              <p>
                The Services are designed for businesses and are not directed to children under
                13. We do not knowingly collect personal information directly from children under
                13. If you believe a child has provided personal information to us, contact us so
                we can review and delete it as appropriate.
              </p>
            </PolicySection>

            <PolicySection id="changes" number={11} title="Changes and contact">
              <p>
                We may update this policy as Churnary changes. We will post the revised version here
                and update the effective date. If a change materially affects how we use
                information, we will provide additional notice when required.
              </p>
              <div className="privacy-contact">
                <span>Privacy questions or requests</span>
                <a href={`mailto:${PRIVACY_EMAIL}`}>{PRIVACY_EMAIL}</a>
                <small>Churnary · Fremont, California, United States</small>
              </div>
            </PolicySection>
          </article>
        </div>
      </main>

      <footer className="privacy-footer">
        <div className="privacy-brand">
          <ChurnaryMark size={22} />
          <span className="font-display">Churnary</span>
        </div>
        <span>© 2026 Churnary</span>
        <button
          type="button"
          className="privacy-footer-button"
          onClick={openPrivacyChoices}
        >
          Privacy choices
        </button>
        <Link to="/">Home</Link>
      </footer>
    </div>
  );
}

const PRIVACY_CSS = `
  html { scroll-behavior: smooth; }
  .privacy-page {
    min-height: 100vh;
    overflow-x: clip;
    color: var(--ink);
    background:
      radial-gradient(880px 440px at 82% -5%, rgba(255,253,247,.9), transparent 70%),
      var(--bg-page);
  }
  .privacy-inline-button, .privacy-footer-button {
    border: 0;
    padding: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
  }
  .privacy-inline-button:hover, .privacy-footer-button:hover { color: var(--accent-dark); }
  .privacy-header {
    position: sticky;
    z-index: 20;
    top: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 68px;
    padding: 0 clamp(20px,5.4vw,108px);
    border-bottom: 1px solid rgba(218,221,204,.8);
    background: rgba(240,231,216,.88);
    backdrop-filter: blur(16px);
  }
  .privacy-brand {
    display: inline-flex;
    align-items: center;
    gap: 9px;
    color: var(--ink) !important;
    font-size: 20px;
    font-weight: 700;
    text-decoration: none;
  }
  .privacy-back {
    color: var(--muted) !important;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .04em;
    text-decoration: none;
  }
  .privacy-back:hover { color: var(--accent) !important; }
  .privacy-hero {
    position: relative;
    padding: clamp(70px,9vw,150px) clamp(20px,8vw,160px) clamp(55px,7vw,105px);
    border-bottom: 1px solid var(--border);
  }
  .privacy-kicker {
    margin: 0 0 22px;
    color: var(--accent);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .18em;
    text-transform: uppercase;
  }
  .privacy-hero h1 {
    max-width: 950px;
    margin: 0;
    color: var(--ink-strong);
    font-size: clamp(48px,7vw,112px);
    font-weight: 600;
    letter-spacing: -.055em;
    line-height: .93;
  }
  .privacy-deck {
    max-width: 720px;
    margin: 34px 0 0;
    color: var(--muted);
    font-size: clamp(17px,1.55vw,23px);
    line-height: 1.55;
  }
  .privacy-date {
    position: absolute;
    right: clamp(20px,5.4vw,108px);
    bottom: 35px;
    display: grid;
    justify-items: end;
    gap: 3px;
    color: var(--muted);
    font-size: 11px;
    letter-spacing: .05em;
    text-transform: uppercase;
  }
  .privacy-date strong {
    color: var(--ink-strong);
    font-size: 12px;
  }
  .privacy-summary {
    display: grid;
    grid-template-columns: repeat(3,minmax(0,1fr));
    border-bottom: 1px solid var(--border);
  }
  .privacy-summary article {
    min-height: 250px;
    padding: clamp(28px,3.7vw,62px);
  }
  .privacy-summary article + article { border-left: 1px solid var(--border); }
  .privacy-summary-number {
    color: var(--accent);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .12em;
  }
  .privacy-summary h2 {
    max-width: 400px;
    margin: 28px 0 14px;
    color: var(--ink-strong);
    font-size: clamp(22px,2.1vw,34px);
    font-weight: 600;
    letter-spacing: -.025em;
    line-height: 1.1;
  }
  .privacy-summary p {
    max-width: 430px;
    margin: 0;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.65;
  }
  .privacy-layout {
    display: grid;
    grid-template-columns: minmax(220px,25vw) minmax(0,1fr);
    min-width: 0;
  }
  .privacy-aside {
    padding: 72px clamp(24px,3.8vw,66px);
    border-right: 1px solid var(--border);
  }
  .privacy-aside nav {
    position: sticky;
    top: 110px;
  }
  .privacy-aside nav > p {
    margin: 0 0 20px;
    color: var(--muted-2);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .16em;
    text-transform: uppercase;
  }
  .privacy-aside ol {
    display: grid;
    gap: 3px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .privacy-aside a {
    display: grid;
    grid-template-columns: 25px 1fr;
    gap: 7px;
    padding: 7px 0;
    color: var(--muted) !important;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.35;
    text-decoration: none;
  }
  .privacy-aside a span {
    color: var(--muted-2);
    font-size: 9px;
    letter-spacing: .08em;
  }
  .privacy-aside a:hover { color: var(--accent) !important; }
  .privacy-policy {
    width: min(100%,960px);
    min-width: 0;
    padding: 72px clamp(24px,6vw,100px) 120px;
  }
  .privacy-intro {
    padding: 0 0 60px;
    color: var(--ink-strong);
    font-family: var(--font-display);
    font-size: clamp(20px,2vw,28px);
    line-height: 1.5;
  }
  .privacy-intro p { margin: 0 0 20px; }
  .privacy-section {
    scroll-margin-top: 95px;
    min-width: 0;
    padding: 65px 0;
    border-top: 1px solid var(--border);
  }
  .privacy-section-heading {
    display: grid;
    grid-template-columns: 40px 1fr;
    align-items: start;
    gap: 12px;
    margin-bottom: 34px;
  }
  .privacy-section-heading > span {
    padding-top: 9px;
    color: var(--accent);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .1em;
  }
  .privacy-section-heading h2 {
    margin: 0;
    color: var(--ink-strong);
    font-size: clamp(30px,3vw,46px);
    font-weight: 600;
    letter-spacing: -.035em;
    line-height: 1.05;
  }
  .privacy-section-copy {
    min-width: 0;
    padding-left: 52px;
    color: #665548;
    font-size: 15px;
    line-height: 1.78;
  }
  .privacy-section-copy p { margin: 0 0 20px; }
  .privacy-section-copy h3 {
    margin: 36px 0 10px;
    color: var(--ink-strong);
    font-family: var(--font-body);
    font-size: 15px;
    font-weight: 800;
    letter-spacing: -.01em;
  }
  .privacy-section-copy ul {
    display: grid;
    gap: 10px;
    margin: 18px 0 24px;
    padding-left: 22px;
  }
  .privacy-section-copy li::marker { color: var(--accent); }
  .privacy-section-copy a {
    color: var(--accent-dark);
    font-weight: 700;
    text-underline-offset: 3px;
  }
  .privacy-table-wrap {
    overflow-x: auto;
    max-width: 100%;
    margin: 0 0 28px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: rgba(251,246,238,.75);
  }
  .privacy-table-wrap table {
    width: 100%;
    min-width: 700px;
    border-collapse: collapse;
    font-size: 12px;
    line-height: 1.55;
  }
  .privacy-table-wrap th,
  .privacy-table-wrap td {
    padding: 15px 16px;
    border-right: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
  }
  .privacy-table-wrap th:last-child,
  .privacy-table-wrap td:last-child { border-right: 0; }
  .privacy-table-wrap tbody tr:last-child td { border-bottom: 0; }
  .privacy-table-wrap th {
    color: var(--muted);
    background: var(--surface-2);
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .1em;
    text-transform: uppercase;
  }
  .privacy-table-wrap td:first-child {
    width: 23%;
    color: var(--ink-strong);
    font-weight: 800;
  }
  .privacy-callout {
    display: grid;
    gap: 7px;
    margin: 32px 0 6px;
    padding: 24px 26px;
    border-left: 3px solid var(--accent);
    color: var(--muted);
    background: var(--surface-2);
  }
  .privacy-callout strong { color: var(--ink-strong); }
  .privacy-retention {
    display: grid;
    margin: 28px 0;
    border-top: 1px solid var(--border);
  }
  .privacy-retention > div {
    display: grid;
    grid-template-columns: minmax(150px,.8fr) minmax(0,1.6fr);
    gap: 24px;
    padding: 18px 0;
    border-bottom: 1px solid var(--border);
  }
  .privacy-retention dt {
    color: var(--ink-strong);
    font-size: 12px;
    font-weight: 800;
  }
  .privacy-retention dd { margin: 0; }
  .privacy-contact {
    display: grid;
    gap: 7px;
    margin-top: 32px;
    padding: 28px;
    color: var(--cream-text);
    background: #33241B;
  }
  .privacy-contact > span {
    color: var(--on-espresso-accent);
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .14em;
    text-transform: uppercase;
  }
  .privacy-contact a {
    color: #FFF5E9 !important;
    font-family: var(--font-display);
    font-size: clamp(24px,3vw,38px);
    font-weight: 600;
    line-height: 1.15;
    text-decoration: none;
  }
  .privacy-contact small { color: #BBAA9D; }
  .privacy-footer {
    display: flex;
    align-items: center;
    gap: 28px;
    min-height: 95px;
    padding: 0 clamp(20px,5.4vw,108px);
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 11px;
  }
  .privacy-footer .privacy-brand { margin-right: auto; font-size: 16px; }
  .privacy-footer a {
    color: var(--muted) !important;
    font-weight: 700;
    text-decoration: none;
  }
  .privacy-footer a:hover { color: var(--accent) !important; }
  @media (max-width: 900px) {
    .privacy-date { position: static; justify-items: start; margin-top: 35px; }
    .privacy-summary { grid-template-columns: 1fr; }
    .privacy-summary article { min-height: 0; }
    .privacy-summary article + article { border-top: 1px solid var(--border); border-left: 0; }
    .privacy-layout { grid-template-columns: 1fr; }
    .privacy-aside { display: none; }
    .privacy-policy { box-sizing: border-box; width: 100%; padding-top: 60px; }
  }
  @media (max-width: 620px) {
    .privacy-header { min-height: 60px; }
    .privacy-brand { font-size: 17px; }
    .privacy-back span { display: none; }
    .privacy-hero { padding-top: 62px; }
    .privacy-section-heading { grid-template-columns: 30px 1fr; }
    .privacy-section-copy { padding-left: 0; }
    .privacy-retention > div { grid-template-columns: 1fr; gap: 6px; }
    .privacy-contact { padding: 22px 18px; }
    .privacy-contact a { overflow-wrap: anywhere; }
    .privacy-footer { flex-wrap: wrap; gap: 16px; padding-top: 25px; padding-bottom: 25px; }
    .privacy-footer .privacy-brand { width: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
  }
`;
