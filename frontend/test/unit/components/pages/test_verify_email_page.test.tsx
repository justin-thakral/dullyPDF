import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const verifyEmailMocks = vi.hoisted(() => ({
  sendVerificationEmail: vi.fn(),
}));

vi.mock('../../../../src/services/auth', () => ({
  Auth: {
    sendVerificationEmail: verifyEmailMocks.sendVerificationEmail,
  },
}));

import VerifyEmailPage from '../../../../src/components/pages/VerifyEmailPage';

const createDeferred = <T,>() => {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe('VerifyEmailPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    verifyEmailMocks.sendVerificationEmail.mockReset();
    verifyEmailMocks.sendVerificationEmail.mockResolvedValue(undefined);
  });

  it('handles resend verification success with loading/disabled state', async () => {
    const user = userEvent.setup();
    const deferred = createDeferred<void>();
    verifyEmailMocks.sendVerificationEmail.mockReturnValueOnce(deferred.promise);

    render(<VerifyEmailPage email="verify@example.com" />);

    await user.click(screen.getByRole('button', { name: 'Resend verification email' }));

    const sendingButton = screen.getByRole('button', { name: 'Sending…' }) as HTMLButtonElement;
    expect(sendingButton.disabled).toBe(true);

    deferred.resolve();

    await waitFor(() => {
      expect(screen.getByText('Verification email sent. Check your inbox and spam folder.')).toBeTruthy();
    });
  });

  it('shows an error message when resend verification fails', async () => {
    const user = userEvent.setup();
    verifyEmailMocks.sendVerificationEmail.mockRejectedValueOnce(new Error('send failed'));

    render(<VerifyEmailPage email="verify@example.com" />);

    await user.click(screen.getByRole('button', { name: 'Resend verification email' }));

    await waitFor(() => {
      expect(
        screen.getByText('Unable to resend the verification email. Please try again shortly.'),
      ).toBeTruthy();
    });
  });

  it('handles refresh verification success with loading/disabled state', async () => {
    const user = userEvent.setup();
    const deferred = createDeferred<void>();
    const onRefresh = vi.fn().mockReturnValueOnce(deferred.promise);

    render(<VerifyEmailPage email="refresh@example.com" onRefresh={onRefresh} />);

    await user.click(screen.getByRole('button', { name: 'I have verified' }));

    const checkingButton = screen.getByRole('button', { name: 'Checking…' }) as HTMLButtonElement;
    expect(checkingButton.disabled).toBe(true);
    expect(onRefresh).toHaveBeenCalledTimes(1);

    deferred.resolve();

    await waitFor(() => {
      const readyButton = screen.getByRole('button', { name: 'I have verified' }) as HTMLButtonElement;
      expect(readyButton.disabled).toBe(false);
    });
  });

  it('shows an error message when refresh verification fails', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockRejectedValueOnce(new Error('not verified'));

    render(<VerifyEmailPage email="refresh@example.com" onRefresh={onRefresh} />);

    await user.click(screen.getByRole('button', { name: 'I have verified' }));

    await waitFor(() => {
      expect(screen.getByText('We could not confirm verification yet. Please try again.')).toBeTruthy();
    });
  });

  it('wires sign-out callback and falls back to generic email copy', async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn();
    const { rerender } = render(<VerifyEmailPage onSignOut={onSignOut} />);

    expect(screen.getByText('your email address')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(onSignOut).toHaveBeenCalledTimes(1);

    rerender(<VerifyEmailPage email="real@example.com" onSignOut={onSignOut} />);
    expect(screen.getByText('real@example.com')).toBeTruthy();
  });
});
