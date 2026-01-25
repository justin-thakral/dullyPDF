/**
 * Auth page for email/password sign-in with FirebaseUI for OAuth providers.
 */
import React, { useEffect, useRef, useState } from 'react';
import type { FirebaseError } from 'firebase/app';
import { GithubAuthProvider, GoogleAuthProvider } from 'firebase/auth';
import * as firebaseui from 'firebaseui';
import 'firebaseui/dist/firebaseui.css';
import './LoginPage.css';
import { firebaseAuth } from '../../services/firebaseClient';
import { Auth } from '../../services/auth';
import { ApiService } from '../../api';
import { ApiError } from '../../services/apiConfig';
import {
  disableRecaptchaBadge,
  enableRecaptchaBadge,
  getRecaptchaToken,
  loadRecaptcha,
} from '../../utils/recaptcha';
import { Alert } from '../ui/Alert';

interface LoginPageProps {
  onAuthenticated?: () => void;
  onCancel?: () => void;
}

type AuthMode = 'signin' | 'signup';

const INITIAL_STATE = {
  email: '',
  password: '',
};

/**
 * Map Firebase errors into user-friendly messages.
 */
function getFriendlyError(error: unknown, mode: AuthMode): string {
  if (!error) return 'Something went wrong. Please try again.';
  const fbError = error as FirebaseError & { message?: string };
  switch (fbError.code) {
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
      return 'Invalid email or password. Please try again.';
    case 'auth/email-already-in-use':
      return 'An account already exists with this email address.';
    case 'auth/weak-password':
      return 'Password must be at least 6 characters long.';
    case 'auth/too-many-requests':
      return 'Too many attempts. Please wait a moment and try again.';
    case 'auth/account-exists-with-different-credential':
      return 'An account already exists with a different sign-in method. Try that provider.';
    default:
      return fbError.message || (mode === 'signup'
        ? 'Unable to create your account right now. Please try again later.'
        : 'Unable to sign you in right now. Please try again later.');
  }
}

/**
 * Render the authentication UI with a custom email/password form and provider buttons.
 */
