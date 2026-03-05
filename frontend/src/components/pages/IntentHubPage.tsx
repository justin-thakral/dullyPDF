import { useEffect, useMemo } from 'react';
import { getIntentPages, type IntentPageCategory } from '../../config/intentPages';
import { applyRouteSeo } from '../../utils/seo';
import { IntentPageShell } from './IntentPageShell';

type IntentHubKey = 'workflows' | 'industries';

type IntentHubPageProps = {
  hubKey: IntentHubKey;
};

type HubConfig = {
  category: IntentPageCategory;
  breadcrumbLabel: string;
  kicker: string;
  title: string;
  summary: string;
  panelTitle: string;
  panelDescription: string;
};

const HUB_CONFIG: Record<IntentHubKey, HubConfig> = {
  workflows: {
    category: 'workflow',
    breadcrumbLabel: 'Workflows',
    kicker: 'Workflow hub',
    title: 'Workflow Library for PDF Automation',
    summary:
      'Browse high-intent workflow pages for converting PDFs to fillable templates, mapping fields, and auto-filling from structured data.',
    panelTitle: 'All workflow pages',
    panelDescription:
      'These pages are organized for users searching by action (convert, map, fill, rename). Start with the workflow closest to your immediate task.',
  },
  industries: {
    category: 'industry',
    breadcrumbLabel: 'Industries',
    kicker: 'Industry hub',
    title: 'Industry Solutions for Repeat PDF Workflows',
    summary:
      'Browse industry-specific pages for healthcare, insurance, legal, HR, finance, and other document-heavy operations.',
    panelTitle: 'All industry pages',
    panelDescription:
      'These pages are organized for teams searching by vertical. Choose your industry route to see targeted implementation guidance and examples.',
  },
};

const IntentHubPage = ({ hubKey }: IntentHubPageProps) => {
  const hub = HUB_CONFIG[hubKey];
  const pages = useMemo(
    () => getIntentPages().filter((page) => page.category === hub.category),
    [hub.category],
  );

  useEffect(() => {
    applyRouteSeo({ kind: 'intent-hub', hubKey });
  }, [hubKey]);

  return (
    <IntentPageShell
      breadcrumbItems={[{ label: 'Home', href: '/' }, { label: hub.breadcrumbLabel }]}
      heroKicker={hub.kicker}
      heroTitle={hub.title}
      heroSummary={hub.summary}
    >
      <section className="intent-page__panel">
        <h2>{hub.panelTitle}</h2>
        <p>{hub.panelDescription}</p>
        <div className="intent-page__related-links">
          {pages.map((page) => (
            <a key={page.key} href={page.path} className="intent-page__related-link">
              {page.navLabel}
            </a>
          ))}
        </div>
      </section>
    </IntentPageShell>
  );
};

export default IntentHubPage;
