import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BlogPostPage from '../../../../src/components/pages/BlogPostPage';

describe('BlogPostPage', () => {
  it('renders visible publish/update dates and inline workflow links for a real post', () => {
    render(<BlogPostPage slug="auto-fill-pdf-from-spreadsheet" />);

    expect(screen.getByRole('heading', { name: 'How to Auto-Fill PDF Forms From a Spreadsheet (CSV or Excel)' })).toBeTruthy();
    expect(screen.getByText('Published')).toBeTruthy();
    expect(screen.getByText('Last updated')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'How to validate this workflow in DullyPDF' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'Fill PDF From CSV' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Search & Fill' }).length).toBeGreaterThan(0);
    expect(
      Array.from(document.querySelectorAll('script[data-seo-jsonld="true"]')).some((node) =>
        node.textContent?.includes('"@type":"BreadcrumbList"'),
      ),
    ).toBe(true);
  });

  it('applies noindex metadata when the requested blog slug does not exist', () => {
    render(<BlogPostPage slug="not-a-real-post" />);

    expect(screen.getByRole('heading', { name: 'Post not found' })).toBeTruthy();
    expect(screen.getByText('/blog/not-a-real-post')).toBeTruthy();
    expect(document.title).toBe('Blog Post Not Found (404) | DullyPDF');
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,follow');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/blog');
  });
});
