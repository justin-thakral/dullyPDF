import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import '../../styles/ui-buttons.css';
import './VerifyEmailPage.css';
import './AccountActionPage.css';
import { Auth } from '../../services/auth';
import { Alert } from '../ui/Alert';
import { applyNoIndexSeo } from '../../utils/seo';
import {
  ACCOUNT_ACTION_ROUTE_PATH,
  parseEmailActionSearch,
  readStoredEmailActionState,
  writeStoredEmailActionState,
} from '../../utils/emailActions';
import AuthActionShell from './AuthActionShell';

type AccountActionState =
  | { kind: 'processing-verify-email'; continuePath: string }
  | { kind: 'verify-email-success'; continuePath: string }
  | {
      kind: 'ready-reset-password';
      continuePath: string;
      email: string;
      oobCode: string;
    }
  | { kind: 'submitting-reset-password'; continuePath: string; email: string; oobCode: string }
  | { kind: 'reset-password-success'; continuePath: string; email: string }
  | { kind: 'error'; continuePath: string; message: string };

type ActionLink = {
  href: string;
  label: string;
};

const VERIFY_EMAIL_SUCCESS_MESSAGE = 'Your email address has been verified. You can continue to DullyPDF now.';
const INVALID_LINK_MESSAGE = 'This verification link is invalid, expired, or has already been used.';
const UNSUPPORTED_LINK_MESSAGE = 'This email link is not supported by this page.';
const HELP_ACTION: ActionLink = {
  href: '/usage-docs/getting-started',
  label: 'Open setup guide',
};

