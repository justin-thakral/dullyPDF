import { describe, expect, it } from 'vitest';
import { applyNoIndexSeo, applyRouteSeo } from '../../../src/utils/seo';

describe('SEO metadata utility', () => {
  it('applies title, canonical, and social tags for homepage route', () => {
    applyRouteSeo({ kind: 'app' });

    expect(document.title).toBe('DullyPDF | Convert PDFs to Fillable Forms & Map to Database');
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toContain(
      'DullyPDF is a PDF form builder for existing documents',
    );
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/');
    expect(document.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe('https://dullypdf.com/');
    expect(document.querySelector('meta[name="twitter:title"]')?.getAttribute('content')).toBe(
      'DullyPDF | Convert PDFs to Fillable Forms & Map to Database',
    );
    expect(document.querySelectorAll('script[data-seo-jsonld="true"]').length).toBeGreaterThan(0);
  });

  it('applies canonical usage-docs paths even when docs content is section-specific', () => {
    applyRouteSeo({ kind: 'usage-docs', pageKey: 'rename-mapping' });

    expect(document.title).toBe('Map PDF Fields to Database Template Columns | DullyPDF Docs');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      'https://dullypdf.com/usage-docs/rename-mapping',
    );
    expect(document.querySelector('meta[property="og:title"]')?.getAttribute('content')).toBe(
      'Map PDF Fields to Database Template Columns | DullyPDF Docs',
    );
    expect(document.querySelector('meta[name="twitter:description"]')?.getAttribute('content')).toContain(
      'OpenAI rename and schema mapping',
    );
  });

  it('can apply noindex metadata for non-canonical routes', () => {
    applyRouteSeo({ kind: 'intent', intentKey: 'pdf-to-fillable-form' });
    expect(document.querySelectorAll('script[data-seo-jsonld="true"]').length).toBeGreaterThan(0);

    applyNoIndexSeo({
      title: 'Usage Docs Not Found (404) | DullyPDF',
      description: 'No usage docs page exists at this path.',
      canonicalPath: '/usage-docs',
    });

    expect(document.title).toBe('Usage Docs Not Found (404) | DullyPDF');
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toBe(
      'No usage docs page exists at this path.',
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,follow');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/usage-docs');
    expect(document.querySelectorAll('script[data-seo-jsonld="true"]').length).toBe(0);
  });
});
