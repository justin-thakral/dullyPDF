import React, { useMemo, useState } from 'react';
import type { FirebaseError } from 'firebase/app';
import './LoginPage.css';
import { Auth } from '../../services/auth';

interface LoginPageProps {
  onAuthenticated?: () => void;
  onCancel?: () => void;
}

type AuthMode = 'signin' | 'signup';

const INITIAL_STATE = {
  email: '',
  password: '',
  confirmPassword: '',
  displayName: '',
};

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
    default:
      return fbError.message || (mode === 'signup'
        ? 'Unable to create your account right now. Please try again later.'
        : 'Unable to sign you in right now. Please try again later.');
  }
}

const LoginPage: React.FC<LoginPageProps> = ({ onAuthenticated, onCancel }) => {
  const [mode, setMode] = useState<AuthMode>('signin');
  const [form, setForm] = useState(INITIAL_STATE);
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const title = useMemo(() => (mode === 'signin' ? 'Welcome back' : 'Create your account'), [mode]);
  const subtitle = useMemo(
    () => (mode === 'signin'
      ? 'Use your credentials to access the PDF template workspace.'
      : 'Start building precise PDF templates with AI-assisted tooling.'),
    [mode],
  );

  const handleChange = (field: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const resetMessages = () => {
    setError(null);
    setInfo(null);
  };

  const handleModeChange = (nextMode: AuthMode) => {
    if (nextMode === mode) return;
    setMode(nextMode);
    resetMessages();
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    resetMessages();

    if (mode === 'signup' && form.password !== form.confirmPassword) {
      setError('Passwords do not match. Please confirm and try again.');
      return;
    }

    setIsSubmitting(true);
    try {
      if (mode === 'signin') {
        await Auth.signIn(form.email.trim(), form.password);
      } else {
        await Auth.signUp(form.email.trim(), form.password, form.displayName.trim());
      }
      onAuthenticated?.();
    } catch (err) {
      setError(getFriendlyError(err, mode));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleForgotPassword = async () => {
    resetMessages();
    if (!form.email.trim()) {
      setError('Enter your email address first so we can send the reset link.');
      return;
    }
    try {
      await Auth.sendPasswordReset(form.email.trim());
      setInfo('Password reset link sent. Check your inbox for further instructions.');
    } catch (err) {
      setError(getFriendlyError(err, mode));
    }
  };

  return (
    <div className="auth-page">
        <div className="auth-wrapper">
        <div className="auth-brand">
          <img className="auth-logo-image" src="/DullyPDF.png" alt="DullyPDF" />
          <h1>DullyPDF</h1>
          <p>AI-aligned PDF templates with trusted data mapping.</p>
        </div>

        <div className="auth-card">
          <div className="auth-header">
            <div className="auth-tabs">
              <button
                type="button"
                className={mode === 'signin' ? 'tab active' : 'tab'}
                onClick={() => handleModeChange('signin')}
              >
                Sign in
              </button>
              <button
                type="button"
                className={mode === 'signup' ? 'tab active' : 'tab'}
                onClick={() => handleModeChange('signup')}
              >
                Create account
              </button>
            </div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {mode === 'signup' && (
              <div className="form-field">
                <label htmlFor="displayName">Name</label>
                <input
                  id="displayName"
                  type="text"
                  placeholder="How should we address you?"
                  value={form.displayName}
                  onChange={handleChange('displayName')}
                />
              </div>
            )}

            <div className="form-field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={form.email}
                onChange={handleChange('email')}
                required
              />
            </div>

            <div className="form-field">
              <label htmlFor="password">Password</label>
              <div className="password-field">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                  placeholder={mode === 'signin' ? 'Enter your password' : 'Create a secure password'}
                  value={form.password}
                  onChange={handleChange('password')}
                  required
                />
                <button
                  type="button"
                  className="toggle-password"
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>

            {mode === 'signup' && (
              <div className="form-field">
                <label htmlFor="confirmPassword">Confirm password</label>
                <input
                  id="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Re-enter your password"
                  value={form.confirmPassword}
                  onChange={handleChange('confirmPassword')}
                  required
                />
              </div>
            )}

            {error && <div className="form-alert error">{error}</div>}
            {info && <div className="form-alert info">{info}</div>}

            <button type="submit" className="primary-action" disabled={isSubmitting}>
              {isSubmitting ? 'Just a moment…' : mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          <div className="auth-footer">
            {onCancel && (
              <button type="button" className="text-link text-link--cancel" onClick={onCancel}>
                Back to homepage
              </button>
            )}
            <button type="button" className="text-link" onClick={handleForgotPassword}>
              Forgot password?
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
