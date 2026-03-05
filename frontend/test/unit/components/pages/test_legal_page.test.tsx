import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import LegalPage from '../../../../src/components/pages/LegalPage';

describe('LegalPage', () => {
  it('renders privacy copy with active privacy navigation and metadata', () => {
    render(<LegalPage kind="privacy" />);

    expect(screen.getByRole('heading', { name: 'Privacy Policy' })).toBeTruthy();
    expect(screen.getByText('Last updated: February 24, 2026')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Billing and payments' })).toBeTruthy();

    const privacyLink = screen.getByRole('link', { name: 'Privacy' });
    const termsLink = screen.getByRole('link', { name: 'Terms' });
    const usageDocsLinks = screen.getAllByRole('link', { name: 'Usage Docs' });
    expect(privacyLink.className.includes('legal-nav__link--active')).toBe(true);
    expect(termsLink.className.includes('legal-nav__link--active')).toBe(false);
    expect(usageDocsLinks.some((link) => link.getAttribute('href') === '/usage-docs')).toBe(true);

    expect(screen.getByText(/justin@dullypdf\.com/i)).toBeTruthy();
  });

  it('renders terms copy with active terms navigation', () => {
    render(<LegalPage kind="terms" />);

    expect(screen.getByRole('heading', { name: 'Terms of Service' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Billing and subscriptions' })).toBeTruthy();

    const privacyLink = screen.getByRole('link', { name: 'Privacy' });
    const termsLink = screen.getByRole('link', { name: 'Terms' });
    const usageDocsLinks = screen.getAllByRole('link', { name: 'Usage Docs' });
    expect(privacyLink.className.includes('legal-nav__link--active')).toBe(false);
    expect(termsLink.className.includes('legal-nav__link--active')).toBe(true);
    expect(usageDocsLinks.some((link) => link.getAttribute('href') === '/usage-docs')).toBe(true);
  });

  it('updates document title per legal page kind', () => {
    const { rerender } = render(<LegalPage kind="privacy" />);
    expect(document.title).toBe('Privacy Policy | DullyPDF');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/privacy');

    rerender(<LegalPage kind="terms" />);
    expect(document.title).toBe('Terms of Service | DullyPDF');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/terms');
  });

  it('renders legal section ids for in-page anchors', () => {
    const { rerender } = render(<LegalPage kind="privacy" />);

    expect(document.querySelector('section#information-we-collect')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Information we collect' })).toBeTruthy();

    rerender(<LegalPage kind="terms" />);

    expect(document.querySelector('section#acceptable-use')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Acceptable use' })).toBeTruthy();
  });
});
