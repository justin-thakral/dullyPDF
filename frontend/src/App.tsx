/**
 * Lightweight app shell that keeps the marketing homepage fast,
 * and lazy-loads the full workspace runtime on user intent.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import './App.css';
import Homepage from './components/pages/Homepage';
import LegacyHeader from './components/layout/LegacyHeader';
import VerifyEmailPage from './components/pages/VerifyEmailPage';
import { AUTH_READY_FALLBACK_MS } from './config/appConstants';
import { ApiService } from './services/api';
import { Auth } from './services/auth';
import { setAuthToken } from './services/authTokenStore';
import { clearExpiredPendingBillingCheckout, hasFreshPendingBillingCheckout } from './utils/billingCheckoutState';
import { debugLog } from './utils/debug';
import { applyRouteSeo } from './utils/seo';
import type { WorkspaceLaunchIntent } from './WorkspaceRuntime';

const WorkspaceRuntime = lazy(() => import('./WorkspaceRuntime'));

function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authSignInProvider, setAuthSignInProvider] = useState<string | null>(null);

  const [runtimeMounted, setRuntimeMounted] = useState(false);
  const [launchIntent, setLaunchIntent] = useState<WorkspaceLaunchIntent>(null);
  const [runtimeStarting, setRuntimeStarting] = useState(false);
  const [runtimeStartingMessage, setRuntimeStartingMessage] = useState<string | null>(null);
  const [runtimeStartError, setRuntimeStartError] = useState<string | null>(null);
  const runtimeStartAttemptRef = useRef(0);
  const runtimeStartAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    applyRouteSeo({ kind: 'app' });
  }, []);

  useEffect(() => {
    let isActive = true;
    const markReady = () => {
      if (!isActive) return;
      setAuthReady(true);
    };

    const readyTimer = setTimeout(markReady, AUTH_READY_FALLBACK_MS);
    const unsubscribe = Auth.onAuthStateChanged(async (user) => {
      if (!isActive) return;
      setAuthUser(user);
      setAuthSignInProvider(null);

      if (!user) {
        setAuthToken(null);
        markReady();
        return;
      }

      try {
        const tokenResult = await user.getIdTokenResult(true);
        if (!isActive) return;
        setAuthToken(tokenResult.token);
        const provider =
          tokenResult.signInProvider ??
          (user.providerData.length === 1 ? user.providerData[0]?.providerId ?? null : null);
        setAuthSignInProvider(provider);
      } catch (error) {
        debugLog('Failed to hydrate lightweight auth session', error);
      }

      markReady();
    });

    return () => {
      isActive = false;
      clearTimeout(readyTimer);
      unsubscribe();
    };
  }, []);

  const requiresEmailVerification = useMemo(
    () => Boolean(authUser && authSignInProvider === 'password' && !authUser.emailVerified),
    [authSignInProvider, authUser],
  );
  const verifiedUser = useMemo(
    () => (requiresEmailVerification ? null : authUser),
    [authUser, requiresEmailVerification],
  );
  const userEmail = useMemo(() => verifiedUser?.email ?? null, [verifiedUser]);

  const abortRuntimeStart = useCallback(() => {
    runtimeStartAbortRef.current?.abort();
    runtimeStartAbortRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      abortRuntimeStart();
    };
  }, [abortRuntimeStart]);

  const startRuntime = useCallback(async (
    intent: WorkspaceLaunchIntent,
    options?: {
      waitForBackend?: boolean;
      loadingMessage?: string;
    },
  ) => {
    abortRuntimeStart();
    setRuntimeStartError(null);
    setLaunchIntent(intent);
    if (!options?.waitForBackend) {
      setRuntimeStarting(false);
      setRuntimeStartingMessage(null);
      setRuntimeMounted(true);
      return;
    }

    const attemptId = runtimeStartAttemptRef.current + 1;
    runtimeStartAttemptRef.current = attemptId;
    const controller = new AbortController();
    runtimeStartAbortRef.current = controller;
    setRuntimeStarting(true);
    setRuntimeStartingMessage(options.loadingMessage ?? 'Backend is starting…');

    try {
      await ApiService.ensureBackendReady({
        signal: controller.signal,
        healthUrl: '/api/health',
      });
      if (controller.signal.aborted || runtimeStartAttemptRef.current !== attemptId) {
        return;
      }
      setRuntimeMounted(true);
    } catch (error) {
      if (controller.signal.aborted || runtimeStartAttemptRef.current !== attemptId) {
        return;
      }
      const message = error instanceof Error && error.message.trim()
        ? error.message
        : 'Backend is still starting. Please wait a moment and try again.';
      setRuntimeStartError(message);
      setLaunchIntent(null);
    } finally {
      if (runtimeStartAttemptRef.current === attemptId) {
        setRuntimeStarting(false);
        if (runtimeStartAbortRef.current === controller) {
          runtimeStartAbortRef.current = null;
        }
      }
    }
  }, [abortRuntimeStart]);

  const launchWorkspace = useCallback((intent: WorkspaceLaunchIntent) => {
    if (runtimeMounted || runtimeStarting) {
      return;
    }
    const waitForBackend = Boolean(verifiedUser) && (intent === 'workflow' || intent === 'profile');
    const loadingMessage = intent === 'profile'
      ? 'Starting backend for your profile…'
      : 'Backend is starting…';
    void startRuntime(intent, { waitForBackend, loadingMessage });
  }, [runtimeMounted, runtimeStarting, startRuntime, verifiedUser]);

  const handleDismissRuntimeStartError = useCallback(() => {
    setRuntimeStartError(null);
    setRuntimeStartingMessage(null);
    setLaunchIntent(null);
  }, []);

  useEffect(() => {
    if (!authReady || runtimeMounted || typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    const billingState = (url.searchParams.get('billing') || '').toLowerCase();
    if (!billingState) return;
    if (billingState !== 'success' && billingState !== 'cancel') {
      url.searchParams.delete('billing');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      return;
    }
    clearExpiredPendingBillingCheckout();
    if (billingState === 'cancel') {
      if (!verifiedUser) {
        url.searchParams.delete('billing');
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
        return;
      }
      launchWorkspace('workflow');
      return;
    }
    if (!verifiedUser && !hasFreshPendingBillingCheckout()) {
      url.searchParams.delete('billing');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      return;
    }
    launchWorkspace(verifiedUser ? 'workflow' : 'signin');
  }, [authReady, launchWorkspace, runtimeMounted, verifiedUser]);

  const handleStartWorkflow = useCallback(() => {
    launchWorkspace(verifiedUser ? 'workflow' : 'signin');
  }, [launchWorkspace, verifiedUser]);

  const handleStartDemo = useCallback(() => {
    launchWorkspace('demo');
  }, [launchWorkspace]);

  const handleSignIn = useCallback(() => {
    launchWorkspace('signin');
  }, [launchWorkspace]);

  const handleOpenProfile = useCallback(() => {
    launchWorkspace('profile');
  }, [launchWorkspace]);

  const handleSignOut = useCallback(async () => {
    try {
      await Auth.signOut();
      setAuthToken(null);
      setAuthUser(null);
      setAuthSignInProvider(null);
    } catch (error) {
      debugLog('Failed to sign out from lightweight shell', error);
    }
  }, []);

  const handleRefreshVerification = useCallback(async () => {
    try {
      const user = await Auth.refreshCurrentUser();
      setAuthUser(user);
      setAuthSignInProvider(null);
      if (!user) {
        setAuthToken(null);
        return;
      }
      const tokenResult = await user.getIdTokenResult(true);
      setAuthToken(tokenResult.token);
      const provider =
        tokenResult.signInProvider ??
        (user.providerData.length === 1 ? user.providerData[0]?.providerId ?? null : null);
      setAuthSignInProvider(provider);
    } catch (error) {
      debugLog('Failed to refresh verification state', error);
    }
  }, []);

  if (!authReady) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">Loading workspace…</div>
      </div>
    );
  }

  if (requiresEmailVerification) {
    return (
      <VerifyEmailPage
        email={authUser?.email ?? null}
        onRefresh={handleRefreshVerification}
        onSignOut={handleSignOut}
      />
    );
  }

  if (!runtimeMounted && (runtimeStarting || runtimeStartError)) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">
          <div>{runtimeStarting ? (runtimeStartingMessage ?? 'Backend is starting…') : 'Backend startup delayed'}</div>
          <div>
            {runtimeStarting
              ? 'The first request after inactivity can take a few seconds.'
              : runtimeStartError}
          </div>
          {!runtimeStarting ? (
            <button type="button" onClick={handleDismissRuntimeStartError}>
              Back
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (runtimeMounted) {
    return (
      <Suspense
        fallback={
          <div className="auth-loading-screen">
            <div className="auth-loading-card">Loading workspace…</div>
          </div>
        }
      >
        <WorkspaceRuntime
          initialShowHomepage={launchIntent !== 'workflow' && launchIntent !== 'demo'}
          launchIntent={launchIntent}
          assumeAuthReady={authReady}
          bootstrapHasVerifiedUser={Boolean(verifiedUser)}
          bootstrapAuthUser={authUser}
        />
      </Suspense>
    );
  }

  return (
    <div className="homepage-shell">
      <LegacyHeader
        currentView="homepage"
        onNavigateHome={() => {}}
        showBackButton={false}
        userEmail={userEmail}
        onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        onSignIn={!verifiedUser ? handleSignIn : undefined}
      />
      <main className="landing-main">
        <Homepage
          onStartWorkflow={handleStartWorkflow}
          onStartDemo={handleStartDemo}
          userEmail={userEmail}
          onSignIn={!verifiedUser ? handleSignIn : undefined}
          onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
        />
      </main>
    </div>
  );
}

export default App;
