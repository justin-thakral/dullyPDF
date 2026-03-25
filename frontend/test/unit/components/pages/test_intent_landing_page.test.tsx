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
});
