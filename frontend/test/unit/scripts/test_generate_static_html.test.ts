import { describe, expect, it } from 'vitest';
import { ALL_ROUTES } from '../../../../scripts/seo-route-data.mjs';
import { generatePageHtml } from '../../../../scripts/generate-static-html.mjs';

const EMPTY_VITE_ASSETS = {
  headScriptTags: [],
  linkTags: [],
  scriptTags: [],
};

describe('generate-static-html', () => {
  it('renders a visible static shell instead of hidden prerender content', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/fill-pdf-from-csv');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS);

    expect(html).toContain('data-seo-shell-visible="true"');
    expect(html).not.toContain('display:none');
    expect(html).toContain('Supporting Documentation');
  });

  it('renders richer usage docs support sections in static HTML', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/usage-docs/getting-started');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS);

    expect(html).toContain('How to Use This Docs Page');
    expect(html).toContain('Adjacent Docs');
    expect(html).toContain('/usage-docs/rename-mapping');
  });

  it('renders blog index links to individual posts in static HTML', () => {
    const route = ALL_ROUTES.find((entry) => entry.path === '/blog');
    expect(route).toBeTruthy();

    const html = generatePageHtml(route!, EMPTY_VITE_ASSETS);

    expect(html).toContain('/blog/how-to-convert-pdf-to-fillable-form');
    expect(html).toContain('All Guides');
  });
});
