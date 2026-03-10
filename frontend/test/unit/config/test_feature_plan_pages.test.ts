import { describe, expect, it } from 'vitest';
import {
  getFeaturePlanPage,
  getFeaturePlanPages,
  resolveFeaturePlanPath,
} from '../../../src/config/featurePlanPages';

describe('featurePlanPages config', () => {
  it('keeps feature plan paths unique', () => {
    const paths = getFeaturePlanPages().map((page) => page.path);
    const unique = new Set(paths);
    expect(unique.size).toBe(paths.length);
  });

  it('resolves canonical feature plan routes', () => {
    expect(resolveFeaturePlanPath('/free-features')).toBe('free-features');
    expect(resolveFeaturePlanPath('/premium-features/')).toBe('premium-features');
    expect(resolveFeaturePlanPath('/not-a-plan')).toBeNull();
  });

  it('contains seo and faq data for every plan page', () => {
    getFeaturePlanPages().forEach((page) => {
      expect(page.seoTitle.length).toBeGreaterThan(10);
      expect(page.seoDescription.length).toBeGreaterThan(20);
      expect(page.seoKeywords.length).toBeGreaterThan(1);
      expect(page.faqs.length).toBeGreaterThan(0);
      expect(getFeaturePlanPage(page.key).path).toBe(page.path);
    });
  });
});
