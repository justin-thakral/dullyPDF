import { describe, expect, it } from 'vitest';
import {
  getIntentPage,
  getIntentPages,
  resolveIntentPath,
} from '../../../src/config/intentPages';

describe('intentPages config', () => {
  it('keeps intent paths unique', () => {
    const paths = getIntentPages().map((page) => page.path);
    const unique = new Set(paths);
    expect(unique.size).toBe(paths.length);
  });

  it('resolves canonical intent routes', () => {
    expect(resolveIntentPath('/pdf-to-fillable-form')).toBe('pdf-to-fillable-form');
    expect(resolveIntentPath('/fillable-form-field-name/')).toBe('fillable-form-field-name');
    expect(resolveIntentPath('/pdf-signature-workflow')).toBe('pdf-signature-workflow');
    expect(resolveIntentPath('/esign-ueta-pdf-workflow')).toBe('esign-ueta-pdf-workflow');
    expect(resolveIntentPath('/pdf-fill-api')).toBe('pdf-fill-api');
    expect(resolveIntentPath('/pdf-radio-button-editor')).toBe('pdf-radio-button-editor');
    expect(resolveIntentPath('/healthcare-pdf-automation')).toBe('healthcare-pdf-automation');
    expect(resolveIntentPath('/acord-form-automation')).toBe('acord-form-automation');
    expect(resolveIntentPath('/not-an-intent')).toBeNull();
  });

  it('contains SEO and FAQ data for every intent page', () => {
    getIntentPages().forEach((page) => {
      expect(page.seoTitle.length).toBeGreaterThan(10);
      expect(page.seoDescription.length).toBeGreaterThan(20);
      expect(page.seoKeywords.length).toBeGreaterThan(1);
      expect(page.faqs.length).toBeGreaterThan(0);
      expect(getIntentPage(page.key).path).toBe(page.path);
    });
  });

  it('keeps legal footnotes on the signing authority pages', () => {
    const workflowPage = getIntentPage('pdf-signature-workflow');
    const legalPage = getIntentPage('esign-ueta-pdf-workflow');

    expect(workflowPage.footnotes?.length ?? 0).toBeGreaterThan(3);
    expect(legalPage.footnotes?.length ?? 0).toBeGreaterThan(6);
    expect(legalPage.footnotes?.some((footnote) => footnote.label.includes('21 CFR Part 11'))).toBe(true);
  });
});
