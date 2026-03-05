import { useEffect } from 'react';
import type { ReactNode } from 'react';
import './LegalPage.css';
import { applyRouteSeo } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { SiteFooter } from '../ui/SiteFooter';

export type LegalPageKind = 'privacy' | 'terms';

type LegalSection = {
  id: string;
  title: string;
  body: ReactNode;
};

type LegalCopy = {
  title: string;
  summary: string;
  sections: LegalSection[];
};

const LAST_UPDATED = 'February 24, 2026';
const SUPPORT_EMAIL = 'justin@dullypdf.com';

const PRIVACY_COPY: LegalCopy = {
  title: 'Privacy Policy',
  summary:
    'DullyPDF helps you turn PDFs into editable templates and fill them with local data. This policy explains what we collect, why we collect it, and how you can control it.',
  sections: [
    {
      id: 'information-we-collect',
      title: 'Information we collect',
      body: (
        <>
          <p>
            We collect the information you provide directly, plus limited technical data required to run the service.
            This includes:
          </p>
          <ul>
            <li>
              Account data such as your email address, authentication provider, and role/usage limits stored with your
              profile.
            </li>
            <li>
              PDFs and template data that you upload or save, including detected fields, coordinates, labels, and
              template settings stored with your saved forms.
            </li>
            <li>
              Schema metadata such as CSV/Excel/JSON/TXT column headers and types. The actual CSV/Excel/JSON rows stay in
              your browser and are not uploaded.
            </li>
            <li>
              Usage and diagnostic metadata like request timestamps, session identifiers, and rate-limit signals.
            </li>
            <li>
              Billing metadata required for subscriptions and credit refills, such as Stripe customer and
              subscription identifiers, plan identifiers, checkout/payment status, and cancellation schedule fields.
            </li>
            <li>
              Contact form details (name, company, email, phone, and message) when you reach out for support.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: 'how-we-use',
      title: 'How we use information',
      body: (
        <>
          <p>We use your information to:</p>
          <ul>
            <li>Provide PDF detection, template editing, and Search &amp; Fill features.</li>
            <li>Authenticate users, enforce usage limits, and keep your saved forms tied to your account.</li>
            <li>Process Stripe-backed subscriptions, credit refill purchases, and related billing state synchronization.</li>
            <li>Run optional AI rename and schema mapping workflows when you enable them.</li>
            <li>Respond to support requests and communicate about your account.</li>
            <li>Protect the service against abuse, fraud, and automated traffic.</li>
          </ul>
        </>
      ),
    },
    {
      id: 'billing-and-payments',
      title: 'Billing and payments',
      body: (
        <>
          <p>
            Paid subscriptions and credit refill transactions are processed by Stripe. We do not store full payment
            card numbers on DullyPDF servers.
          </p>
          <p>
            To support subscriptions and refill fulfillment, we store billing metadata (such as Stripe customer id,
            subscription id, checkout session id, and webhook event ids) and account billing state (for example
            subscription status and cancellation schedule).
          </p>
        </>
      ),
    },
    {
      id: 'ai-processing',
      title: 'AI processing and third-party services',
      body: (
        <>
          <p>
            When you enable AI rename or schema mapping, we send limited inputs to third-party AI providers. These
            inputs can include PDF page images, detected field labels, and schema headers. We do not send your
            CSV/Excel/JSON row data.
          </p>
          <p>
            DullyPDF uses service providers such as Firebase (authentication), Google Cloud Storage and Firestore
            (data storage), Stripe (payment processing), Google reCAPTCHA (abuse protection), and email delivery
            services for the contact form.
          </p>
        </>
      ),
    },
    {
      id: 'sharing',
      title: 'When we share data',
      body: (
        <>
          <p>
            We do not sell your personal information. We share data only with service providers that help operate
            DullyPDF (for example, cloud hosting, authentication, storage, payment processing, and AI processing) or
            when required by law.
          </p>
        </>
      ),
    },
    {
      id: 'retention',
      title: 'Retention',
      body: (
        <>
          <p>
            Session data and request logs are retained only for limited periods configured for performance and
            troubleshooting. Saved forms are stored until you delete them. Contact messages are retained as needed to
            respond to you.
          </p>
        </>
      ),
    },
    {
      id: 'security',
      title: 'Security',
      body: (
        <>
          <p>
            We use access controls and encryption in transit to protect your data. No method of transmission or storage
            is fully secure, so we cannot guarantee absolute security.
          </p>
        </>
      ),
    },
    {
      id: 'your-choices',
      title: 'Your choices',
      body: (
        <>
          <p>You can:</p>
          <ul>
            <li>Disable AI workflows and keep processing limited to detection and local editing.</li>
            <li>Delete saved forms from your profile to remove stored PDFs and template metadata.</li>
            <li>Manage or cancel active subscriptions from your profile billing section.</li>
            <li>Contact us to request account deletion or access questions at {SUPPORT_EMAIL}.</li>
          </ul>
        </>
      ),
    },
    {
      id: 'children',
      title: "Children's privacy",
      body: (
        <>
          <p>
            DullyPDF is not intended for children under 13, and we do not knowingly collect information from children.
          </p>
        </>
      ),
    },
    {
      id: 'changes',
      title: 'Changes to this policy',
      body: (
        <>
          <p>
            We may update this policy from time to time. The \"Last updated\" date above shows when it was last changed.
          </p>
        </>
      ),
    },
  ],
};

const TERMS_COPY: LegalCopy = {
  title: 'Terms of Service',
  summary:
    'These terms govern your use of DullyPDF. By accessing or using the service, you agree to these terms.',
  sections: [
    {
      id: 'operator',
      title: 'Operator',
      body: (
        <>
          <p>
            DullyPDF is a SaaS product operated by an individual based in New York State, United States. No separate
            legal entity has been formed yet.
          </p>
        </>
      ),
    },
    {
      id: 'service',
      title: 'Service description',
      body: (
        <>
          <p>
            DullyPDF provides tools to detect PDF form fields, rename and map fields with optional AI workflows, and
            fill templates with data from local CSV/Excel/JSON sources. Paid plans include recurring Pro subscriptions
            and Pro-only credit refill purchases.
          </p>
        </>
      ),
    },
    {
      id: 'accounts',
      title: 'Accounts and access',
      body: (
        <>
          <p>
            You are responsible for your account credentials and all activity that happens under your account. Provide
            accurate information and keep your login details secure.
          </p>
        </>
      ),
    },
    {
      id: 'your-content',
      title: 'Your content',
      body: (
        <>
          <p>
            You retain ownership of your PDFs and data. You grant DullyPDF a limited license to host, process, and
            transform your content solely to provide the service. You represent that you have the rights to upload and
            process any content you submit.
          </p>
        </>
      ),
    },
    {
      id: 'acceptable-use',
      title: 'Acceptable use',
      body: (
        <>
          <p>You agree not to:</p>
          <ul>
            <li>Use the service for unlawful, harmful, or fraudulent activities.</li>
            <li>Upload content you do not have rights to process.</li>
            <li>Attempt to reverse engineer, scrape, or disrupt the service.</li>
            <li>Bypass usage limits, authentication, or security controls.</li>
          </ul>
        </>
      ),
    },
    {
      id: 'ai-features',
      title: 'AI features',
      body: (
        <>
          <p>
            AI rename and schema mapping are optional. When enabled, you authorize DullyPDF to send limited content to
            third-party AI providers for processing. AI output may be inaccurate and must be reviewed before use.
          </p>
        </>
      ),
    },
    {
      id: 'limits',
      title: 'Usage limits and availability',
      body: (
        <>
          <p>
            The service may enforce page limits, credits, or other restrictions. We may modify, suspend, or discontinue
            features at any time, including in response to misuse or capacity constraints.
          </p>
        </>
      ),
    },
    {
      id: 'billing-subscriptions',
      title: 'Billing and subscriptions',
      body: (
        <>
          <p>
            DullyPDF uses Stripe Checkout for secure subscription and refill transactions. Pro Monthly and Pro Yearly
            are recurring subscriptions. Refill purchases are one-time credit packs that require an active Pro
            subscription.
          </p>
          <p>
            Subscription cancellation is handled from the profile billing section and is scheduled for period end. Your
            paid access remains active until the scheduled end date.
          </p>
          <p>
            Prices and plan availability are shown at checkout and may change over time. Payment processing is subject
            to Stripe's terms and policies in addition to these terms.
          </p>
        </>
      ),
    },
    {
      id: 'disclaimer',
      title: 'Disclaimer of warranties',
      body: (
        <>
          <p>
            DullyPDF is provided \"as is\" without warranties of any kind. We do not guarantee that the service will be
            uninterrupted, error-free, or produce specific results.
          </p>
        </>
      ),
    },
    {
      id: 'liability',
      title: 'Limitation of liability',
      body: (
        <>
          <p>
            To the maximum extent permitted by law, DullyPDF will not be liable for indirect, incidental, or
            consequential damages, or for loss of data, profits, or revenue arising from your use of the service.
          </p>
        </>
      ),
    },
    {
      id: 'termination',
      title: 'Termination',
      body: (
        <>
          <p>
            We may suspend or terminate access if you violate these terms. You may stop using the service at any time
            and request deletion of saved data.
          </p>
        </>
      ),
    },
    {
      id: 'governing-law',
      title: 'Governing law',
      body: (
        <>
          <p>
            These terms are governed by the laws of the State of New York, United States, without regard to conflict of
            law principles.
          </p>
        </>
      ),
    },
    {
      id: 'contact',
      title: 'Contact',
      body: (
        <>
          <p>Questions about these terms can be sent to {SUPPORT_EMAIL}.</p>
        </>
      ),
    },
  ],
};

const LEGAL_COPY: Record<LegalPageKind, LegalCopy> = {
  privacy: PRIVACY_COPY,
  terms: TERMS_COPY,
};

const NAV_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Privacy', href: '/privacy', kind: 'privacy' as LegalPageKind },
  { label: 'Terms', href: '/terms', kind: 'terms' as LegalPageKind },
];

