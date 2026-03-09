#!/usr/bin/env node
/**
 * Static HTML generator for DullyPDF SEO.
 *
 * Reads dist/index.html (after Vite build) to extract asset tags, then generates
 * a standalone HTML file per public route with correct meta tags, JSON-LD,
 * and semantic body content. Firebase Hosting serves these static files directly;
 * React loads on top for interactivity.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { ALL_ROUTES, SITE_ORIGIN, DEFAULT_SOCIAL_IMAGE_PATH, FOOTER_LINKS } from './seo-route-data.mjs';

const DIST_DIR = resolve(process.cwd(), 'frontend/dist');

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

  // Extract <link> tags (stylesheets, modulepreload) from <head>
  const linkTags = [];
  const linkRegex = /<link\s[^>]*(?:rel="(?:stylesheet|modulepreload)")[^>]*\/?>/gi;
  let match;
  while ((match = linkRegex.exec(indexHtml)) !== null) {
    // Skip font and favicon links — we add those ourselves
    if (match[0].includes('fonts.googleapis.com') || match[0].includes('fonts.gstatic.com') || match[0].includes('icon')) continue;
    linkTags.push(match[0]);
  }

  // Extract <script> tags from <body> (Vite module scripts)
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

// ---------------------------------------------------------------------------
// Generate body content HTML from route data
// ---------------------------------------------------------------------------

function renderBodyContent(route) {
  const { seo, kind } = route;
  const body = seo.bodyContent;
  if (!body) return '';

  const parts = [];

  parts.push(`<h1>${esc(body.heading)}</h1>`);

  if (body.paragraphs) {
    for (const p of body.paragraphs) {
      parts.push(`<p>${esc(p)}</p>`);
    }
  }

  if (body.sections) {
    for (const section of body.sections) {
      parts.push(`<section><h2>${esc(section.title)}</h2><p>${esc(section.description)}</p></section>`);
    }
  }

  if (body.sectionTitles) {
    parts.push('<section><h2>Topics covered</h2><ul>');
    for (const title of body.sectionTitles) {
      parts.push(`<li>${esc(title)}</li>`);
    }
    parts.push('</ul></section>');
  }

  if (body.valuePoints) {
    parts.push('<section><h2>What this page solves</h2><ul>');
    for (const point of body.valuePoints) {
      parts.push(`<li>${esc(point)}</li>`);
    }
    parts.push('</ul></section>');
  }

  if (body.proofPoints) {
    parts.push('<section><h2>Evidence and implementation proof</h2><ul>');
    for (const point of body.proofPoints) {
      parts.push(`<li>${esc(point)}</li>`);
    }
    parts.push('</ul></section>');
  }

  if (body.faqs) {
    parts.push('<section><h2>Frequently asked questions</h2>');
    for (const faq of body.faqs) {
      parts.push(`<h3>${esc(faq.question)}</h3><p>${esc(faq.answer)}</p>`);
    }
    parts.push('</section>');
  }

  // CTA
  parts.push(`<p><a href="/">Try DullyPDF Now</a> | <a href="/usage-docs/getting-started">Getting Started Docs</a></p>`);

  return parts.join('\n');
}

// ---------------------------------------------------------------------------
// Render footer HTML
// ---------------------------------------------------------------------------

function renderFooter() {
  const parts = [];
  parts.push('<footer>');
  parts.push('<nav aria-label="Site navigation">');

  const renderColumn = (title, links) => {
    parts.push(`<div><strong>${esc(title)}</strong><ul>`);
    for (const link of links) {
      parts.push(`<li><a href="${esc(link.href)}">${esc(link.label)}</a></li>`);
    }
    parts.push('</ul></div>');
  };

  renderColumn('Product', FOOTER_LINKS.product);
  renderColumn('Workflows', FOOTER_LINKS.workflows);
  renderColumn('Industries', FOOTER_LINKS.industries);
  renderColumn('Resources', FOOTER_LINKS.resources);
  renderColumn('Legal', FOOTER_LINKS.legal);

  parts.push('</nav>');
  parts.push(`<p>\u00A9 ${new Date().getFullYear()} DullyPDF</p>`);
  parts.push('</footer>');
  return parts.join('\n');
}

// ---------------------------------------------------------------------------
// Generate a full HTML page for a route
// ---------------------------------------------------------------------------

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
    ${structuredDataScripts}
    ${viteAssets.linkTags.join('\n    ')}
  </head>
  <body>
    <div id="root">
      <div class="seo-shell" style="display:none">${bodyContent}
      ${footerHtml}</div>
    </div>
    ${viteAssets.scriptTags.join('\n    ')}
  </body>
</html>
`;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  const indexHtmlPath = join(DIST_DIR, 'index.html');
  if (!existsSync(indexHtmlPath)) {
    console.error(`Error: ${indexHtmlPath} does not exist. Run 'npm run build' first.`);
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
      // e.g., /healthcare-pdf-automation → dist/healthcare-pdf-automation/index.html
      const dir = join(DIST_DIR, route.path.slice(1));
      mkdirSync(dir, { recursive: true });
      outputPath = join(dir, 'index.html');
    }

    writeFileSync(outputPath, html, 'utf-8');
    generated++;
  }

  console.log(`Generated ${generated} static HTML files in ${DIST_DIR}`);
}

main();
