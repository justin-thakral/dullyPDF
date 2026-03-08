import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import PublicNotFoundPage from '../../../../src/components/pages/PublicNotFoundPage';

describe('PublicNotFoundPage', () => {
  it('renders public 404 content and applies noindex metadata', () => {
    render(<PublicNotFoundPage requestedPath="/not-a-real-page" />);

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeTruthy();
    expect(screen.getByText('/not-a-real-page')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Go to Homepage' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'Browse Workflows' }).getAttribute('href')).toBe('/workflows');
    expect(screen.getByRole('link', { name: 'Open Usage Docs' }).getAttribute('href')).toBe('/usage-docs');
    expect(document.title).toBe('Page Not Found (404) | DullyPDF');
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,follow');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/');
  });
});
