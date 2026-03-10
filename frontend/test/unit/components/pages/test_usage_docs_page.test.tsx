import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import UsageDocsPage from '../../../../src/components/pages/UsageDocsPage';

describe('UsageDocsPage', () => {
  it('renders overview page with sidebar page links and section anchors', () => {
    render(<UsageDocsPage pageKey="index" />);

    expect(screen.getByRole('heading', { name: 'DullyPDF Usage Docs' })).toBeTruthy();
    const sidebar = screen.getByLabelText('Usage docs sidebar');
    expect(within(sidebar).getByRole('link', { name: 'Getting Started' }).getAttribute('href')).toBe(
      '/usage-docs/getting-started',
    );
    expect(within(sidebar).getByRole('link', { name: 'Detection' }).getAttribute('href')).toBe('/usage-docs/detection');
    expect(document.querySelector('section#pipeline-overview')).toBeTruthy();
    expect(document.querySelector('section#before-you-start')).toBeTruthy();
  });

  it('renders subroute content and marks active page in sidebar', () => {
    render(<UsageDocsPage pageKey="rename-mapping" />);

    expect(screen.getByRole('heading', { name: 'Rename + Mapping' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'OpenAI data boundaries' })).toBeTruthy();

    const activePageLink = screen.getByRole('link', { name: 'Rename + Mapping' });
    expect(activePageLink.className.includes('usage-docs-sidebar__page--active')).toBe(true);
  });

  it('renders dedicated Fill By Link docs content', () => {
    render(<UsageDocsPage pageKey="fill-by-link" />);

    expect(screen.getByRole('heading', { name: 'Fill By Link' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Owner publishing flow' })).toBeTruthy();
    expect(screen.getByText(/post-submit button/i)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Fill PDF By Link' }).getAttribute('href')).toBe('/fill-pdf-by-link');
  });

  it('updates document title based on page key', () => {
    const { rerender } = render(<UsageDocsPage pageKey="index" />);
    expect(document.title).toBe('PDF Form Automation Docs and Workflow Guide | DullyPDF');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/usage-docs');

    rerender(<UsageDocsPage pageKey="search-fill" />);
    expect(document.title).toBe('Auto Fill PDF from CSV, Excel, JSON, or Fill By Link Respondents | DullyPDF Docs');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/usage-docs/search-fill');
  });
});
