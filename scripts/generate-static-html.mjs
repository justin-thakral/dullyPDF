#!/usr/bin/env node
/**
 * Static HTML generator for DullyPDF SEO.
 *
 * Reads dist/index.html (after Vite build) to extract asset tags, then generates
 * a standalone HTML file per public route with correct meta tags, JSON-LD,
 * and visible semantic body content. Firebase Hosting serves these static files
 * directly; React loads on top for interactivity.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  ALL_ROUTES,
  SITE_ORIGIN,
  DEFAULT_SOCIAL_IMAGE_PATH,
  FOOTER_LINKS,
  BLOG_POSTS,
  INTENT_PAGES,
  USAGE_DOCS_PAGES,
} from './seo-route-data.mjs';

const DIST_DIR = resolve(process.cwd(), 'frontend/dist');

const TOP_NAV_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Workflows', href: '/workflows' },
  { label: 'Industries', href: '/industries' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Blog', href: '/blog' },
];

const SEO_SHELL_STYLE = `
      :root {
        --seo-bg: linear-gradient(180deg, #f3f7fb 0%, #eef4ff 100%);
        --seo-card: rgba(255, 255, 255, 0.94);
        --seo-border: rgba(15, 23, 42, 0.08);
        --seo-text: #10233b;
        --seo-muted: #41546d;
        --seo-link: #0f4fb8;
        --seo-link-hover: #0b3a86;
        --seo-accent: #d7e5ff;
        --seo-shadow: 0 24px 70px rgba(15, 23, 42, 0.08);
      }
      body {
        margin: 0;
        background: var(--seo-bg);
        color: var(--seo-text);
        font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif;
      }
      .seo-shell {
        max-width: 1120px;
        margin: 0 auto;
        padding: 28px 20px 72px;
      }
      .seo-shell__card {
        background: var(--seo-card);
        border: 1px solid var(--seo-border);
        border-radius: 24px;
        box-shadow: var(--seo-shadow);
        overflow: hidden;
      }
      .seo-shell__topbar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 20px 24px;
        border-bottom: 1px solid var(--seo-border);
        background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(247,250,255,0.96) 100%);
      }
      .seo-shell__brand {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .seo-shell__brand-mark {
        width: 42px;
        height: 42px;
        border-radius: 12px;
      }
      .seo-shell__brand-name {
        display: block;
        font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
        font-size: 1.05rem;
        font-weight: 700;
      }
      .seo-shell__brand-tagline {
        display: block;
        color: var(--seo-muted);
        font-size: 0.92rem;
      }
      .seo-shell__nav {
        display: flex;
        flex-wrap: wrap;
        gap: 10px 18px;
      }
      .seo-shell__nav a,
      .seo-shell a {
        color: var(--seo-link);
        text-decoration: none;
      }
      .seo-shell__nav a:hover,
      .seo-shell a:hover {
        color: var(--seo-link-hover);
        text-decoration: underline;
      }
      .seo-shell__main {
        padding: 28px 24px 32px;
      }
      .seo-shell__hero {
        padding-bottom: 16px;
      }
      .seo-shell__eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
        padding: 6px 10px;
        border-radius: 999px;
        background: var(--seo-accent);
        color: #13396a;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .seo-shell h1,
      .seo-shell h2,
      .seo-shell h3 {
        font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
        line-height: 1.15;
        margin: 0 0 12px;
      }
      .seo-shell h1 {
        font-size: clamp(2rem, 4vw, 3.2rem);
        max-width: 16ch;
      }
      .seo-shell h2 {
        font-size: clamp(1.25rem, 2.4vw, 1.7rem);
      }
      .seo-shell h3 {
        font-size: 1.08rem;
      }
      .seo-shell p,
      .seo-shell li {
        color: var(--seo-muted);
        font-size: 1rem;
        line-height: 1.72;
      }
      .seo-shell section + section {
        margin-top: 26px;
      }
      .seo-shell__panel-grid,
      .seo-shell__link-grid,
      .seo-shell__footer-grid {
        display: grid;
        gap: 16px;
      }
      .seo-shell__panel-grid {
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      }
      .seo-shell__link-grid,
      .seo-shell__footer-grid {
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      }
      .seo-shell__panel,
      .seo-shell__link-card,
      .seo-shell__footer-column {
        padding: 18px;
        border-radius: 18px;
        border: 1px solid var(--seo-border);
        background: rgba(255,255,255,0.86);
      }
      .seo-shell__outline,
      .seo-shell__list {
        padding-left: 20px;
        margin: 12px 0 0;
      }
      .seo-shell__link-card p,
      .seo-shell__panel p {
        margin: 0;
      }
      .seo-shell__cta {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        align-items: center;
        margin-top: 28px;
      }
      .seo-shell__cta-primary {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 12px 16px;
        border-radius: 999px;
        background: #143f89;
        color: #fff !important;
        font-weight: 600;
      }
      .seo-shell__cta-primary:hover {
        background: #0f336e;
        text-decoration: none !important;
      }
      .seo-shell__footer {
        padding: 0 24px 28px;
      }
      .seo-shell__footer-meta {
        margin-top: 18px;
        color: var(--seo-muted);
        font-size: 0.94rem;
      }
      @media (max-width: 720px) {
        .seo-shell {
          padding: 14px 12px 48px;
        }
        .seo-shell__topbar,
        .seo-shell__main,
        .seo-shell__footer {
          padding-left: 16px;
          padding-right: 16px;
        }
        .seo-shell h1 {
          max-width: none;
        }
      }
`;

// ---------------------------------------------------------------------------
// Extract Vite asset tags from the built index.html
// ---------------------------------------------------------------------------

function extractViteAssetTags(indexHtml) {
  const headMatch = indexHtml.match(/<head>([\s\S]*?)<\/head>/i);
  const headHtml = headMatch ? headMatch[1] : '';

  const headScriptTags = [];
  const headScriptRegex = /<script\b[^>]*>[\s\S]*?<\/script>/gi;
  let scriptMatch;
  while ((scriptMatch = headScriptRegex.exec(headHtml)) !== null) {
    if (scriptMatch[0].includes('type="module"')) continue;
    headScriptTags.push(scriptMatch[0]);
  }

  const linkTags = [];
  const linkRegex = /<link\s[^>]*(?:rel="(?:stylesheet|modulepreload)")[^>]*\/?>/gi;
  let match;
  while ((match = linkRegex.exec(indexHtml)) !== null) {
    if (match[0].includes('fonts.googleapis.com') || match[0].includes('fonts.gstatic.com') || match[0].includes('icon')) continue;
    linkTags.push(match[0]);
  }

  const scriptTags = [];
  const scriptRegex = /<script\s[^>]*type="module"[^>]*><\/script>/gi;
  while ((match = scriptRegex.exec(indexHtml)) !== null) {
    scriptTags.push(match[0]);
  }

  return { headScriptTags, linkTags, scriptTags };
}

// ---------------------------------------------------------------------------
// HTML escaping
// ---------------------------------------------------------------------------

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function findIntentPage(key) {
  return INTENT_PAGES.find((page) => page.key === key) || null;
}

function findUsageDocsPage(key) {
  return USAGE_DOCS_PAGES.find((page) => page.key === key) || null;
}

function findBlogPost(slug) {
  return BLOG_POSTS.find((post) => post.slug === slug) || null;
}

function renderLinkCards(title, description, links) {
  if (!links?.length) return '';
  const parts = [`<section><h2>${esc(title)}</h2>`];
  if (description) parts.push(`<p>${esc(description)}</p>`);
  parts.push('<div class="seo-shell__link-grid">');
  for (const link of links) {
    parts.push('<article class="seo-shell__link-card">');
    parts.push(`<h3><a href="${esc(link.href)}">${esc(link.label)}</a></h3>`);
    if (link.description) {
      parts.push(`<p>${esc(link.description)}</p>`);
    }
    parts.push('</article>');
  }
  parts.push('</div></section>');
  return parts.join('\n');
}

function renderTopNav() {
  return `<nav class="seo-shell__nav" aria-label="Primary site navigation">
    ${TOP_NAV_LINKS.map((link) => `<a href="${esc(link.href)}">${esc(link.label)}</a>`).join('\n    ')}
  </nav>`;
}

function renderFooter() {
  const renderColumn = (title, links) => `
    <div class="seo-shell__footer-column">
      <strong>${esc(title)}</strong>
      <ul class="seo-shell__list">
        ${links.map((link) => `<li><a href="${esc(link.href)}">${esc(link.label)}</a></li>`).join('')}
      </ul>
    </div>`;

  return `<footer class="seo-shell__footer">
    <div class="seo-shell__footer-grid">
      ${renderColumn('Product', FOOTER_LINKS.product)}
      ${renderColumn('Workflows', FOOTER_LINKS.workflows)}
      ${renderColumn('Industries', FOOTER_LINKS.industries)}
      ${renderColumn('Resources', FOOTER_LINKS.resources)}
      ${renderColumn('Legal', FOOTER_LINKS.legal)}
    </div>
    <p class="seo-shell__footer-meta">DullyPDF focuses on repeat PDF workflows: detect fields, refine them, map them to structured data, and fill the same document type reliably over time.</p>
    <p class="seo-shell__footer-meta">&copy; ${new Date().getFullYear()} DullyPDF</p>
  </footer>`;
}

function buildSupplementalParagraphs(route) {
  switch (route.kind) {
    case 'usage-docs':
      return [
        'Use this documentation page when you are already committed to the DullyPDF workflow and need exact operational guidance instead of top-level marketing copy. The goal is to reduce setup mistakes before a template is shared with teammates or connected to real production records.',
        'The safest rollout pattern is to read the page, run one controlled test on a representative PDF, and only then expand into saved templates, Fill By Link, Search & Fill, or API Fill. That keeps the first validation loop narrow and easier to debug.',
      ];
    case 'intent':
      return [
        route.category === 'industry'
          ? `Teams usually adopt this ${route.seo.bodyContent.heading.toLowerCase()} workflow when the same document type appears repeatedly and staff need a stable template rather than ad hoc editing. The operational win comes from standardizing one canonical form type, validating it against representative records, and then reusing the saved setup.`
          : `The safest way to roll out ${route.seo.bodyContent.heading.toLowerCase()} is to start with one recurring document, turn it into a reusable template, and run one representative validation pass before anyone treats it as production-ready. That is how teams avoid creating brittle one-off automations.`,
        'Good ranking pages for this kind of workflow should answer more than what the feature is called. Operators care about setup order, QA loops, where the workflow breaks down, and which neighboring docs or industry pages explain the next step. The static page now includes those support links directly so the route carries more standalone context.',
      ];
    case 'intent-hub':
      return [
        'Hub pages work best when they act as navigation systems instead of thin category labels. Each card below points to a more specific route so Google and human readers can move from broad intent into narrower pages that match a concrete implementation task.',
        'Use these pages to choose the right entry point before you invest time in setup. If you are searching by action, start in the workflow library. If you are searching by vertical or document-heavy team, start in the industry library and move from there into the supporting docs and blog posts.',
      ];
    case 'blog-index':
      return [
        'The blog complements the workflow and docs routes by adding implementation detail, comparisons, and recurring operational examples. These posts are written to support search coverage around practical questions that appear before or after someone lands on a dedicated workflow page.',
      ];
    case 'blog-post':
      return [
        'If this guide matches your use case, the next step is not more reading. It is building one template, validating one representative record, and checking the generated PDF before rolling the workflow into repeat use.',
      ];
    case 'home':
      return [
        'The homepage is the shortest path into the overall DullyPDF workflow, but the deeper public pages are where more specific use cases live. Use the workflow, industry, docs, and blog links below to reach the route that best matches the actual document problem you are trying to solve.',
      ];
    default:
      return [];
  }
}

function renderPrimarySections(body) {
  const parts = [];

  if (body.articleSections?.length) {
    for (const section of body.articleSections) {
      parts.push('<section>');
      parts.push(`<h2>${esc(section.title)}</h2>`);
      for (const paragraph of section.paragraphs || []) {
        parts.push(`<p>${esc(paragraph)}</p>`);
      }
      if (section.bullets?.length) {
        parts.push('<ul class="seo-shell__list">');
        for (const bullet of section.bullets) {
          parts.push(`<li>${esc(bullet)}</li>`);
        }
        parts.push('</ul>');
      }
      parts.push('</section>');
    }
  }

  if (body.sections?.length) {
    parts.push('<section><div class="seo-shell__panel-grid">');
    for (const section of body.sections) {
      const heading = section.href
        ? `<a href="${esc(section.href)}">${esc(section.title)}</a>`
        : esc(section.title);
      parts.push(`<article class="seo-shell__panel"><h2>${heading}</h2><p>${esc(section.description)}</p></article>`);
    }
    parts.push('</div></section>');
  }

  if (body.sectionTitles?.length) {
    parts.push('<section><h2>Topics Covered</h2><p>This page is organized around the concrete checkpoints below so teams can move from setup to validation in a fixed order.</p><ul class="seo-shell__outline">');
    for (const title of body.sectionTitles) {
      parts.push(`<li>${esc(title)}</li>`);
    }
    parts.push('</ul></section>');
  }

  if (body.valuePoints?.length || body.proofPoints?.length) {
    parts.push('<section><div class="seo-shell__panel-grid">');
    if (body.valuePoints?.length) {
      parts.push('<article class="seo-shell__panel"><h2>What This Page Solves</h2><ul class="seo-shell__list">');
      for (const point of body.valuePoints) {
        parts.push(`<li>${esc(point)}</li>`);
      }
      parts.push('</ul></article>');
    }
    if (body.proofPoints?.length) {
      parts.push('<article class="seo-shell__panel"><h2>Evidence and Implementation Proof</h2><ul class="seo-shell__list">');
      for (const point of body.proofPoints) {
        parts.push(`<li>${esc(point)}</li>`);
      }
      parts.push('</ul></article>');
    }
    parts.push('</div></section>');
  }

  if (body.faqs?.length) {
    parts.push('<section><h2>Frequently Asked Questions</h2>');
    for (const faq of body.faqs) {
      parts.push(`<article><h3>${esc(faq.question)}</h3><p>${esc(faq.answer)}</p></article>`);
    }
    parts.push('</section>');
  }

  return parts.join('\n');
}

function renderIntentSupplement(route) {
  const current = INTENT_PAGES.find((page) => page.path === route.path);
  if (!current) return '';

  const siblingPages = (current.relatedIntentPages?.length
    ? current.relatedIntentPages.map((key) => findIntentPage(key)).filter(Boolean)
    : INTENT_PAGES.filter((page) => page.key !== current.key && page.category === current.category).slice(0, 6))
    .map((page) => ({
      label: page.navLabel,
      href: page.path,
      description: page.heroSummary,
    }));

  const docLinks = (current.relatedDocs?.length
    ? current.relatedDocs.map((key) => findUsageDocsPage(key)).filter(Boolean)
    : [
        findUsageDocsPage('getting-started'),
        findUsageDocsPage('detection'),
        findUsageDocsPage('rename-mapping'),
        findUsageDocsPage('search-fill'),
      ].filter(Boolean))
    .map((page) => ({
      label: page.title,
      href: page.path,
      description: page.summary,
    }));

  return [
    '<section>',
    '<h2>Recommended Rollout Order</h2>',
    '<p>For most teams, the stable order is: pick one recurring PDF, detect and clean the field set, map it to a representative schema, run one controlled fill pass, and only then save or share the workflow. That order keeps template quality ahead of volume.</p>',
    '<ul class="seo-shell__list">',
    '<li>Start with one canonical document layout, not every form variation at once.</li>',
    '<li>Validate names, checkbox groups, and date fields before expanding the workflow.</li>',
    '<li>Use saved templates and docs pages to keep the operating procedure repeatable for the rest of the team.</li>',
    '</ul>',
    '</section>',
    renderLinkCards('Supporting Documentation', 'These docs pages explain the exact runtime behavior behind the workflow above.', docLinks),
    renderLinkCards(
      current.category === 'industry' ? 'Related Industry Routes' : 'Related Workflow Routes',
      'Use adjacent routes to cover neighboring search intents and to compare where one workflow ends and another begins.',
      siblingPages,
    ),
  ].join('\n');
}

function renderUsageDocsSupplement(route) {
  const current = findUsageDocsPage(route.pageKey);
  if (!current) return '';

  const currentIndex = USAGE_DOCS_PAGES.findIndex((page) => page.key === route.pageKey);
  const adjacentDocs = USAGE_DOCS_PAGES
    .filter((page, index) => index !== currentIndex && Math.abs(index - currentIndex) <= 2)
    .slice(0, 4)
    .map((page) => ({
      label: page.title,
      href: page.path,
      description: page.summary,
    }));

  const relatedWorkflowKeys = current.relatedWorkflowKeys || [];
  const relatedWorkflows = relatedWorkflowKeys
    .map((key) => findIntentPage(key))
    .filter(Boolean)
    .map((page) => ({
      label: page.navLabel,
      href: page.path,
      description: page.heroSummary,
    }));

  return [
    '<section>',
    '<h2>How to Use This Docs Page</h2>',
    `<p>The goal of <strong>${esc(current.title)}</strong> is to answer one stage of the DullyPDF workflow well enough that you can run a controlled test without guessing. Read the topics above, verify them against one representative document, then move to the next linked docs or workflow page only after the current step behaves as expected.</p>`,
    '<p>That approach keeps debugging narrow. Most production issues happen when teams mix detection, mapping, fill validation, sharing, and output review into one unstructured pass. The related links below are arranged to keep that setup sequence disciplined.</p>',
    '</section>',
    '<section>',
    '<h2>Fast Validation Checklist</h2>',
    '<p>Use this short checklist when you want to turn the guidance on this page into one low-risk implementation pass instead of a broad unstructured rollout.</p>',
    '<ul class="seo-shell__list">',
    '<li>Run the step on one canonical template, not every packet variation at once.</li>',
    '<li>Validate the risky fields first: repeated names, dates, checkbox groups, and any field that drives later automation.</li>',
    '<li>Keep one representative record or respondent example nearby so the page guidance can be checked against a realistic document state.</li>',
    '<li>Move to the next docs page only after the current stage behaves predictably under one full QA loop.</li>',
    '</ul>',
    '</section>',
    renderLinkCards('Adjacent Docs', 'Move one step earlier or later in the workflow without jumping out of the public docs set.', adjacentDocs),
    renderLinkCards('Related Workflows', 'These routes connect the operational details on this docs page to the corresponding search-intent landing pages.', relatedWorkflows),
  ].join('\n');
}

function renderHubSupplement(route) {
  const category = route.pageKey === 'workflows' ? 'workflow' : 'industry';
  const pageLinks = INTENT_PAGES
    .filter((page) => page.category === category)
    .map((page) => ({
      label: page.navLabel,
      href: page.path,
      description: page.heroSummary,
    }));
  const resourceLinks = [
    { label: 'Usage Docs Overview', href: '/usage-docs', description: 'Read the full operational guide for the DullyPDF pipeline.' },
    { label: 'Getting Started', href: '/usage-docs/getting-started', description: 'Use the quick-start when you need one representative test path.' },
    { label: 'Blog', href: '/blog', description: 'Browse supporting case-study and comparison content for authority and implementation detail.' },
  ];
  return [
    renderLinkCards(
      route.pageKey === 'workflows' ? 'All Workflow Pages' : 'All Industry Pages',
      'Each route below targets a narrower use case than the hub itself, which makes it easier for searchers to reach the page that matches the document problem they actually have.',
      pageLinks,
    ),
    renderLinkCards('Supporting Resources', 'After choosing a route, use the docs and blog to validate setup order, limitations, and rollout guidance.', resourceLinks),
  ].join('\n');
}

function renderHomeSupplement() {
  const topWorkflows = INTENT_PAGES
    .filter((page) => page.category === 'workflow')
    .slice(0, 6)
    .map((page) => ({
      label: page.navLabel,
      href: page.path,
      description: page.heroSummary,
    }));
  const topResources = [
    { label: 'Usage Docs', href: '/usage-docs', description: 'Read the complete pipeline from upload through filled output.' },
    { label: 'Workflow Library', href: '/workflows', description: 'Choose the route that best matches the action you need to take.' },
    { label: 'Industry Library', href: '/industries', description: 'Browse vertical-specific pages for insurance, healthcare, HR, legal, and more.' },
    { label: 'Blog', href: '/blog', description: 'Use the blog for comparisons, walkthroughs, and repeat-workflow examples.' },
  ];
  return [
    renderLinkCards('Popular Workflow Entry Points', 'These are the public routes most likely to match high-intent searches for converting, mapping, and filling PDFs.', topWorkflows),
    renderLinkCards('Supporting Resources', 'Use these route families when you need deeper implementation detail or more specific vertical guidance.', topResources),
  ].join('\n');
}

function renderBlogIndexSupplement() {
  const postLinks = BLOG_POSTS.map((post) => ({
    label: post.title,
    href: `/blog/${post.slug}`,
    description: post.summary,
  }));
  const routeLinks = [
    { label: 'PDF to Fillable Form', href: '/pdf-to-fillable-form', description: 'Start here when the job is converting an existing PDF into a reusable template.' },
    { label: 'Fill PDF From CSV', href: '/fill-pdf-from-csv', description: 'Use this route for row-based fill workflows driven by spreadsheet or JSON records.' },
    { label: 'Rename + Mapping Docs', href: '/usage-docs/rename-mapping', description: 'Read the exact rename and schema-mapping behavior behind several blog examples.' },
  ];
  return [
    renderLinkCards('All Guides', 'Each post below is a crawlable entry point that links back into the main workflow and documentation routes.', postLinks),
    renderLinkCards('Start With These Core Routes', 'If you are new to DullyPDF, these pages usually make the best companion reads for the blog.', routeLinks),
  ].join('\n');
}

function renderBlogPostSupplement(route) {
  const post = findBlogPost(route.slug);
  if (!post) return '';

  const relatedWorkflowLinks = (post.relatedIntentPages || [])
    .map((key) => findIntentPage(key))
    .filter(Boolean)
    .map((page) => ({
      label: page.navLabel,
      href: page.path,
      description: page.heroSummary,
    }));

  const relatedDocsLinks = (post.relatedDocs || [])
    .map((key) => findUsageDocsPage(key))
    .filter(Boolean)
    .map((page) => ({
      label: page.title,
      href: page.path,
      description: page.summary,
    }));

  return [
    '<section>',
    '<h2>What to Do Next</h2>',
    '<p>Use the related workflow and docs links below to turn the ideas in this guide into one controlled implementation pass. The fastest validation loop is still one representative PDF, one representative record, and one review of the generated output before you scale the process.</p>',
    '</section>',
    '<section>',
    '<h2>Validation Checklist for This Guide</h2>',
    '<p>Most blog posts are not meant to be read in isolation. They work best when you apply the advice to one template and one realistic record immediately.</p>',
    '<ul class="seo-shell__list">',
    '<li>Pick the recurring document type that creates the most repetitive rekeying work.</li>',
    '<li>Build or reopen the template, then review geometry, names, and field-type behavior before you optimize for speed.</li>',
    '<li>Fill one representative record, inspect the risky fields, clear the output, and fill again.</li>',
    '<li>Use the related route and docs pages below when the next question becomes product setup rather than general workflow strategy.</li>',
    '</ul>',
    '</section>',
    renderLinkCards('Related Workflow Pages', 'These intent routes cover the main document problem behind this article.', relatedWorkflowLinks),
    renderLinkCards('Related Documentation', 'Use the docs pages below for product-specific setup order, limits, and QA expectations.', relatedDocsLinks),
  ].join('\n');
}

function renderSupplementalSections(route) {
  switch (route.kind) {
    case 'home':
      return renderHomeSupplement();
    case 'intent':
      return renderIntentSupplement(route);
    case 'intent-hub':
      return renderHubSupplement(route);
    case 'usage-docs':
      return renderUsageDocsSupplement(route);
    case 'blog-index':
      return renderBlogIndexSupplement();
    case 'blog-post':
      return renderBlogPostSupplement(route);
    default:
      return '';
  }
}

function renderBodyContent(route) {
  const { seo } = route;
  const body = seo.bodyContent;
  if (!body) return '';

  const parts = [
    '<main class="seo-shell__main">',
    '<section class="seo-shell__hero">',
    `<span class="seo-shell__eyebrow">${esc(route.kind.replace(/-/g, ' '))}</span>`,
    `<h1>${esc(body.heading)}</h1>`,
  ];

  if (body.paragraphs) {
    for (const paragraph of body.paragraphs) {
      parts.push(`<p>${esc(paragraph)}</p>`);
    }
  }

  for (const paragraph of buildSupplementalParagraphs(route)) {
    parts.push(`<p>${esc(paragraph)}</p>`);
  }

  parts.push('</section>');
  parts.push(renderPrimarySections(body));
  parts.push(renderSupplementalSections(route));
  parts.push(`<div class="seo-shell__cta">
    <a href="/" class="seo-shell__cta-primary">Try DullyPDF Now</a>
    <a href="/usage-docs/getting-started">Read the Getting Started Docs</a>
  </div>`);
  parts.push('</main>');

  return parts.join('\n');
}

function generatePageHtml(route, viteAssets) {
  const { seo } = route;
  const canonicalUrl = `${SITE_ORIGIN}${seo.canonicalPath}`;
  const imageUrl = `${SITE_ORIGIN}${DEFAULT_SOCIAL_IMAGE_PATH}`;
  const ogTitle = seo.ogTitle || seo.title;
  const ogDescription = seo.ogDescription || seo.description;
  const twitterTitle = seo.twitterTitle || ogTitle;
  const twitterDescription = seo.twitterDescription || ogDescription;

  const structuredDataScripts = (seo.structuredData || [])
    .map((entry, i) =>
      `<script type="application/ld+json" data-seo-jsonld="true" data-seo-jsonld-index="${i}">${JSON.stringify(entry)}</script>`
    )
    .join('\n    ');

  const bodyContent = renderBodyContent(route);
  const footerHtml = renderFooter();

  return `<!doctype html>
<html lang="en">
  <head>
    ${viteAssets.headScriptTags.join('\n    ')}
    <meta charset="UTF-8" />
    <link rel="icon" type="image/png" href="/DullyPDFLogoImproved.png" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${esc(seo.title)}</title>
    <meta name="description" content="${esc(seo.description)}" />
    <meta name="keywords" content="${esc(seo.keywords.join(', '))}" />
    <meta name="robots" content="index,follow" />
    <link rel="canonical" href="${esc(canonicalUrl)}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="DullyPDF" />
    <meta property="og:title" content="${esc(ogTitle)}" />
    <meta property="og:description" content="${esc(ogDescription)}" />
    <meta property="og:url" content="${esc(canonicalUrl)}" />
    <meta property="og:image" content="${esc(imageUrl)}" />
    <meta property="og:image:alt" content="DullyPDF logo" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${esc(twitterTitle)}" />
    <meta name="twitter:description" content="${esc(twitterDescription)}" />
    <meta name="twitter:image" content="${esc(imageUrl)}" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet" />
    <style data-seo-shell="true">${SEO_SHELL_STYLE}</style>
    ${structuredDataScripts}
    ${viteAssets.linkTags.join('\n    ')}
  </head>
  <body>
    <div id="root">
      <div class="seo-shell" data-seo-shell-visible="true">
        <div class="seo-shell__card">
          <header class="seo-shell__topbar">
            <div class="seo-shell__brand">
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF logo" class="seo-shell__brand-mark" />
              <div>
                <span class="seo-shell__brand-name">DullyPDF</span>
                <span class="seo-shell__brand-tagline">Repeat PDF workflow automation</span>
              </div>
            </div>
            ${renderTopNav()}
          </header>
          ${bodyContent}
          ${footerHtml}
        </div>
      </div>
    </div>
    ${viteAssets.scriptTags.join('\n    ')}
  </body>
</html>
`;
}

function main() {
  const indexHtmlPath = join(DIST_DIR, 'index.html');
  if (!existsSync(indexHtmlPath)) {
    console.error(`Error: ${indexHtmlPath} does not exist. Run 'npm run frontend:build:prod' first.`);
    process.exit(1);
  }

  const indexHtml = readFileSync(indexHtmlPath, 'utf-8');
  const viteAssets = extractViteAssetTags(indexHtml);

  console.log(`Extracted ${viteAssets.linkTags.length} link tags and ${viteAssets.scriptTags.length} script tags from index.html`);

  let generated = 0;
  for (const route of ALL_ROUTES) {
    const html = generatePageHtml(route, viteAssets);

    let outputPath;
    if (route.path === '/') {
      outputPath = join(DIST_DIR, 'index.html');
    } else {
      const dir = join(DIST_DIR, route.path.slice(1));
      mkdirSync(dir, { recursive: true });
      outputPath = join(dir, 'index.html');
    }

    writeFileSync(outputPath, html, 'utf-8');
    generated++;
  }

  console.log(`Generated ${generated} static HTML files in ${DIST_DIR}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}

export {
  extractViteAssetTags,
  generatePageHtml,
  renderBodyContent,
};
