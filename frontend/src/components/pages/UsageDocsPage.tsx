import { useEffect, useMemo } from 'react';
import type { UsageDocsPageKey } from './usageDocsContent';
import {
  getUsageDocsPage,
  getUsageDocsPages,
  usageDocsHref,
} from './usageDocsContent';
import './UsageDocsPage.css';
import { applyRouteSeo } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { SiteFooter } from '../ui/SiteFooter';
import type { IntentPageKey } from '../../config/intentPages';
import { getIntentPage } from '../../config/intentPages';

type UsageDocsPageProps = {
  pageKey: UsageDocsPageKey;
};

const HEADER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
];

const RELATED_INTENT_PAGES: Record<string, IntentPageKey[]> = {
  'getting-started': ['pdf-to-fillable-form', 'fill-pdf-from-csv'],
  detection: ['pdf-to-fillable-form', 'healthcare-pdf-automation'],
  'rename-mapping': ['pdf-to-database-template', 'fillable-form-field-name'],
  'search-fill': ['fill-pdf-from-csv', 'fill-information-in-pdf'],
  'fill-by-link': ['fill-pdf-by-link', 'fill-information-in-pdf'],
  'create-group': ['pdf-to-fillable-form', 'pdf-to-database-template'],
  'save-download-profile': ['pdf-to-fillable-form'],
  troubleshooting: [],
  'editor-workflow': ['pdf-to-fillable-form'],
  index: [],
};

const UsageDocsPage = ({ pageKey }: UsageDocsPageProps) => {
  const page = getUsageDocsPage(pageKey);
  const pages = getUsageDocsPages();

  const relatedWorkflows = useMemo(() => {
    const keys = RELATED_INTENT_PAGES[pageKey] || [];
    return keys.map((key) => {
      const p = getIntentPage(key);
      return { label: p.navLabel, href: p.path };
    });
  }, [pageKey]);

  useEffect(() => {
    applyRouteSeo({ kind: 'usage-docs', pageKey });
  }, [pageKey]);

  const breadcrumbItems = pageKey === 'index'
    ? [{ label: 'Home', href: '/' }, { label: 'Usage Docs' }]
    : [{ label: 'Home', href: '/' }, { label: 'Usage Docs', href: '/usage-docs' }, { label: page.title }];

  return (
    <div className="usage-docs-page">
      <div className="usage-docs-card">
        <header className="usage-docs-header">
          <div className="usage-docs-brand">
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="usage-docs-brand__logo" decoding="async" />
            </picture>
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
          <Breadcrumbs items={breadcrumbItems} />
          <span className="usage-docs-kicker">Usage docs</span>
          <h1 className="usage-docs-title">{page.title}</h1>
          <p className="usage-docs-summary">{page.summary}</p>
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

            {relatedWorkflows.length > 0 && (
              <section className="usage-docs-section usage-docs-section--related">
                <h2>Related workflows</h2>
                <ul>
                  {relatedWorkflows.map((link) => (
                    <li key={link.href}>
                      <a href={link.href}>{link.label}</a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </main>
        </div>

        <SiteFooter />
      </div>
    </div>
  );
};

export default UsageDocsPage;
