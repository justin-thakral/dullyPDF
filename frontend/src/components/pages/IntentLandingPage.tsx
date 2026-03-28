import { useEffect, useMemo, type ReactNode } from 'react';
import {
  getIntentPage,
  getIntentPages,
  type IntentPageKey,
} from '../../config/intentPages';
import { getUsageDocsPage, usageDocsHref } from './usageDocsContent';
import { applyRouteSeo } from '../../utils/seo';
import { IntentPageShell } from './IntentPageShell';

type IntentLandingPageProps = {
  pageKey: IntentPageKey;
};

const FOOTNOTE_TOKEN = /\[\^([a-z0-9-]+)\]/gi;

const getFootnoteSuffix = (referenceIndex: number): string => {
  let remaining = referenceIndex;
  let suffix = '';

  while (remaining > 0) {
    remaining -= 1;
    suffix = String.fromCharCode(97 + (remaining % 26)) + suffix;
    remaining = Math.floor(remaining / 26);
  }

  return suffix;
};

const IntentLandingPage = ({ pageKey }: IntentLandingPageProps) => {
  const page = getIntentPage(pageKey);
  const footnoteNumberById = useMemo(
    () => new Map((page.footnotes ?? []).map((footnote, index) => [footnote.id, index + 1])),
    [page.footnotes],
  );
  const footnoteReferenceTotalById = useMemo(
    () => {
      const totals = new Map<string, number>();
      const collect = (text: string) => {
        FOOTNOTE_TOKEN.lastIndex = 0;
        let match: RegExpExecArray | null = FOOTNOTE_TOKEN.exec(text);
        while (match) {
          const footnoteId = match[1];
          totals.set(footnoteId, (totals.get(footnoteId) ?? 0) + 1);
          match = FOOTNOTE_TOKEN.exec(text);
        }
      };

      page.articleSections?.forEach((section) => {
        section.paragraphs.forEach(collect);
        section.bullets?.forEach(collect);
      });
      page.valuePoints.forEach(collect);
      page.proofPoints.forEach(collect);
      page.faqs.forEach((faq) => collect(faq.answer));
      page.supportSections?.forEach((section) => {
        section.paragraphs?.forEach(collect);
      });

      return totals;
    },
    [page.articleSections, page.faqs, page.proofPoints, page.supportSections, page.valuePoints],
  );
  const footnoteReferenceCounts = new Map<string, number>();
  const relatedPages = useMemo(
    () => {
      if (page.relatedIntentPages?.length) {
        return page.relatedIntentPages.map((key) => getIntentPage(key));
      }

      const remaining = getIntentPages().filter((entry) => entry.key !== pageKey);
      const sameCategory = remaining.filter((entry) => entry.category === page.category);
      const otherCategory = remaining.filter((entry) => entry.category !== page.category);
      return [...sameCategory, ...otherCategory];
    },
    [page.category, page.relatedIntentPages, pageKey],
  );
  const relatedDocs = useMemo(
    () => {
      const pageKeys = page.relatedDocs ?? ['getting-started', 'detection', 'rename-mapping', 'search-fill'];
      return pageKeys.map((key) => {
        const doc = getUsageDocsPage(key);
        return { label: doc.title, href: usageDocsHref(key) };
      });
    },
    [page.relatedDocs],
  );
  const implementationChecklist = useMemo(
    () => [
      'Start with one recurring PDF layout instead of every possible variation.',
      'Validate field geometry, names, checkbox groups, and date behavior before sharing the workflow broadly.',
      'Run one representative record through the full template before treating the route as production-ready.',
      page.category === 'industry'
        ? 'Document version control matters more than volume. Keep one canonical template per recurring form type whenever possible.'
        : 'Use the saved-template workflow to preserve one canonical setup instead of rebuilding the same document every time.',
    ],
    [page.category],
  );

  const renderFootnotedText = (text: string) => {
    const parts: ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    FOOTNOTE_TOKEN.lastIndex = 0;
    match = FOOTNOTE_TOKEN.exec(text);
    while (match) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }

      const footnoteId = match[1];
      const footnoteNumber = footnoteNumberById.get(footnoteId);
      if (!footnoteNumber) {
        parts.push(match[0]);
      } else {
        const nextReferenceCount = (footnoteReferenceCounts.get(footnoteId) ?? 0) + 1;
        footnoteReferenceCounts.set(footnoteId, nextReferenceCount);
        const totalReferenceCount = footnoteReferenceTotalById.get(footnoteId) ?? 1;
        const footnoteMarker = totalReferenceCount > 1
          ? `${footnoteNumber}${getFootnoteSuffix(nextReferenceCount)}`
          : `${footnoteNumber}`;
        const referenceId = `footnote-ref-${footnoteId}-${nextReferenceCount}`;
        parts.push(
          <sup key={`${footnoteId}-${match.index}`} className="intent-page__footnote-ref">
            <a
              id={referenceId}
              href={`#footnote-${footnoteId}`}
              aria-label={`See legal footnote ${footnoteMarker}`}
            >
              {footnoteMarker}
            </a>
          </sup>,
        );
      }

      lastIndex = match.index + match[0].length;
      match = FOOTNOTE_TOKEN.exec(text);
    }

    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex));
    }

    return parts.length ? parts : text;
  };

  useEffect(() => {
    applyRouteSeo({ kind: 'intent', intentKey: pageKey });
  }, [pageKey]);

  return (
    <IntentPageShell
      breadcrumbItems={[
        { label: 'Home', href: '/' },
        { label: page.category === 'industry' ? 'Industries' : 'Workflows' },
        { label: page.navLabel },
      ]}
      heroKicker={page.category === 'industry' ? 'Industry workflow page' : 'Commercial workflow page'}
      heroTitle={page.heroTitle}
      heroSummary={page.heroSummary}
    >
      {page.articleSections?.map((section) => (
        <section key={section.title} className="intent-page__panel intent-page__panel--article">
          <h2>{section.title}</h2>
          <div className="intent-page__article-copy">
            {section.paragraphs.map((paragraph) => (
              <p key={paragraph}>{renderFootnotedText(paragraph)}</p>
            ))}
            {section.bullets?.length ? (
              <ul>
                {section.bullets.map((bullet) => (
                  <li key={bullet}>{renderFootnotedText(bullet)}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </section>
      ))}

      <section className="intent-page__panel intent-page__panel--article">
        <h2>How teams put this into production</h2>
        <div className="intent-page__article-copy">
          <p>
            This route is strongest when it is treated as an operating workflow rather than a one-time conversion.
            The durable pattern is to pick one representative document, turn it into a reusable template, test it
            against real data, and only then expand to more records or adjacent form variations.
          </p>
          <p>
            That rollout order matters because the early mistakes are rarely in the headline feature. They are in
            field naming, checkbox grouping, date handling, and quality assurance. A disciplined first pass usually
            saves more time than trying to automate everything at once.
          </p>
          <ul>
            {implementationChecklist.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="intent-page__grid">
        <article className="intent-page__panel">
          <h2>What this page solves</h2>
          <ul>
            {page.valuePoints.map((point) => (
              <li key={point}>{renderFootnotedText(point)}</li>
            ))}
          </ul>
        </article>

        <article className="intent-page__panel">
          <h2>Evidence and implementation proof</h2>
          <ul>
            {page.proofPoints.map((point) => (
              <li key={point}>{renderFootnotedText(point)}</li>
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
              <p>{renderFootnotedText(faq.answer)}</p>
            </article>
          ))}
        </div>
      </section>

      {page.footnotes?.length ? (
        <section className="intent-page__panel intent-page__panel--article">
          <h2>Legal footnotes and sources</h2>
          <ol className="intent-page__footnote-list">
            {page.footnotes.map((footnote, index) => (
              <li key={footnote.id} id={`footnote-${footnote.id}`} className="intent-page__footnote-item">
                <span className="intent-page__footnote-number">{index + 1}.</span>
                <a href={footnote.href} className="intent-page__footnote-link">
                  {footnote.label}
                </a>
                <a
                  href={`#footnote-ref-${footnote.id}-1`}
                  className="intent-page__footnote-backlink"
                  aria-label={`Back to first reference for footnote ${
                    (footnoteReferenceTotalById.get(footnote.id) ?? 0) > 1 ? `${index + 1}a` : `${index + 1}`
                  }`}
                >
                  ↩
                </a>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {(page.supportSections ?? []).map((section) => (
        <section
          key={section.title}
          className={section.paragraphs?.length ? 'intent-page__panel intent-page__panel--article' : 'intent-page__panel'}
        >
          <h2>{section.title}</h2>
          {section.paragraphs?.length ? (
            <div className="intent-page__article-copy">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{renderFootnotedText(paragraph)}</p>
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

      <section className="intent-page__panel">
        <h2>Supporting docs</h2>
        <p>
          Use these docs pages when you want the exact runtime behavior behind the workflow instead of summary-level
          landing-page copy.
        </p>
        <div className="intent-page__related-links">
          {relatedDocs.map((doc) => (
            <a key={doc.href} href={doc.href} className="intent-page__related-link">
              {doc.label}
            </a>
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
          <a href="mailto:justin@dullypdf.com" className="intent-page__related-link">
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
    </IntentPageShell>
  );
};

export default IntentLandingPage;
