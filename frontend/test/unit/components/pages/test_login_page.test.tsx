import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const loginMocks = vi.hoisted(() => ({
  signIn: vi.fn(),
  signUp: vi.fn(),
  sendPasswordReset: vi.fn(),
  trackGoogleAdsSignup: vi.fn(),
  getAdditionalUserInfo: vi.fn(),
  verifyRecaptcha: vi.fn(),
  loadRecaptcha: vi.fn(),
  getRecaptchaToken: vi.fn(),
  enableRecaptchaBadge: vi.fn(),
  disableRecaptchaBadge: vi.fn(),
  uiGetInstance: vi.fn(),
  uiStart: vi.fn(),
  uiReset: vi.fn(),
  authUiCtor: vi.fn(),
}));

vi.mock('../../../../src/services/auth', () => ({
  Auth: {
    signIn: loginMocks.signIn,
    signUp: loginMocks.signUp,
    sendPasswordReset: loginMocks.sendPasswordReset,
  },
}));

vi.mock('../../../../src/services/api', () => ({
  ApiService: {
    verifyRecaptcha: loginMocks.verifyRecaptcha,
  },
}));

vi.mock('../../../../src/utils/recaptcha', () => ({
  loadRecaptcha: loginMocks.loadRecaptcha,
  getRecaptchaToken: loginMocks.getRecaptchaToken,
  enableRecaptchaBadge: loginMocks.enableRecaptchaBadge,
  disableRecaptchaBadge: loginMocks.disableRecaptchaBadge,
}));

vi.mock('../../../../src/services/firebaseClient', () => ({
  firebaseAuth: {},
}));

vi.mock('../../../../src/utils/googleAds', () => ({
  trackGoogleAdsSignup: loginMocks.trackGoogleAdsSignup,
}));

vi.mock('firebase/auth', () => ({
  getAdditionalUserInfo: loginMocks.getAdditionalUserInfo,
  GithubAuthProvider: { PROVIDER_ID: 'github.com' },
  GoogleAuthProvider: { PROVIDER_ID: 'google.com' },
}));

vi.mock('firebaseui', () => {
  class AuthUI {
    static getInstance = loginMocks.uiGetInstance;
    start = loginMocks.uiStart;
    reset = loginMocks.uiReset;

    constructor(auth: unknown) {
      loginMocks.authUiCtor(auth);
    }
  }

  return {
    auth: {
      AuthUI,
      CredentialHelper: {
        NONE: 'NONE',
      },
    },
  };
});

vi.mock('firebaseui/dist/firebaseui.css', () => ({}));

