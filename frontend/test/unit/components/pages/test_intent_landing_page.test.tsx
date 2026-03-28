import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import IntentLandingPage from '../../../../src/components/pages/IntentLandingPage';

describe('IntentLandingPage', () => {
  it('renders requested intent copy and related links', () => {
    render(<IntentLandingPage pageKey="fillable-form-field-name" />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Standardize Fillable Form Field Names for Reliable Auto-Fill' }),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Try DullyPDF Now' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'PDF to Database Template' }).getAttribute('href')).toBe(
      '/pdf-to-database-template',
    );
  });

  it('renders long-form article sections for expanded landing pages', () => {
    render(<IntentLandingPage pageKey="fill-pdf-from-csv" />);

    expect(
      screen.getByRole('heading', { level: 2, name: 'How Search and Fill works once the template is mapped' }),
    ).toBeTruthy();
    expect(
      screen.getByText(/DullyPDF treats the PDF template and the row data as two separate layers/i),
    ).toBeTruthy();
  });

  it('uses targeted supporting docs from the shared SEO dataset', () => {
    render(<IntentLandingPage pageKey="pdf-fill-api" />);

    expect(screen.getByRole('link', { name: 'API Fill' }).getAttribute('href')).toBe('/usage-docs/api-fill');
    expect(screen.getByRole('link', { name: 'Rename + Mapping' }).getAttribute('href')).toBe(
      '/usage-docs/rename-mapping',
    );
  });

  it('renders inline legal footnotes and the numbered source list for authority-style pages', () => {
    render(<IntentLandingPage pageKey="esign-ueta-pdf-workflow" />);

    expect(screen.getByRole('heading', { level: 2, name: 'Legal footnotes and sources' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /See legal footnote/i }).length).toBeGreaterThan(5);
    expect(screen.getByRole('link', { name: 'See legal footnote 1a' }).getAttribute('href')).toBe('#footnote-esign-7001');
    expect(screen.getByRole('link', { name: 'See legal footnote 1b' }).getAttribute('href')).toBe('#footnote-esign-7001');
    expect(
      screen.getByRole('link', { name: '15 U.S.C. § 7001 | General rule of validity and related provisions' }).getAttribute('href'),
    ).toBe('https://www.law.cornell.edu/uscode/text/15/7001');
    expect(
      screen.getByRole('link', { name: '21 CFR Part 11 | Electronic records and electronic signatures' }).getAttribute('href'),
    ).toBe('https://www.law.cornell.edu/cfr/text/21/part-11');
    expect(
      screen.getByRole('link', { name: 'Back to first reference for footnote 1a' }).getAttribute('href'),
    ).toBe('#footnote-ref-esign-7001-1');
  });
});
