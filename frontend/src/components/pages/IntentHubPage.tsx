import { useEffect } from 'react';
import {
  applyRouteSeo,
} from '../../utils/seo';
import { resolveRouteSeoBodyContent, type RouteBodySection } from '../../config/routeSeo';
import { IntentPageShell } from './IntentPageShell';

type IntentHubKey = 'workflows' | 'industries';

type IntentHubPageProps = {
  hubKey: IntentHubKey;
};

const HUB_BREADCRUMB_LABEL: Record<IntentHubKey, string> = {
  workflows: 'Workflows',
  industries: 'Industries',
};

const IntentHubPage = ({ hubKey }: IntentHubPageProps) => {
  const bodyContent = resolveRouteSeoBodyContent({ kind: 'intent-hub', hubKey });
  const pageSections = (bodyContent?.sections ?? []) as RouteBodySection[];

  useEffect(() => {
    applyRouteSeo({ kind: 'intent-hub', hubKey });
  }, [hubKey]);

  return (
    <IntentPageShell
      breadcrumbItems={[{ label: 'Home', href: '/' }, { label: HUB_BREADCRUMB_LABEL[hubKey] }]}
      heroKicker={bodyContent?.heroKicker ?? 'Hub'}
      heroTitle={bodyContent?.heading ?? 'Public route library'}
      heroSummary={bodyContent?.paragraphs?.[0] ?? ''}
    >
      <section className="intent-page__panel">
        <h2>{bodyContent?.panelTitle ?? 'Pages'}</h2>
        <p>{bodyContent?.panelDescription ?? ''}</p>
        <div className="intent-page__related-links">
          {pageSections.map((section) => (
            <a key={section.href ?? section.title} href={section.href ?? '#'} className="intent-page__related-link">
              {section.title}
            </a>
          ))}
        </div>
      </section>

      {(bodyContent?.supportSections ?? []).map((section) => (
        <section
          key={section.title}
          className={section.paragraphs?.length ? 'intent-page__panel intent-page__panel--article' : 'intent-page__panel'}
        >
          <h2>{section.title}</h2>
          {section.paragraphs?.length ? (
            <div className="intent-page__article-copy">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          ) : null}
          {section.links?.length ? (
            <div className="intent-page__related-links">
              {section.links.map((link) => (
                <a key={link.href} href={link.href} className="intent-page__related-link">
                  {link.label}
                </a>
              ))}
            </div>
          ) : null}
        </section>
      ))}
    </IntentPageShell>
  );
};

export default IntentHubPage;