import LoginPage from '../../../../src/components/pages/LoginPage';

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', 'site-key');
    vi.stubEnv('VITE_SIGNUP_REQUIRE_RECAPTCHA', 'true');

    loginMocks.signIn.mockResolvedValue({});
    loginMocks.signUp.mockResolvedValue({ uid: 'user-signup-123' });
    loginMocks.sendPasswordReset.mockResolvedValue(undefined);
    loginMocks.trackGoogleAdsSignup.mockReset();
    loginMocks.getAdditionalUserInfo.mockReset().mockReturnValue({ isNewUser: false });
    loginMocks.verifyRecaptcha.mockResolvedValue({ success: true });
    loginMocks.loadRecaptcha.mockResolvedValue(undefined);
    loginMocks.getRecaptchaToken.mockResolvedValue('token-123');
    loginMocks.uiGetInstance.mockReturnValue(null);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('toggles between sign-in and sign-up modes and clears transient form state', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    expect(screen.getByRole('heading', { name: 'Sign in to DullyPDF' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Forgot password?' }));
    expect(screen.getByText('Enter your email so we can send the reset link.')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: "Don't have an account? Sign up" }));

    expect(screen.getByRole('heading', { name: 'Create account for DullyPDF' })).toBeTruthy();
    expect(screen.queryByText('Enter your email so we can send the reset link.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Forgot password?' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Already have an account? Sign in' }));
    expect(screen.getByRole('heading', { name: 'Sign in to DullyPDF' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Forgot password?' })).toBeTruthy();
  });

  it('submits email/password sign-in and calls onAuthenticated after success', async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    render(<LoginPage onAuthenticated={onAuthenticated} />);

    await user.type(screen.getByLabelText('Email'), '  user@example.com ');
    await user.type(screen.getByLabelText('Password'), '  secret123 ');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(loginMocks.signIn).toHaveBeenCalledWith('user@example.com', 'secret123');
    });
    expect(onAuthenticated).toHaveBeenCalledTimes(1);
  });

  it('enforces signup reCAPTCHA and runs verification before sign-up when configured', async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    render(<LoginPage onAuthenticated={onAuthenticated} />);

    await user.click(screen.getByRole('button', { name: "Don't have an account? Sign up" }));
    await waitFor(() => {
      expect(loginMocks.loadRecaptcha).toHaveBeenCalledWith('site-key');
    });

    await user.type(screen.getByLabelText('Email'), '  new@example.com ');
    await user.type(screen.getByLabelText('Password'), '  password123 ');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => {
      expect(loginMocks.getRecaptchaToken).toHaveBeenCalledWith('site-key', 'signup');
      expect(loginMocks.verifyRecaptcha).toHaveBeenCalledWith({
        token: 'token-123',
        action: 'signup',
      });
      expect(loginMocks.signUp).toHaveBeenCalledWith('new@example.com', 'password123');
      expect(loginMocks.trackGoogleAdsSignup).toHaveBeenCalledWith('user-signup-123');
    });

    expect(screen.getByText('Verification email sent. Check your inbox before continuing.')).toBeTruthy();
    expect(onAuthenticated).toHaveBeenCalledTimes(1);
  });

  it('blocks signup submit when reCAPTCHA is required but site key is missing', async () => {
    const user = userEvent.setup();
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', '');
    vi.stubEnv('VITE_SIGNUP_REQUIRE_RECAPTCHA', 'true');

    render(<LoginPage />);

    await user.click(screen.getByRole('button', { name: "Don't have an account? Sign up" }));

    const createButton = screen.getByRole('button', { name: 'Create account' }) as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);
    expect(screen.getByText('reCAPTCHA is required but not configured.')).toBeTruthy();

    await user.click(createButton);

    expect(loginMocks.signUp).not.toHaveBeenCalled();
    expect(loginMocks.verifyRecaptcha).not.toHaveBeenCalled();
    expect(loginMocks.getRecaptchaToken).not.toHaveBeenCalled();
  });

  it('validates forgot-password email input and shows success messaging', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole('button', { name: 'Forgot password?' }));
    expect(screen.getByText('Enter your email so we can send the reset link.')).toBeTruthy();

    await user.type(screen.getByLabelText('Email'), 'reset@example.com');
    await user.click(screen.getByRole('button', { name: 'Forgot password?' }));

    await waitFor(() => {
      expect(loginMocks.sendPasswordReset).toHaveBeenCalledWith('reset@example.com');
    });

    expect(screen.getByText('Password reset link sent. Check your inbox for instructions.')).toBeTruthy();
  });

  it('shows friendly forgot-password error when auth reset fails', async () => {
    const user = userEvent.setup();
    loginMocks.sendPasswordReset.mockRejectedValueOnce({ code: 'auth/user-not-found' });

    render(<LoginPage />);

    await user.type(screen.getByLabelText('Email'), 'missing@example.com');
    await user.click(screen.getByRole('button', { name: 'Forgot password?' }));

    await waitFor(() => {
      expect(screen.getByText('Invalid email or password. Please try again.')).toBeTruthy();
    });
  });

  it('bootstraps firebaseui and resets UI instance during mode changes and unmount', async () => {
    const user = userEvent.setup();
    const existingUi = {
      start: vi.fn(),
      reset: vi.fn(),
    };
    loginMocks.uiGetInstance.mockReturnValue(existingUi);

    const { unmount } = render(<LoginPage />);

    expect(loginMocks.authUiCtor).not.toHaveBeenCalled();
    expect(existingUi.start).toHaveBeenCalledWith(
      '#firebaseui-auth-container',
      expect.objectContaining({
        signInFlow: 'popup',
        callbacks: expect.objectContaining({
          signInSuccessWithAuthResult: expect.any(Function),
          signInFailure: expect.any(Function),
        }),
      }),
    );
    expect(existingUi.reset).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: "Don't have an account? Sign up" }));

    await waitFor(() => {
      expect(existingUi.start).toHaveBeenCalledTimes(2);
    });
    expect(existingUi.reset.mock.calls.length).toBeGreaterThanOrEqual(3);

    unmount();
    expect(existingUi.reset.mock.calls.length).toBeGreaterThanOrEqual(4);
  });

  it('tracks native OAuth signup conversions only for new FirebaseUI users', async () => {
    const onAuthenticated = vi.fn();
    render(<LoginPage onAuthenticated={onAuthenticated} />);

    const firebaseUiConfig = loginMocks.uiStart.mock.calls[0]?.[1];
    const signInSuccess = firebaseUiConfig?.callbacks?.signInSuccessWithAuthResult;
    expect(typeof signInSuccess).toBe('function');

    loginMocks.getAdditionalUserInfo.mockReturnValueOnce({ isNewUser: true });
    const firstResult = signInSuccess({ user: { uid: 'oauth-new-user' } });
    expect(firstResult).toBe(false);
    expect(loginMocks.trackGoogleAdsSignup).toHaveBeenCalledWith('oauth-new-user');
    expect(onAuthenticated).toHaveBeenCalledTimes(1);

    loginMocks.getAdditionalUserInfo.mockReturnValueOnce({ isNewUser: false });
    const secondResult = signInSuccess({ user: { uid: 'oauth-existing-user' } });
    expect(secondResult).toBe(false);
    expect(loginMocks.trackGoogleAdsSignup).toHaveBeenCalledTimes(1);
    expect(onAuthenticated).toHaveBeenCalledTimes(2);
  });
});
