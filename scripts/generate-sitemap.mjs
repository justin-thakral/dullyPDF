#!/usr/bin/env node
/**
 * Auto-generate sitemap.xml from seo-route-data.mjs.
 * Writes to frontend/dist/sitemap.xml (must run after Vite build).
 */

import { writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { ALL_ROUTES, SITE_ORIGIN } from './seo-route-data.mjs';

const DIST_DIR = resolve(process.cwd(), 'frontend/dist');
const TODAY = new Date().toISOString().slice(0, 10); // YYYY-MM-DD

function getPriority(route) {
  if (route.kind === 'home') return '1.0';
  if (route.kind === 'legal') return '0.5';
  if (route.kind === 'usage-docs') return route.pageKey === 'index' ? '0.8' : '0.7';
  if (route.kind === 'intent') return route.category === 'workflow' ? '0.9' : '0.8';
  if (route.kind === 'blog-index') return '0.8';
  if (route.kind === 'blog-post') return '0.7';
  return '0.5';
}

function getChangefreq(route) {
  if (route.kind === 'home') return 'weekly';
  if (route.kind === 'legal') return 'yearly';
  if (route.kind === 'usage-docs') return route.pageKey === 'index' ? 'weekly' : 'monthly';
  if (route.kind === 'intent') return 'weekly';
  if (route.kind === 'blog-index') return 'weekly';
  if (route.kind === 'blog-post') return 'monthly';
  return 'monthly';
}

function escXml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function main() {
  const entries = ALL_ROUTES.map((route) => {
    const loc = route.path === '/' ? `${SITE_ORIGIN}/` : `${SITE_ORIGIN}${route.path}`;
    return `  <url>
    <loc>${escXml(loc)}</loc>
    <lastmod>${TODAY}</lastmod>
    <changefreq>${getChangefreq(route)}</changefreq>
    <priority>${getPriority(route)}</priority>
  </url>`;
  });

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries.join('\n')}
</urlset>
`;

  const outputPath = join(DIST_DIR, 'sitemap.xml');
  writeFileSync(outputPath, xml, 'utf-8');
  console.log(`Generated sitemap.xml with ${entries.length} URLs at ${outputPath}`);
}

main();
