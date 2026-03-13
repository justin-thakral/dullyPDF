/**
 * Verification gate for password users awaiting email confirmation.
 */
import React, { useState } from 'react';
import '../../styles/ui-buttons.css';
import './VerifyEmailPage.css';
import './AccountActionPage.css';
import { Auth } from '../../services/auth';
import { Alert } from '../ui/Alert';
import AuthActionShell from './AuthActionShell';

interface VerifyEmailPageProps {
  email?: string | null;
  onRefresh?: () => Promise<void> | void;
  onSignOut?: () => void;
}

const RESEND_COOLDOWN_MS = 60_000;
const RESEND_DAILY_LIMIT = 5;
const RESEND_STORAGE_PREFIX = 'dullypdf:verify-email:resend:';

type ResendThrottleState = {
  dayKey: string;
  sentCount: number;
  nextAllowedAtMs: number;
};

function resolveDayKey(nowMs: number): string {
  return new Date(nowMs).toISOString().slice(0, 10);
}

function resolveStorageKey(email?: string | null): string {
  const normalized = (email || 'anonymous').trim().toLowerCase();
  return `${RESEND_STORAGE_PREFIX}${normalized || 'anonymous'}`;
}

function loadResendThrottle(email?: string | null, nowMs = Date.now()): ResendThrottleState {
  const initial: ResendThrottleState = {
    dayKey: resolveDayKey(nowMs),
    sentCount: 0,
    nextAllowedAtMs: 0,
  };
  if (typeof window === 'undefined') {
    return initial;
  }
  try {
    const raw = window.localStorage.getItem(resolveStorageKey(email));
    if (!raw) {
      return initial;
    }
    const parsed = JSON.parse(raw) as Partial<ResendThrottleState>;
    const parsedDay = typeof parsed.dayKey === 'string' ? parsed.dayKey : initial.dayKey;
    if (parsedDay !== initial.dayKey) {
      return initial;
    }
    const sentCount = Number.isFinite(parsed.sentCount) ? Math.max(0, Number(parsed.sentCount)) : 0;
    const nextAllowedAtMs = Number.isFinite(parsed.nextAllowedAtMs) ? Math.max(0, Number(parsed.nextAllowedAtMs)) : 0;
    return { dayKey: parsedDay, sentCount, nextAllowedAtMs };
  } catch {
    return initial;
  }
}

function saveResendThrottle(email: string | null | undefined, state: ResendThrottleState): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(resolveStorageKey(email), JSON.stringify(state));
  } catch {
    // Ignore local storage write failures and keep runtime state only.
  }
}

/**
 * Render a verification reminder with resend + refresh actions.
 */
const VerifyEmailPage: React.FC<VerifyEmailPageProps> = ({ email, onRefresh, onSignOut }) => {
  const [isSending, setIsSending] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [resendThrottle, setResendThrottle] = useState<ResendThrottleState>(() => loadResendThrottle(email));
  const [, setTimeTick] = useState(0);
  const nowMs = Date.now();
  const cooldownRemainingMs = Math.max(0, resendThrottle.nextAllowedAtMs - nowMs);
  const cooldownRemainingSeconds = Math.ceil(cooldownRemainingMs / 1000);
  const dailyLimitReached = resendThrottle.sentCount >= RESEND_DAILY_LIMIT;
  const resendBlocked = dailyLimitReached || cooldownRemainingMs > 0;
  const summaryItems = [
    'Open the message from DullyPDF and follow the secure verification link.',
    <span className="verify-page-summary-warning">
      If the message does not appear in your inbox right away, check spam or promotions.
    </span>,
    'After verification, return here and confirm so the workspace can refresh your session.',
  ];
  const resendStatusMessage = dailyLimitReached
    ? 'Daily resend limit reached on this browser. Try again tomorrow.'
    : cooldownRemainingMs > 0
      ? `You can request another verification email in ${cooldownRemainingSeconds}s.`
      : `You can resend up to ${RESEND_DAILY_LIMIT} verification emails per day from this browser.`;

  React.useEffect(() => {
    setResendThrottle(loadResendThrottle(email));
  }, [email]);

  React.useEffect(() => {
    if (cooldownRemainingMs <= 0) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      setTimeTick((prev) => prev + 1_000);
    }, 1_000);
    return () => window.clearInterval(intervalId);
  }, [cooldownRemainingMs]);

  const handleResend = async () => {
    setError(null);
    setInfo(null);
    if (dailyLimitReached) {
      setError('Daily resend limit reached. Please try again tomorrow.');
      return;
    }
    if (cooldownRemainingMs > 0) {
      setInfo(`Please wait ${cooldownRemainingSeconds}s before resending.`);
      return;
    }
    setIsSending(true);
    try {
      await Auth.sendVerificationEmail();
      const updatedState: ResendThrottleState = {
        dayKey: resolveDayKey(Date.now()),
        sentCount: resendThrottle.sentCount + 1,
        nextAllowedAtMs: Date.now() + RESEND_COOLDOWN_MS,
      };
      setResendThrottle(updatedState);
      saveResendThrottle(email, updatedState);
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
    <AuthActionShell
      toneClass="verify-action-card--processing"
      supportLabel="Workspace access pending"
      badge="Email verification required"
      title="Confirm your email"
      description={
        <>
          We sent a verification link to <strong>{email || 'your email address'}</strong>. Verify the address before
          entering the workspace.
        </>
      }
      summaryTitle="Before you continue"
      summaryItems={summaryItems}
      body={
        <>
          {error || info ? (
            <div className="verify-alerts">
              {error ? <Alert tone="error" variant="inline" message={error} /> : null}
              {info ? <Alert tone="info" variant="inline" message={info} /> : null}
            </div>
          ) : null}

          <div className="verify-actions verify-page-actions">
            <button
              type="button"
              className="ui-button ui-button--primary verify-page-button"
              onClick={handleRefresh}
              disabled={isChecking}
            >
              {isChecking ? 'Checking…' : 'I have verified my email'}
            </button>
            <button
              type="button"
              className="ui-button ui-button--ghost verify-page-button"
              onClick={handleResend}
              disabled={isSending || resendBlocked}
            >
              {isSending
                ? 'Sending…'
                : dailyLimitReached
                  ? 'Resend limit reached'
                  : cooldownRemainingMs > 0
                    ? `Resend in ${cooldownRemainingSeconds}s`
                    : 'Resend verification email'}
            </button>
          </div>

          <div className="verify-page-meta">
            <p className="verify-page-meta-note">{resendStatusMessage}</p>
          </div>
        </>
      }
      footer={
        <div className="verify-action-footer verify-page-footer">
          {onSignOut ? (
            <button type="button" className="ui-button ui-button--ghost verify-page-signout" onClick={onSignOut}>
              Sign out
            </button>
          ) : (
            <span className="verify-action-footer-note">
              Secure Firebase verification handled on your branded DullyPDF domain.
            </span>
          )}
          <a className="verify-action-footer-link" href="/usage-docs/getting-started">
            Need help? Open the setup guide
          </a>
        </div>
      }
    />
  );
};

export default VerifyEmailPage;
