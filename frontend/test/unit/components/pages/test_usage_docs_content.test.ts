import { describe, expect, it } from 'vitest';
import { resolveUsageDocsPath, usageDocsHref } from '../../../../src/components/pages/usageDocsContent';

describe('usageDocsContent route resolver', () => {
  it('resolves canonical /usage-docs routes', () => {
    expect(resolveUsageDocsPath('/usage-docs')).toEqual({ kind: 'canonical', pageKey: 'index' });
    expect(resolveUsageDocsPath('/usage-docs/search-fill')).toEqual({ kind: 'canonical', pageKey: 'search-fill' });
    expect(resolveUsageDocsPath('/usage-docs/search-fill/')).toEqual({ kind: 'canonical', pageKey: 'search-fill' });
  });

  it('returns not-found for unknown or nested usage-docs slugs', () => {
    expect(resolveUsageDocsPath('/usage-docs/not-real')).toEqual({
      kind: 'not-found',
      requestedPath: '/usage-docs/not-real',
    });
    expect(resolveUsageDocsPath('/usage-docs/search-fill/details')).toEqual({
      kind: 'not-found',
      requestedPath: '/usage-docs/search-fill/details',
    });
  });

  it('returns redirect targets for /docs aliases', () => {
    expect(resolveUsageDocsPath('/docs')).toEqual({ kind: 'redirect', targetPath: '/usage-docs' });
    expect(resolveUsageDocsPath('/docs/search-fill')).toEqual({
      kind: 'redirect',
      targetPath: '/usage-docs/search-fill',
    });
    expect(resolveUsageDocsPath('/docs/search-fill/extra')).toEqual({
      kind: 'redirect',
      targetPath: '/usage-docs/search-fill/extra',
    });
  });

  it('builds canonical usage-docs hrefs', () => {
    expect(usageDocsHref('index')).toBe('/usage-docs');
    expect(usageDocsHref('detection')).toBe('/usage-docs/detection');
  });
});
