import { describe, expect, it } from 'vitest';
import { getIntentPages } from '../../../src/config/intentPages';
import { getBlogPost } from '../../../src/config/blogPosts';
import { getBlogPostSeo } from '../../../src/config/blogSeo';
import { INDEXABLE_PUBLIC_ROUTE_PATHS, resolveRouteSeo } from '../../../src/config/routeSeo';
import { ALL_ROUTES, INTENT_PAGES as STATIC_INTENT_PAGES } from '../../../../scripts/seo-route-data.mjs';

describe('routeSeo config', () => {
  it('keeps indexable canonical paths unique', () => {
    const unique = new Set(INDEXABLE_PUBLIC_ROUTE_PATHS);
    expect(unique.size).toBe(INDEXABLE_PUBLIC_ROUTE_PATHS.length);
  });

  it('resolves canonical homepage metadata', () => {
    const metadata = resolveRouteSeo({ kind: 'app' });
    expect(metadata.canonicalPath).toBe('/');
    expect(metadata.title).toContain('PDF to Fillable Form');
    expect(metadata.keywords).toContain('pdf form builder');
  });

  it('resolves canonical usage docs metadata by page key', () => {
    const metadata = resolveRouteSeo({ kind: 'usage-docs', pageKey: 'search-fill' });
    expect(metadata.canonicalPath).toBe('/usage-docs/search-fill');
    expect(metadata.title).toContain('Auto Fill PDF');
  });

  it('resolves dedicated Create Group docs metadata', () => {
    const metadata = resolveRouteSeo({ kind: 'usage-docs', pageKey: 'create-group' });
    expect(metadata.canonicalPath).toBe('/usage-docs/create-group');
    expect(metadata.title).toContain('Create Group');
  });

  it('resolves dedicated signature docs metadata', () => {
    const metadata = resolveRouteSeo({ kind: 'usage-docs', pageKey: 'signature-workflow' });
    expect(metadata.canonicalPath).toBe('/usage-docs/signature-workflow');
    expect(metadata.title).toContain('Signature');
  });

  it('resolves dedicated API Fill docs metadata', () => {
    const metadata = resolveRouteSeo({ kind: 'usage-docs', pageKey: 'api-fill' });
    expect(metadata.canonicalPath).toBe('/usage-docs/api-fill');
    expect(metadata.title).toContain('API Fill');
  });

  it('resolves canonical intent metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent', intentKey: 'healthcare-pdf-automation' });
    expect(metadata.canonicalPath).toBe('/healthcare-pdf-automation');
    expect(metadata.title).toContain('Healthcare');
  });

  it('resolves signature workflow intent metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent', intentKey: 'pdf-signature-workflow' });
    expect(metadata.canonicalPath).toBe('/pdf-signature-workflow');
    expect(metadata.title).toContain('Signature');
  });

  it('resolves API Fill intent metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent', intentKey: 'pdf-fill-api' });
    expect(metadata.canonicalPath).toBe('/pdf-fill-api');
    expect(metadata.title).toContain('API');
  });

  it('uses the hero copy for intent titles and appends breadcrumb schema', () => {
    const metadata = resolveRouteSeo({ kind: 'intent', intentKey: 'fill-pdf-from-csv' });
    expect(metadata.title).toBe('Fill PDF From CSV, Excel, or JSON Data | DullyPDF');
    expect(
      metadata.structuredData?.some(
        (entry) => entry['@type'] === 'BreadcrumbList',
      ),
    ).toBe(true);
  });

  it('resolves canonical hub metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent-hub', hubKey: 'workflows' });
    expect(metadata.canonicalPath).toBe('/workflows');
    expect(metadata.title).toContain('Workflow Library');
  });

  it('resolves feature plan metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'feature-plan', planKey: 'premium-features' });
    expect(metadata.canonicalPath).toBe('/premium-features');
    expect(metadata.title).toContain('Premium');
  });

  it('keeps build-time static routes aligned with the runtime indexable route list', () => {
    const runtimePaths = [...INDEXABLE_PUBLIC_ROUTE_PATHS].sort();
    const staticPaths = ALL_ROUTES.map((route) => route.path).sort();
    expect(staticPaths).toEqual(runtimePaths);
  });

  it('keeps build-time intent content aligned with the runtime intent page config', () => {
    const runtimeIntentPages = getIntentPages().map((page) => JSON.parse(JSON.stringify(page)));
    const staticIntentPages = STATIC_INTENT_PAGES.map((page) => JSON.parse(JSON.stringify(page)));
    expect(staticIntentPages).toEqual(runtimeIntentPages);
  });

  it('adds blog article and breadcrumb structured data with the modified date', () => {
    const post = getBlogPost('auto-fill-pdf-from-spreadsheet');
    expect(post).toBeTruthy();
    const metadata = getBlogPostSeo(post!);
    expect(
      metadata.structuredData?.some(
        (entry) => entry['@type'] === 'BlogPosting' && entry['dateModified'] === '2026-03-24',
      ),
    ).toBe(true);
    expect(
      metadata.structuredData?.some((entry) => entry['@type'] === 'BreadcrumbList'),
    ).toBe(true);
  });
});
