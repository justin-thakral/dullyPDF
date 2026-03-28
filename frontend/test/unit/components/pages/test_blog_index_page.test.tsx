import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BlogIndexPage from '../../../../src/components/pages/BlogIndexPage';

describe('BlogIndexPage', () => {
  it('renders shared hero and support content', () => {
    render(<BlogIndexPage />);

    expect(screen.getByRole('heading', { level: 1, name: 'PDF Automation Guides & Tutorials' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'How to use these guides' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Rename + Mapping Docs' }).getAttribute('href')).toBe(
      '/usage-docs/rename-mapping',
    );
  });
});
