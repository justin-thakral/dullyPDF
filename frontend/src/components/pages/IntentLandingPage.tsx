import { useEffect, useMemo } from 'react';
import {
  getIntentPage,
  getIntentPages,
  type IntentPageKey,
} from '../../config/intentPages';
import { applyRouteSeo } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { SiteFooter } from '../ui/SiteFooter';
import './IntentLandingPage.css';

type IntentLandingPageProps = {
  pageKey: IntentPageKey;
};

const GLOBAL_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
];

const IntentLandingPage = ({ pageKey }: IntentLandingPageProps) => {
  const page = getIntentPage(pageKey);
  const relatedPages = useMemo(
    () => {
      const remaining = getIntentPages().filter((entry) => entry.key !== pageKey);
      const sameCategory = remaining.filter((entry) => entry.category === page.category);
      const otherCategory = remaining.filter((entry) => entry.category !== page.category);
      return [...sameCategory, ...otherCategory];
    },
    [page.category, pageKey],
  );

  useEffect(() => {
    applyRouteSeo({ kind: 'intent', intentKey: pageKey });
  }, [pageKey]);

  return (
    <div className="intent-page">
      <div className="intent-page__card">
        <header className="intent-page__header">
          <div className="intent-page__brand">
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="intent-page__logo" decoding="async" />
            </picture>
            <div>
              <div className="intent-page__brand-name">DullyPDF</div>
              <div className="intent-page__brand-tagline">PDF automation workflows</div>
            </div>
          </div>
          <nav className="intent-page__nav" aria-label="Primary navigation">
            {GLOBAL_LINKS.map((link) => (
              <a key={link.href} href={link.href} className="intent-page__nav-link">
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        <main className="intent-page__content">
          <Breadcrumbs
            items={[
              { label: 'Home', href: '/' },
              { label: page.category === 'industry' ? 'Industries' : 'Workflows' },
              { label: page.navLabel },
            ]}
          />
          <section className="intent-page__hero">
            <p className="intent-page__kicker">
              {page.category === 'industry' ? 'Industry workflow page' : 'Commercial workflow page'}
            </p>
            <h1>{page.heroTitle}</h1>
            <p>{page.heroSummary}</p>
            <div className="intent-page__cta-row">
              <a href="/" className="intent-page__cta intent-page__cta--primary">
                Try DullyPDF Now
              </a>
              <a href="/usage-docs/getting-started" className="intent-page__cta intent-page__cta--secondary">
                View Getting Started Docs
              </a>
            </div>
          </section>

          <section className="intent-page__grid">
            <article className="intent-page__panel">
              <h2>What this page solves</h2>
              <ul>
                {page.valuePoints.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>

            <article className="intent-page__panel">
              <h2>Evidence and implementation proof</h2>
              <ul>
                {page.proofPoints.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
              <p>
                Need deeper technical details? Use the
                {' '}
                <a href="/usage-docs/rename-mapping">Rename + Mapping docs</a>
                {' '}
                and
                {' '}
                <a href="/usage-docs/search-fill">Search &amp; Fill docs</a>
                {' '}
                to validate exact behavior.
              </p>
            </article>
          </section>

          <section className="intent-page__panel">
            <h2>Frequently asked questions</h2>
            <div className="intent-page__faq-list">
              {page.faqs.map((faq) => (
                <article key={faq.question} className="intent-page__faq-item">
                  <h3>{faq.question}</h3>
                  <p>{faq.answer}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="intent-page__panel">
            <h2>Public workflow examples</h2>
            <p>
              These links are designed as shareable authority assets for communities, partners, and implementation
              reviews.
            </p>
            <div className="intent-page__related-links">
              <a href="/usage-docs/getting-started" className="intent-page__related-link">
                End-to-end quick-start example
              </a>
              <a href="/usage-docs/detection" className="intent-page__related-link">
                Detection quality review example
              </a>
              <a href="/usage-docs/rename-mapping" className="intent-page__related-link">
                Mapping and rename example
              </a>
              <a href="/usage-docs/search-fill" className="intent-page__related-link">
                Search &amp; Fill validation example
              </a>
              <a href="/usage-docs/troubleshooting" className="intent-page__related-link">
                Troubleshooting playbook example
              </a>
              <a href="mailto:justin@ttcommercial.com" className="intent-page__related-link">
                Request partner workflow review
              </a>
            </div>
          </section>

          <section className="intent-page__panel">
            <h2>Related search intents</h2>
            <p>
              Explore adjacent intent pages so visitors searching for fillable form field name cleanup, PDF database
              templates, or how to fill information in PDF forms can find the right entry point.
            </p>
            <div className="intent-page__related-links">
              {relatedPages.map((entry) => (
                <a key={entry.key} href={entry.path} className="intent-page__related-link">
                  {entry.navLabel}
                </a>
              ))}
            </div>
          </section>
        </main>
        <SiteFooter />
      </div>
    </div>
  );
};

export default IntentLandingPage;
