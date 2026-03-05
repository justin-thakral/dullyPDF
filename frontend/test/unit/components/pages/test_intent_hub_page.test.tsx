import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import IntentHubPage from '../../../../src/components/pages/IntentHubPage';

describe('IntentHubPage', () => {
  it('renders workflow hub copy and links', () => {
    render(<IntentHubPage hubKey="workflows" />);

    expect(screen.getByRole('heading', { level: 1, name: 'Workflow Library for PDF Automation' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'PDF to Fillable Form' }).getAttribute('href')).toBe('/pdf-to-fillable-form');
  });

  it('renders industry hub copy and links', () => {
    render(<IntentHubPage hubKey="industries" />);

    expect(screen.getByRole('heading', { level: 1, name: 'Industry Solutions for Repeat PDF Workflows' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Healthcare PDF Automation' }).getAttribute('href')).toBe(
      '/healthcare-pdf-automation',
    );
  });
});
