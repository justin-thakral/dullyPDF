/**
 * Verification gate for password users awaiting email confirmation.
 */
import React, { useState } from 'react';
import './VerifyEmailPage.css';
import { Auth } from '../../services/auth';
import { Alert } from '../ui/Alert';

interface VerifyEmailPageProps {
  email?: string | null;
  onRefresh?: () => Promise<void> | void;
  onSignOut?: () => void;
}

/**
 * Render a verification reminder with resend + refresh actions.
 */
const VerifyEmailPage: React.FC<VerifyEmailPageProps> = ({ email, onRefresh, onSignOut }) => {
  const [isSending, setIsSending] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const handleResend = async () => {
    setError(null);
    setInfo(null);
    setIsSending(true);
    try {
      await Auth.sendVerificationEmail();
      setInfo('Verification email sent. Check your inbox and spam folder.');
    } catch (err) {
      setError('Unable to resend the verification email. Please try again shortly.');
    } finally {
      setIsSending(false);
    }
  };

  const handleRefresh = async () => {
    setError(null);
    setInfo(null);
    setIsChecking(true);
    try {
      await onRefresh?.();
    } catch (err) {
      setError('We could not confirm verification yet. Please try again.');
    } finally {
      setIsChecking(false);
    }
  };

  return (
    <div className="verify-page">
      <div className="verify-card">
        <div className="verify-header">
          <div className="verify-badge">Email verification required</div>
          <h1>Confirm your email</h1>
          <p>
            We sent a verification link to <strong>{email || 'your email address'}</strong>. Please
            verify your email before accessing the workspace.
          </p>
          <p className="verify-spam-note">
            Email might be sent to spam please check there if you don&apos;t see email in inbox
          </p>
        </div>

        {error || info ? (
          <div className="verify-alerts">
            {error ? <Alert tone="error" variant="inline" message={error} /> : null}
            {info ? <Alert tone="info" variant="inline" message={info} /> : null}
          </div>
        ) : null}

        <div className="verify-actions">
          <button
            type="button"
            className="ui-button ui-button--primary"
            onClick={handleRefresh}
            disabled={isChecking}
          >
            {isChecking ? 'Checking…' : 'I have verified'}
          </button>
          <button
            type="button"
            className="ui-button ui-button--ghost"
            onClick={handleResend}
            disabled={isSending}
          >
            {isSending ? 'Sending…' : 'Resend verification email'}
          </button>
        </div>

        {onSignOut ? (
          <button type="button" className="verify-signout" onClick={onSignOut}>
            Sign out
          </button>
        ) : null}
      </div>
    </div>
  );
};

export default VerifyEmailPage;