const AccountActionPage = () => {
  const [state, setState] = useState<AccountActionState>({
    kind: 'processing-verify-email',
    continuePath: '/',
  });
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    applyNoIndexSeo({
      title: 'Account Action | DullyPDF',
      description: 'Complete your DullyPDF email verification or password reset and continue back into the app.',
      canonicalPath: ACCOUNT_ACTION_ROUTE_PATH,
    });

    const storedAction = readStoredEmailActionState(window.history.state);
    if (storedAction && !window.location.search) {
      if (storedAction.kind === 'pending-reset-password') {
        setState({
          kind: 'ready-reset-password',
          continuePath: storedAction.continuePath,
          email: storedAction.email,
          oobCode: storedAction.oobCode,
        });
        return undefined;
      }
      setState(
        storedAction.status === 'success'
          ? storedAction.mode === 'verifyEmail'
            ? { kind: 'verify-email-success', continuePath: storedAction.continuePath }
            : {
                kind: 'reset-password-success',
                continuePath: storedAction.continuePath,
                email: '',
              }
          : {
              kind: 'error',
              continuePath: storedAction.continuePath,
              message: INVALID_LINK_MESSAGE,
            },
      );
      return undefined;
    }

    const parsedAction = parseEmailActionSearch(window.location.search);
    if (parsedAction.status === 'invalid') {
      const message =
        parsedAction.reason === 'unsupported-mode' ? UNSUPPORTED_LINK_MESSAGE : INVALID_LINK_MESSAGE;
      writeStoredEmailActionState({
        kind: 'result',
        mode: 'verifyEmail',
        status: 'error',
        continuePath: parsedAction.continuePath,
      });
      setState({
        kind: 'error',
        continuePath: parsedAction.continuePath,
        message,
      });
      return undefined;
    }

    let cancelled = false;
    const { continuePath, oobCode, mode } = parsedAction;
    if (mode === 'verifyEmail') {
      void (async () => {
        try {
          await Auth.applyEmailVerificationCode(oobCode);
          if (cancelled) return;
          writeStoredEmailActionState({
            kind: 'result',
            mode,
            status: 'success',
            continuePath,
          });
          setState({ kind: 'verify-email-success', continuePath });
        } catch {
          if (cancelled) return;
          writeStoredEmailActionState({
            kind: 'result',
            mode,
            status: 'error',
            continuePath,
          });
          setState({
            kind: 'error',
            continuePath,
            message: INVALID_LINK_MESSAGE,
          });
        }
      })();
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const email = await Auth.verifyPasswordResetActionCode(oobCode);
        if (cancelled) return;
        writeStoredEmailActionState({
          kind: 'pending-reset-password',
          oobCode,
          email,
          continuePath,
        });
        setState({
          kind: 'ready-reset-password',
          continuePath,
          email,
          oobCode,
        });
      } catch {
        if (cancelled) return;
        writeStoredEmailActionState({
          kind: 'result',
          mode,
          status: 'error',
          continuePath,
        });
        setState({
          kind: 'error',
          continuePath,
          message: INVALID_LINK_MESSAGE,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const primaryHref = useMemo(() => {
    if (state.kind === 'error') return state.continuePath || '/';
    if (state.kind === 'verify-email-success') return state.continuePath || '/';
    if (state.kind === 'reset-password-success') return '/';
    return '/';
  }, [state]);

  const primaryLabel = useMemo(() => {
    if (state.kind === 'reset-password-success') {
      return 'Sign in to DullyPDF';
    }
    return primaryHref === '/' ? 'Open DullyPDF' : 'Continue to DullyPDF';
  }, [primaryHref, state]);

  const secondaryAction = useMemo<ActionLink>(() => {
    if (primaryHref !== '/') {
      return {
        href: '/',
        label: 'Go to homepage',
      };
    }
    return HELP_ACTION;
  }, [primaryHref]);

  const summaryItems = useMemo(() => {
    if (state.kind === 'verify-email-success') {
      return [
        'Your email is now trusted for password sign-in.',
        'You can return to the app immediately without reopening the link.',
        'Future account emails will continue using the branded DullyPDF action route.',
      ];
    }
    if (state.kind === 'reset-password-success') {
      return [
        'Your new password is active right away.',
        'Use the updated password the next time you sign in.',
        'If you did not request this reset, sign in and change the password again.',
      ];
    }
    if (state.kind === 'ready-reset-password' || state.kind === 'submitting-reset-password') {
      return [
        'Use at least 8 characters for the new password.',
        'Avoid reusing passwords from other apps or sites.',
        'After reset, return to the homepage and sign in normally.',
      ];
    }
    if (state.kind === 'processing-verify-email') {
      return [
        'We are validating your secure Firebase action code.',
        'As soon as verification finishes, the next-step actions will appear here.',
      ];
    }
    return [
      'The link may already be used, expired, or incomplete.',
      'Request a fresh verification or reset email from the sign-in page.',
      'If this keeps happening, open the setup guide and retry from the account flow.',
    ];
  }, [state]);

  const cardToneClass =
    state.kind === 'verify-email-success' || state.kind === 'reset-password-success'
      ? 'verify-action-card--success'
      : state.kind === 'error'
        ? 'verify-action-card--error'
        : 'verify-action-card--processing';

  const handleResetPasswordSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (state.kind !== 'ready-reset-password') {
      return;
    }
    setFormError(null);
    const trimmedPassword = password.trim();
    if (trimmedPassword.length < 8) {
      setFormError('Use at least 8 characters for your new password.');
      return;
    }
    if (trimmedPassword !== confirmPassword.trim()) {
      setFormError('Your passwords do not match.');
      return;
    }

    setState({
      kind: 'submitting-reset-password',
      continuePath: state.continuePath,
      email: state.email,
      oobCode: state.oobCode,
    });
    try {
      await Auth.confirmPasswordReset(state.oobCode, trimmedPassword);
      writeStoredEmailActionState({
        kind: 'result',
        mode: 'resetPassword',
        status: 'success',
        continuePath: state.continuePath,
      });
      setState({
        kind: 'reset-password-success',
        continuePath: state.continuePath,
        email: state.email,
      });
      setPassword('');
      setConfirmPassword('');
    } catch {
      writeStoredEmailActionState({
        kind: 'result',
        mode: 'resetPassword',
        status: 'error',
        continuePath: state.continuePath,
      });
      setState({
        kind: 'error',
        continuePath: state.continuePath,
        message: INVALID_LINK_MESSAGE,
      });
    }
  };

  if (state.kind === 'ready-reset-password' || state.kind === 'submitting-reset-password') {
    const isSubmitting = state.kind === 'submitting-reset-password';
    return (
      <AuthActionShell
        toneClass={cardToneClass}
        supportLabel="Secure account recovery"
        badge="Reset password"
        title="Choose a new password"
        description={
          <>
            Set a new password for <strong>{state.email}</strong>.
          </>
        }
        summaryTitle="Security checklist"
        summaryItems={summaryItems}
        body={
          <>
            {formError ? (
              <div className="verify-alerts">
                <Alert tone="error" variant="inline" message={formError} />
              </div>
            ) : null}

            <form className="verify-action-form" onSubmit={handleResetPasswordSubmit}>
              <label className="verify-action-field">
                <span>New password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                  disabled={isSubmitting}
                />
              </label>
              <label className="verify-action-field">
                <span>Confirm new password</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  disabled={isSubmitting}
                />
              </label>
              <button
                type="submit"
                className="ui-button ui-button--primary verify-action-submit"
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Resetting password…' : 'Reset password'}
              </button>
            </form>
          </>
        }
        footer={
          <div className="verify-action-footer verify-action-footer--reset">
            <a className="ui-button ui-button--ghost verify-action-link verify-action-link--footer" href="/">
              Back to homepage
            </a>
            <a className="verify-action-footer-link" href={HELP_ACTION.href}>
              Need help? Open the setup guide
            </a>
          </div>
        }
      />
    );
  }

  const supportLabel =
    state.kind === 'verify-email-success'
      ? 'Account access confirmed'
      : state.kind === 'reset-password-success'
        ? 'Password updated'
        : state.kind === 'processing-verify-email'
          ? 'Verifying secure link'
          : 'Action needs attention';

  const badge =
    state.kind === 'processing-verify-email'
      ? 'Verifying email'
      : state.kind === 'verify-email-success'
        ? 'Email verified'
        : state.kind === 'reset-password-success'
          ? 'Password reset'
          : 'Verification failed';

  const title =
    state.kind === 'processing-verify-email'
      ? 'Verifying your email'
      : state.kind === 'verify-email-success'
        ? 'Email verified'
        : state.kind === 'reset-password-success'
          ? 'Password updated'
          : 'We could not verify this email';

  const description =
    state.kind === 'processing-verify-email'
      ? 'Please wait while we confirm your email address with Firebase.'
      : state.kind === 'verify-email-success'
        ? VERIFY_EMAIL_SUCCESS_MESSAGE
        : state.kind === 'reset-password-success'
          ? 'Your password has been reset. Sign in with your new password.'
          : state.message;

  const summaryTitle =
    state.kind === 'processing-verify-email'
      ? 'What is happening'
      : state.kind === 'error'
        ? 'How to fix this'
        : 'What happens next';

  return (
    <AuthActionShell
      toneClass={cardToneClass}
      supportLabel={supportLabel}
      badge={badge}
      title={title}
      description={description}
      summaryTitle={summaryTitle}
      summaryItems={summaryItems}
      body={
        <div className="verify-action-actions">
          {state.kind === 'processing-verify-email' ? (
            <div className="verify-action-progress" aria-live="polite">
              <span className="verify-action-spinner" aria-hidden="true" />
              <span>Applying your verification link…</span>
            </div>
          ) : (
            <div className="verify-action-cta-grid">
              <a className="ui-button ui-button--primary verify-action-link" href={primaryHref}>
                {primaryLabel}
              </a>
              <a className="ui-button ui-button--ghost verify-action-link" href={secondaryAction.href}>
                {secondaryAction.label}
              </a>
            </div>
          )}
        </div>
      }
      footer={
        <div className="verify-action-footer">
          <span className="verify-action-footer-note">
            Secure Firebase action handled on your branded DullyPDF domain.
          </span>
          <a className="verify-action-footer-link" href={HELP_ACTION.href}>
            Need help? Open the setup guide
          </a>
        </div>
      }
    />
  );
};

export default AccountActionPage;