const LoginPage: React.FC<LoginPageProps> = ({ onAuthenticated, onCancel }) => {
  const uiRef = useRef<firebaseui.auth.AuthUI | null>(null);
  const [mode, setMode] = useState<AuthMode>('signin');
  const [form, setForm] = useState(INITIAL_STATE);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const recaptchaSiteKey =
    typeof import.meta.env.VITE_RECAPTCHA_SITE_KEY === 'string'
      ? import.meta.env.VITE_RECAPTCHA_SITE_KEY.trim()
      : '';
  const signupRecaptchaRequired = (() => {
    const raw = typeof import.meta.env.VITE_SIGNUP_REQUIRE_RECAPTCHA === 'string'
      ? import.meta.env.VITE_SIGNUP_REQUIRE_RECAPTCHA.trim().toLowerCase()
      : '';
    if (raw) {
      return !['0', 'false', 'no'].includes(raw);
    }
    return true;
  })();
  const signupRecaptchaBlocked = mode === 'signup' && signupRecaptchaRequired && !recaptchaSiteKey;

  useEffect(() => {
    const ui = firebaseui.auth.AuthUI.getInstance() || new firebaseui.auth.AuthUI(firebaseAuth);
    uiRef.current = ui;
    ui.reset();

    const uiConfig: firebaseui.auth.Config = {
      signInFlow: 'popup',
      credentialHelper: firebaseui.auth.CredentialHelper.NONE,
      signInOptions: [
        GoogleAuthProvider.PROVIDER_ID,
        {
          provider: GithubAuthProvider.PROVIDER_ID,
          scopes: ['user:email'],
        },
      ],
      callbacks: {
        signInSuccessWithAuthResult: () => {
          setError(null);
          setInfo(null);
          onAuthenticated?.();
          return false;
        },
        signInFailure: (authError) => {
          setError(getFriendlyError(authError, mode));
          return Promise.resolve();
        },
      },
    };

    ui.start('#firebaseui-auth-container', uiConfig);

    return () => {
      ui.reset();
    };
  }, [mode, onAuthenticated]);

  useEffect(() => {
    if (mode !== 'signup' || !signupRecaptchaRequired || !recaptchaSiteKey) return;
    loadRecaptcha(recaptchaSiteKey).catch(() => {
      setError('reCAPTCHA failed to load. Please refresh and try again.');
    });
  }, [mode, recaptchaSiteKey, signupRecaptchaRequired]);

  useEffect(() => {
    if (mode === 'signup' && signupRecaptchaRequired) {
      enableRecaptchaBadge('signup');
    } else {
      disableRecaptchaBadge('signup');
    }
    return () => {
      disableRecaptchaBadge('signup');
    };
  }, [mode, signupRecaptchaRequired]);

  const handleChange = (field: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
    setError(null);
    setInfo(null);
  };

  const handleToggleMode = () => {
    setMode((prev) => (prev === 'signin' ? 'signup' : 'signin'));
    setError(null);
    setInfo(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);

    setIsSubmitting(true);
    try {
      const email = form.email.trim();
      const password = form.password.trim();
      if (mode === 'signup' && signupRecaptchaRequired) {
        if (!recaptchaSiteKey) {
          setError('reCAPTCHA is required but not configured.');
          return;
        }
        setInfo('Verifying reCAPTCHA...');
        const token = await getRecaptchaToken(recaptchaSiteKey, 'signup');
        await ApiService.verifyRecaptcha({ token, action: 'signup' });
      }
      setInfo(null);
      if (mode === 'signin') {
        await Auth.signIn(email, password);
      } else {
        await Auth.signUp(email, password);
        setInfo('Verification email sent. Check your inbox before continuing.');
      }
      onAuthenticated?.();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(getFriendlyError(err, mode));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleForgotPassword = async () => {
    setError(null);
    setInfo(null);
    const email = form.email.trim();
    if (!email) {
      setError('Enter your email so we can send the reset link.');
      return;
    }
    try {
      await Auth.sendPasswordReset(email);
      setInfo('Password reset link sent. Check your inbox for instructions.');
    } catch (err) {
      setError(getFriendlyError(err, mode));
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <img className="auth-logo-image" src="/DullyPDFLogoImproved.png" alt="DullyPDF" />
          <div className="auth-brand-text">
            <h1>DullyPDF</h1>
            <p>AI-aligned PDF templates with trusted data mapping.</p>
          </div>
        </div>

        <div className="auth-panel">
          <div className="auth-header">
            <span className="auth-pill">Secure access</span>
            <h2>{mode === 'signin' ? 'Sign in to DullyPDF' : 'Create account for DullyPDF'}</h2>
            <p>
              Use email/password or continue with Google or GitHub. Email verification is required
              for password accounts.
            </p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="auth-email">Email</label>
              <input
                id="auth-email"
                name="auth-email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={form.email}
                onChange={handleChange('email')}
                required
              />
            </div>
            <div className="auth-field">
              <label htmlFor="auth-password">Password</label>
              <input
                id="auth-password"
                name="auth-password"
                type="password"
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                placeholder={mode === 'signin' ? 'Enter your password' : 'Create a password'}
                value={form.password}
                onChange={handleChange('password')}
                required
              />
            </div>

            <button type="submit" className="primary-action" disabled={isSubmitting || signupRecaptchaBlocked}>
              {isSubmitting ? 'Just a moment…' : mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
            {mode === 'signup' && signupRecaptchaRequired ? (
              <p className="auth-recaptcha-note">
                {signupRecaptchaBlocked ? 'reCAPTCHA is required but not configured.' : 'Protected by reCAPTCHA Enterprise.'}
              </p>
            ) : null}
          </form>

          <div className="auth-links">
            {mode === 'signin' ? (
              <button type="button" className="text-link" onClick={handleForgotPassword}>
                Forgot password?
              </button>
            ) : null}
            <button type="button" className="text-link" onClick={handleToggleMode}>
              {mode === 'signin' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
            </button>
          </div>

          {error || info ? (
            <div className="auth-alerts">
              {error ? <Alert tone="error" variant="inline" message={error} /> : null}
              {info ? <Alert tone="info" variant="inline" message={info} /> : null}
            </div>
          ) : null}

          <div className="auth-divider">
            <span>Or continue with</span>
          </div>

          <div id="firebaseui-auth-container" className="firebaseui-shell" />

          <div className="auth-footer">
            {onCancel && (
              <button type="button" className="text-link text-link--cancel" onClick={onCancel}>
                Back to homepage
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