type LegalPageProps = {
  kind: LegalPageKind;
};

const LegalPage = ({ kind }: LegalPageProps) => {
  const copy = LEGAL_COPY[kind];

  useEffect(() => {
    applyRouteSeo({ kind: 'legal', legalKind: kind });
  }, [kind]);

  return (
    <div className="legal-page">
      <div className="legal-card">
        <header className="legal-header">
          <div className="legal-brand">
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="legal-brand__logo" decoding="async" />
            </picture>
            <div className="legal-brand__text">
              <span className="legal-brand__name">DullyPDF</span>
              <span className="legal-brand__tagline">Automatic PDF to template</span>
            </div>
          </div>
          <nav className="legal-nav">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className={
                  link.kind === kind
                    ? 'legal-nav__link legal-nav__link--active'
                    : 'legal-nav__link'
                }
              >
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        <section className="legal-hero">
          <Breadcrumbs
            items={[
              { label: 'Home', href: '/' },
              { label: copy.title },
            ]}
          />
          <span className="legal-kicker">Legal</span>
          <h1 className="legal-title">{copy.title}</h1>
          <div className="legal-updated">Last updated: {LAST_UPDATED}</div>
          <p className="legal-summary">{copy.summary}</p>
        </section>

        <section className="legal-content">
          {copy.sections.map((section) => (
            <section key={section.id} id={section.id} className="legal-section">
              <h2>{section.title}</h2>
              {section.body}
            </section>
          ))}
        </section>

        <SiteFooter />
      </div>
    </div>
  );
};

export default LegalPage;
