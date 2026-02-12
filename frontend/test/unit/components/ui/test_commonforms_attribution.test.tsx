import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CommonFormsAttribution } from '../../../../src/components/ui/CommonFormsAttribution';

describe('CommonFormsAttribution', () => {
  it('renders the default attribution label', () => {
    render(<CommonFormsAttribution />);

    const link = screen.getByRole('link', { name: 'jbarrow' });
    const container = link.closest('span') as HTMLSpanElement;
    expect(container.textContent?.replace(/\s+/g, ' ').trim()).toBe('CommonForms by jbarrow');
  });

  it('renders suffix text when provided', () => {
    render(<CommonFormsAttribution suffix="field detection" />);

    const link = screen.getByRole('link', { name: 'jbarrow' });
    const container = link.closest('span') as HTMLSpanElement;
    expect(container.textContent?.replace(/\s+/g, ' ').trim()).toBe('CommonForms field detection by jbarrow');
  });

  it('uses the expected external link URL and safety attributes', () => {
    render(<CommonFormsAttribution />);

    const link = screen.getByRole('link', { name: 'jbarrow' });
    expect(link.getAttribute('href')).toBe('https://github.com/jbarrow/commonforms');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noreferrer');
    expect(link.getAttribute('rel')).toContain('noopener');
  });
});
