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

const UsageDocsPage = ({ pageKey }: UsageDocsPageProps) => {
  const page = getUsageDocsPage(pageKey);
  const pages = getUsageDocsPages();

  const relatedWorkflows = useMemo(() => {
    const keys: IntentPageKey[] = page.relatedWorkflowKeys ?? [];
    return keys.map((key) => {
      const p = getIntentPage(key);
      return { label: p.navLabel, href: p.path };
    });
  }, [page.relatedWorkflowKeys]);
  const adjacentDocs = useMemo(() => {
    const currentIndex = pages.findIndex((entry) => entry.key === pageKey);
    return pages.filter((entry, index) => entry.key !== pageKey && Math.abs(index - currentIndex) <= 2);
  }, [pageKey, pages]);

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
            <section className="usage-docs-section">
              <h2>How to use this docs page</h2>
              <p>
                This page is meant to answer one operational stage of the DullyPDF workflow well enough that you can
                run a controlled test without guessing. Read the sections below, validate the behavior against one
                representative document, and only then move to the next linked page.
              </p>
              <p>
                That order matters because most setup failures come from mixing detection, mapping, fill validation,
                and sharing into one unstructured pass. A narrower review loop keeps troubleshooting faster and makes
                the template easier to trust once you save it for reuse.
              </p>
            </section>

            {page.sections.map((section) => (
              <section key={section.id} id={section.id} className="usage-docs-section">
                <h2>{section.title}</h2>
                {section.body}
              </section>
            ))}

            {adjacentDocs.length > 0 && (
              <section className="usage-docs-section usage-docs-section--related">
                <h2>Continue through the docs</h2>
                <p>
                  Move to the next closest docs page instead of skipping ahead to unrelated features. That keeps the
                  rollout sequence easier to validate and reduces setup drift between templates.
                </p>
                <ul>
                  {adjacentDocs.map((entry) => (
                    <li key={entry.key}>
                      <a href={usageDocsHref(entry.key)}>{entry.title}</a>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {relatedWorkflows.length > 0 && (
              <section className="usage-docs-section usage-docs-section--related">
                <h2>Related workflows</h2>
                <p>
                  These workflow pages explain the public search-intent side of the same feature area, which is useful
                  when you need a higher-level route summary before returning to the operational docs.
                </p>
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
