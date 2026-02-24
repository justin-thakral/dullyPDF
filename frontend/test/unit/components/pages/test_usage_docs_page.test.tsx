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

  it('shows not-found notice when unknown slug is provided', () => {
    render(<UsageDocsPage pageKey="index" unknownSlug="not-real" />);

    expect(screen.getByText(/Could not find a page for/i)).toBeTruthy();
    expect(screen.getByText('not-real')).toBeTruthy();
  });

  it('updates document title based on page key', () => {
    const { rerender } = render(<UsageDocsPage pageKey="index" />);
    expect(document.title).toBe('Usage Docs | DullyPDF');

    rerender(<UsageDocsPage pageKey="search-fill" />);
    expect(document.title).toBe('Search & Fill | Usage Docs | DullyPDF');
  });
});
