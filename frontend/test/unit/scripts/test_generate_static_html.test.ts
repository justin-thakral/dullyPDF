import { describe, expect, it } from 'vitest';
import { ALL_ROUTES } from '../../../../scripts/seo-route-data.mjs';
import {
  extractViteAssetTags,
  generateAppShellHtml,
  generatePageHtml,
} from '../../../../scripts/generate-static-html.mjs';

const EMPTY_VITE_ASSETS = {
  headScriptTags: [],
  linkTags: [],
  scriptTags: [],
};

describe('generate-static-html', () => {
  it('renders prerendered route markup inside the React root', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/fill-pdf-from-csv');
    expect(route).toBeTruthy();

    const html = generatePageHtml(
      route!,
      EMPTY_VITE_ASSETS,
      '<main><h1>Fill PDF From CSV, SQL, Excel, or JSON Data</h1><a href="/">Try DullyPDF Now</a></main>',
    );

    expect(html).toContain('data-seo-jsonld="true"');
    expect(html).toContain('Fill PDF From CSV, SQL, Excel, or JSON Data');
    expect(html).toContain('Try DullyPDF Now');
    expect(html).toContain('<div id="root"><main><h1>Fill PDF From CSV, SQL, Excel, or JSON Data</h1><a href="/">Try DullyPDF Now</a></main></div>');
  });

  it('adds the homepage-only hydration cover tags', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS, '<main>Homepage prerender</main>');

    expect(html).toContain('data-homepage-hydration-cover="true"');
    expect(html).not.toContain("data-homepage-hydration-cover', 'active'");
    expect(html).toContain('#homepage-hydration-cover {');
    expect(html).toContain('<div id="homepage-hydration-cover" aria-hidden="true"></div>');
  });

  it('does not leak the dev homepage cover bootstrap into shared Vite head assets', () => {
    const assets = extractViteAssetTags(`<!doctype html>
<html lang="en">
  <head>
    <style data-homepage-hydration-cover="true">html[data-homepage-hydration-cover="active"] #homepage-hydration-cover {}</style>
    <script data-homepage-hydration-cover="true">document.documentElement.setAttribute('data-homepage-hydration-cover', 'active');</script>
    <script>window.__otherBootstrap = true;</script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/assets/main.js"></script>
  </body>
</html>`);

    expect(assets.headScriptTags).toEqual(['<script>window.__otherBootstrap = true;</script>']);
  });

  it('generates a neutral app shell for rewrite routes', () => {
    const appShell = generateAppShellHtml(`<!doctype html>
<html lang="en">
  <head>
    <style data-homepage-hydration-cover="true">#homepage-hydration-cover {}</style>
    <script data-homepage-hydration-cover="true">document.getElementById('homepage-hydration-cover')?.remove();</script>
    <script data-app-route-hydration-cover="true">document.documentElement.setAttribute('data-app-route-hydration-cover', 'active');</script>
  </head>
  <body>
    <div id="homepage-hydration-cover" aria-hidden="true"></div>
    <div id="root"></div>
    <script type="module" src="/assets/main.js"></script>
  </body>
</html>`);

    expect(appShell).not.toContain('data-homepage-hydration-cover="true"');
    expect(appShell).toContain('data-app-route-hydration-cover="true"');
    expect(appShell).toContain('<div id="root"></div>');
    expect(appShell).not.toContain('homepage-hydration-cover');
  });

  it('includes head SEO signals for usage docs pages', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/usage-docs/getting-started');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS, '<main>Usage docs prerender</main>');

    expect(html).toContain('<title>');
    expect(html).toContain('name="description"');
    expect(html).toContain('rel="canonical"');
  });

  it('includes head SEO signals for blog index', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/blog');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS, '<main>Blog prerender</main>');

    expect(html).toContain('<title>');
    expect(html).toContain('name="description"');
    expect(html).toContain('data-seo-jsonld="true"');
  });
});
