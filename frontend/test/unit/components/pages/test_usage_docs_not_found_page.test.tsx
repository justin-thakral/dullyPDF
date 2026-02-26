import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import UsageDocsNotFoundPage from '../../../../src/components/pages/UsageDocsNotFoundPage';

describe('UsageDocsNotFoundPage', () => {
  it('renders docs 404 content and applies noindex metadata', () => {
    render(<UsageDocsNotFoundPage requestedPath="/usage-docs/not-a-real-page" />);

    expect(screen.getByRole('heading', { name: 'Usage docs page not found' })).toBeTruthy();
    expect(screen.getByText('/usage-docs/not-a-real-page')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Go to Usage Docs Overview' }).getAttribute('href')).toBe('/usage-docs');
    expect(document.title).toBe('Usage Docs Not Found (404) | DullyPDF');
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,follow');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/usage-docs');
  });
});
