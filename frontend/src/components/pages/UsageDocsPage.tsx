import { useEffect } from 'react';
import type { UsageDocsPageKey } from './usageDocsContent';
import {
  getUsageDocsPage,
  getUsageDocsPages,
  usageDocsHref,
} from './usageDocsContent';
import './UsageDocsPage.css';

type UsageDocsPageProps = {
  pageKey: UsageDocsPageKey;
  unknownSlug?: string | null;
};

const HEADER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
];

const UsageDocsPage = ({ pageKey, unknownSlug = null }: UsageDocsPageProps) => {
  const page = getUsageDocsPage(pageKey);
  const pages = getUsageDocsPages();

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const title = pageKey === 'index' ? 'Usage Docs | DullyPDF' : `${page.title} | Usage Docs | DullyPDF`;
    document.title = title;
  }, [page.title, pageKey]);

  return (
    <div className="usage-docs-page">
      <div className="usage-docs-card">
        <header className="usage-docs-header">
          <div className="usage-docs-brand">
            <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="usage-docs-brand__logo" />
            <div className="usage-docs-brand__text">
              <span className="usage-docs-brand__name">DullyPDF</span>
              <span className="usage-docs-brand__tagline">Usage Documentation</span>
            </div>
          </div>
          <nav className="usage-docs-top-nav" aria-label="Primary docs navigation">
            {HEADER_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className={link.href === '/usage-docs' ? 'usage-docs-top-nav__link usage-docs-top-nav__link--active' : 'usage-docs-top-nav__link'}
              >
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        <section className="usage-docs-hero">
          <span className="usage-docs-kicker">Usage docs</span>
          <h1 className="usage-docs-title">{page.title}</h1>
          <p className="usage-docs-summary">{page.summary}</p>
          {unknownSlug ? (
            <div className="usage-docs-warning" role="status">
              Could not find a page for <code>{unknownSlug}</code>. Showing the overview instead.
            </div>
          ) : null}
        </section>

        <div className="usage-docs-layout">
          <aside className="usage-docs-sidebar" aria-label="Usage docs sidebar">
            <div className="usage-docs-sidebar__group">
              <h2>Pages</h2>
              <div className="usage-docs-sidebar__pages">
                {pages.map((entry) => {
                  const active = entry.key === page.key;
                  return (
                    <a
                      key={entry.key}
                      href={usageDocsHref(entry.key)}
                      className={active ? 'usage-docs-sidebar__page usage-docs-sidebar__page--active' : 'usage-docs-sidebar__page'}
                      aria-current={active ? 'page' : undefined}
                    >
                      {entry.navLabel}
                    </a>
                  );
                })}
              </div>
            </div>

            <div className="usage-docs-sidebar__group">
              <h2>On this page</h2>
              <div className="usage-docs-sidebar__sections">
                {page.sections.map((section) => (
                  <a key={section.id} href={`#${section.id}`} className="usage-docs-sidebar__section-link">
                    {section.title}
                  </a>
                ))}
              </div>
            </div>
          </aside>

          <main className="usage-docs-content">
            {page.sections.map((section) => (
              <section key={section.id} id={section.id} className="usage-docs-section">
                <h2>{section.title}</h2>
                {section.body}
              </section>
            ))}
          </main>
        </div>

        <footer className="usage-docs-footer">
          <div>
            Questions about product usage: <a href="mailto:justin@ttcommercial.com">justin@ttcommercial.com</a>
          </div>
          <div className="usage-docs-footer__meta">DullyPDF</div>
        </footer>
      </div>
    </div>
  );
};

export default UsageDocsPage;
