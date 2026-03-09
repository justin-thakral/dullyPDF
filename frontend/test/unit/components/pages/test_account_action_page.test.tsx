import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const verifyEmailActionMocks = vi.hoisted(() => ({
  applyEmailVerificationCode: vi.fn(),
  verifyPasswordResetActionCode: vi.fn(),
  confirmPasswordReset: vi.fn(),
}));

vi.mock('../../../../src/services/auth', () => ({
  Auth: {
    applyEmailVerificationCode: verifyEmailActionMocks.applyEmailVerificationCode,
    verifyPasswordResetActionCode: verifyEmailActionMocks.verifyPasswordResetActionCode,
    confirmPasswordReset: verifyEmailActionMocks.confirmPasswordReset,
  },
}));

import AccountActionPage from '../../../../src/components/pages/AccountActionPage';

describe('AccountActionPage', () => {
  beforeEach(() => {
    verifyEmailActionMocks.applyEmailVerificationCode.mockReset();
    verifyEmailActionMocks.verifyPasswordResetActionCode.mockReset();
    verifyEmailActionMocks.confirmPasswordReset.mockReset();
    verifyEmailActionMocks.applyEmailVerificationCode.mockResolvedValue(undefined);
    verifyEmailActionMocks.verifyPasswordResetActionCode.mockResolvedValue('reset@example.com');
    verifyEmailActionMocks.confirmPasswordReset.mockResolvedValue(undefined);
    window.history.replaceState({}, '', '/account-action');
  });

  it('applies the verification code, strips noisy query params, and renders a continue CTA', async () => {
    window.history.replaceState(
      {},
      '',
      '/account-action?mode=verifyEmail&oobCode=test-code&continueUrl=https%3A%2F%2Fdullypdf.com%2Fprofile%3Fverified%3D1',
    );

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Email verified' })).toBeTruthy();
    });

    expect(verifyEmailActionMocks.applyEmailVerificationCode).toHaveBeenCalledWith('test-code');
    expect(window.location.pathname).toBe('/account-action');
    expect(window.location.search).toBe('');
    expect(screen.getByRole('link', { name: 'Continue to DullyPDF' }).getAttribute('href')).toBe(
      '/profile?verified=1',
    );
  });

  it('renders a reset-password form for valid reset links and submits the new password', async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      '',
      '/account-action?mode=resetPassword&oobCode=reset-code&continueUrl=https%3A%2F%2Fdullypdf.com%2Fprofile',
    );

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Choose a new password' })).toBeTruthy();
    });
    expect(verifyEmailActionMocks.verifyPasswordResetActionCode).toHaveBeenCalledWith('reset-code');
    expect(window.location.pathname).toBe('/account-action');
    expect(window.location.search).toBe('');

    await user.type(screen.getByLabelText('New password'), 'new-secret-123');
    await user.type(screen.getByLabelText('Confirm new password'), 'new-secret-123');
    await user.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Password updated' })).toBeTruthy();
    });
    expect(verifyEmailActionMocks.confirmPasswordReset).toHaveBeenCalledWith('reset-code', 'new-secret-123');
    expect(screen.getByRole('link', { name: 'Sign in to DullyPDF' }).getAttribute('href')).toBe('/');
  });

  it('validates password reset form input before calling Firebase', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/account-action?mode=resetPassword&oobCode=reset-code');

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Choose a new password' })).toBeTruthy();
    });

    await user.type(screen.getByLabelText('New password'), 'short');
    await user.type(screen.getByLabelText('Confirm new password'), 'different');
    await user.click(screen.getByRole('button', { name: 'Reset password' }));

    expect(screen.getByText('Use at least 8 characters for your new password.')).toBeTruthy();
    expect(verifyEmailActionMocks.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it('renders a clear error state for invalid links', async () => {
    window.history.replaceState({}, '', '/account-action?mode=verifyEmail');

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'We could not verify this email' })).toBeTruthy();
    });

    expect(
      screen.getByText('This verification link is invalid, expired, or has already been used.'),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open DullyPDF' }).getAttribute('href')).toBe('/');
  });

  it('surfaces verification failures from Firebase and preserves the stored clean route on refresh', async () => {
    window.history.replaceState({}, '', '/account-action?mode=verifyEmail&oobCode=expired-code');
    verifyEmailActionMocks.applyEmailVerificationCode.mockRejectedValueOnce(new Error('expired'));

    const { unmount } = render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByText('This verification link is invalid, expired, or has already been used.')).toBeTruthy();
    });
    unmount();

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'We could not verify this email' })).toBeTruthy();
    });
    expect(window.location.pathname).toBe('/account-action');
    expect(window.location.search).toBe('');
  });

  it('normalizes legacy /verify-email links onto /account-action before rendering the clean route', async () => {
    window.history.replaceState({}, '', '/verify-email?mode=verifyEmail&oobCode=test-code');

    render(<AccountActionPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Email verified' })).toBeTruthy();
    });

    expect(window.location.pathname).toBe('/account-action');
    expect(window.location.search).toBe('');
  });
});
