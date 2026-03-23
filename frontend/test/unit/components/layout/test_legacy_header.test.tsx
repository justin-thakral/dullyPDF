import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LegacyHeader from '../../../../src/components/layout/LegacyHeader';

type LegacyHeaderProps = ComponentProps<typeof LegacyHeader>;

function createProps(overrides: Partial<LegacyHeaderProps> = {}): LegacyHeaderProps {
  return {
    currentView: 'homepage',
    onNavigateHome: vi.fn(),
    showBackButton: false,
    userEmail: null,
    onOpenProfile: undefined,
    onSignOut: undefined,
    onSignIn: vi.fn(),
    ...overrides,
  };
}

describe('LegacyHeader', () => {
  it.each([
    [
      'homepage',
      'PDF Form Generator',
      'Transform PDFs into interactive forms with AI-powered field detection',
    ],
    ['upload', 'Upload PDF Document', 'Select a PDF file to begin automatic form field detection'],
    ['processing', 'Processing Document', 'Analyzing document and detecting form fields using AI'],
    ['editor', 'Form Field Editor', 'Review and edit detected form fields with precision tools'],
  ] as const)('maps %s view to title and description', (currentView, expectedTitle, expectedDescription) => {
    render(<LegacyHeader {...createProps({ currentView })} />);

    expect(screen.getByRole('heading', { name: expectedTitle })).toBeTruthy();
    expect(screen.getByText(expectedDescription)).toBeTruthy();
  });

  it('conditionally renders back button and sign-in control for anonymous users', async () => {
    const user = userEvent.setup();
    const onNavigateHome = vi.fn();
    const onSignIn = vi.fn();

    render(
      <LegacyHeader
        {...createProps({
          currentView: 'upload',
          showBackButton: true,
          onNavigateHome,
          onSignIn,
          userEmail: null,
          onOpenProfile: undefined,
          onSignOut: undefined,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Return to homepage' }));
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(onNavigateHome).toHaveBeenCalledTimes(1);
    expect(onSignIn).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('conditionally renders profile and sign-out controls for authenticated users', async () => {
    const user = userEvent.setup();
    const onOpenProfile = vi.fn();
    const onSignOut = vi.fn();
    const { rerender } = render(
      <LegacyHeader
        {...createProps({
          currentView: 'editor',
          userEmail: 'person@example.com',
          onOpenProfile,
          onSignOut,
          onSignIn: undefined,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: /person@example\.com/i }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(onOpenProfile).toHaveBeenCalledTimes(1);
    expect(onSignOut).toHaveBeenCalledTimes(1);

    rerender(
      <LegacyHeader
        {...createProps({
          currentView: 'editor',
          userEmail: 'person@example.com',
          onOpenProfile: undefined,
          onSignOut,
          onSignIn: undefined,
        })}
      />,
    );

    expect(screen.queryByRole('button', { name: /person@example\.com/i })).toBeNull();
    expect(screen.getByText('person@example.com')).toBeTruthy();
  });

  it('shows Sign in copy while auth is pending', () => {
    render(<LegacyHeader {...createProps({ authPending: true })} />);

    const pendingControl = document.querySelector('.header-auth-pending');
    expect(pendingControl?.textContent?.trim()).toBe('Sign in');
    expect(pendingControl?.getAttribute('aria-busy')).toBe('true');
  });

  it('renders branding assets and combined docs/legal navigation link', () => {
    render(<LegacyHeader {...createProps()} />);

    const docsLink = screen.getByRole('link', { name: 'Docs & Privacy & Terms' });
    expect(docsLink.getAttribute('href')).toBe('/usage-docs');

    const headerLinks = screen
      .getAllByRole('link')
      .filter((element) => element.className.includes('header-link-button'));
    expect(headerLinks.map((element) => element.textContent?.trim())).toEqual(['Docs & Privacy & Terms']);

    expect(screen.getByRole('img', { name: 'DullyPDF' })).toBeTruthy();
    expect(screen.getAllByText('DullyPDF').length).toBeGreaterThan(0);
  });
});
