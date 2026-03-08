import { describe, expect, it } from 'vitest';
import { INDEXABLE_PUBLIC_ROUTE_PATHS, resolveRouteSeo } from '../../../src/config/routeSeo';
import { ALL_ROUTES } from '../../../../scripts/seo-route-data.mjs';

describe('routeSeo config', () => {
  it('keeps indexable canonical paths unique', () => {
    const unique = new Set(INDEXABLE_PUBLIC_ROUTE_PATHS);
    expect(unique.size).toBe(INDEXABLE_PUBLIC_ROUTE_PATHS.length);
  });

  it('resolves canonical homepage metadata', () => {
    const metadata = resolveRouteSeo({ kind: 'app' });
    expect(metadata.canonicalPath).toBe('/');
    expect(metadata.title).toContain('PDFs to Fillable Forms');
    expect(metadata.keywords).toContain('pdf form builder');
  });

  it('resolves canonical usage docs metadata by page key', () => {
    const metadata = resolveRouteSeo({ kind: 'usage-docs', pageKey: 'search-fill' });
    expect(metadata.canonicalPath).toBe('/usage-docs/search-fill');
    expect(metadata.title).toContain('Auto Fill PDF');
  });

  it('resolves canonical intent metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent', intentKey: 'healthcare-pdf-automation' });
    expect(metadata.canonicalPath).toBe('/healthcare-pdf-automation');
    expect(metadata.title).toContain('Healthcare');
  });

  it('resolves canonical hub metadata by key', () => {
    const metadata = resolveRouteSeo({ kind: 'intent-hub', hubKey: 'workflows' });
    expect(metadata.canonicalPath).toBe('/workflows');
    expect(metadata.title).toContain('Workflow Library');
  });

  it('keeps build-time static routes aligned with the runtime indexable route list', () => {
    const runtimePaths = [...INDEXABLE_PUBLIC_ROUTE_PATHS].sort();
    const staticPaths = ALL_ROUTES.map((route) => route.path).sort();
    expect(staticPaths).toEqual(runtimePaths);
  });
});
