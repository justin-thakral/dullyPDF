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
import { clearWorkspaceResumeState } from './utils/workspaceResumeState';
import {
  areWorkspaceBrowserRoutesEqual,
  buildWorkspaceBrowserHref,
  getWorkspaceBrowserRouteKey,
  type WorkspaceBrowserRoute,
} from './utils/workspaceRoutes';
import type { WorkspaceLaunchIntent } from './WorkspaceRuntime';

const WorkspaceRuntime = lazy(() => import('./WorkspaceRuntime'));

type AppProps = {
  initialBrowserRoute?: WorkspaceBrowserRoute;
};

function App({
  initialBrowserRoute = { kind: 'homepage' },
}: AppProps) {
  const HOMEPAGE_SPLASH_FALLBACK_MS = 2500;
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authSignInProvider, setAuthSignInProvider] = useState<string | null>(null);
  const [browserRoute, setBrowserRoute] = useState<WorkspaceBrowserRoute>(initialBrowserRoute);
  const [homepageInitialRenderReady, setHomepageInitialRenderReady] = useState(false);

  const [runtimeMounted, setRuntimeMounted] = useState(false);
  const [launchIntent, setLaunchIntent] = useState<WorkspaceLaunchIntent>(null);
  const [runtimeStarting, setRuntimeStarting] = useState(false);
  const [runtimeStartError, setRuntimeStartError] = useState<string | null>(null);
  const runtimeStartAttemptRef = useRef(0);
  const runtimeStartAbortRef = useRef<AbortController | null>(null);
  const runtimeAutoStartKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (browserRoute.kind === 'homepage') {
      applyRouteSeo({ kind: 'app' });
    }
  }, [browserRoute.kind]);

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

  const replaceBrowserRoute = useCallback((
    nextRoute: WorkspaceBrowserRoute,
    options?: { replace?: boolean },
  ) => {
    if (typeof window === 'undefined') return;
    const nextHref = buildWorkspaceBrowserHref(nextRoute);
    const [nextPathname, nextSearch = ''] = nextHref.split('?');
    const resolvedSearch = nextSearch ? `?${nextSearch}` : '';
    if (window.location.pathname === nextPathname && window.location.search === resolvedSearch) {
      return;
    }
    const historyMethod = options?.replace ? 'replaceState' : 'pushState';
    window.history[historyMethod]({}, '', `${nextPathname}${resolvedSearch}`);
  }, []);

  const navigateBrowserRoute = useCallback((
    nextRoute: WorkspaceBrowserRoute,
    options?: { replace?: boolean },
  ) => {
    setBrowserRoute((current) => (
      areWorkspaceBrowserRoutesEqual(current, nextRoute) ? current : nextRoute
    ));
    replaceBrowserRoute(nextRoute, options);
    if (nextRoute.kind === 'homepage') {
      abortRuntimeStart();
      runtimeAutoStartKeyRef.current = null;
      setRuntimeMounted(false);
      setLaunchIntent(null);
      setRuntimeStarting(false);
      setRuntimeStartError(null);
      setHomepageInitialRenderReady(false);
    }
  }, [abortRuntimeStart, replaceBrowserRoute]);

  const replaceBrowserRouteWithBillingState = useCallback((billingState: 'success' | 'cancel') => {
    if (typeof window !== 'undefined') {
      const href = buildWorkspaceBrowserHref({ kind: 'upload-root' });
      window.history.replaceState({}, '', `${href}?billing=${billingState}`);
    }
    setBrowserRoute({ kind: 'upload-root' });
  }, []);

  useEffect(() => {
    return () => {
      abortRuntimeStart();
    };
  }, [abortRuntimeStart]);

  useEffect(() => {
    if (browserRoute.kind !== 'homepage' || runtimeMounted) {
      setHomepageInitialRenderReady(false);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setHomepageInitialRenderReady(true);
    }, HOMEPAGE_SPLASH_FALLBACK_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [browserRoute.kind, runtimeMounted]);

  const startRuntime = useCallback(async (
    intent: WorkspaceLaunchIntent,
    options?: {
      waitForBackend?: boolean;
    },
  ) => {
    abortRuntimeStart();
    setRuntimeStartError(null);
    setLaunchIntent(intent);
    if (!options?.waitForBackend) {
      setRuntimeStarting(false);
      setRuntimeMounted(true);
      return;
    }

    const attemptId = runtimeStartAttemptRef.current + 1;
    runtimeStartAttemptRef.current = attemptId;
    const controller = new AbortController();
    runtimeStartAbortRef.current = controller;
    setRuntimeStarting(true);

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
      void error;
      setRuntimeStartError('Loading workspace took longer than expected. Please try again.');
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
    void startRuntime(intent, { waitForBackend });
  }, [runtimeMounted, runtimeStarting, startRuntime, verifiedUser]);

  useEffect(() => {
    if (!authReady) return;
    if (browserRoute.kind === 'homepage') {
      runtimeAutoStartKeyRef.current = null;
      return;
    }
    if (runtimeMounted || runtimeStarting || runtimeStartError) {
      return;
    }
    const autoStartKey = `${getWorkspaceBrowserRouteKey(browserRoute)}:${verifiedUser ? 'verified' : 'guest'}`;
    if (runtimeAutoStartKeyRef.current === autoStartKey) {
      return;
    }
    runtimeAutoStartKeyRef.current = autoStartKey;
    const intent: WorkspaceLaunchIntent = browserRoute.kind === 'profile'
      ? 'profile'
      : (verifiedUser ? 'workflow' : 'signin');
    launchWorkspace(intent);
  }, [authReady, browserRoute, launchWorkspace, runtimeMounted, runtimeStartError, runtimeStarting, verifiedUser]);

  const handleDismissRuntimeStartError = useCallback(() => {
    setRuntimeStartError(null);
    setLaunchIntent(null);
    if (browserRoute.kind !== 'homepage') {
      navigateBrowserRoute({ kind: 'homepage' }, { replace: true });
    }
  }, [browserRoute.kind, navigateBrowserRoute]);

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
        navigateBrowserRoute({ kind: 'homepage' }, { replace: true });
        return;
      }
      replaceBrowserRouteWithBillingState('cancel');
      return;
    }
    if (!verifiedUser && !hasFreshPendingBillingCheckout()) {
      navigateBrowserRoute({ kind: 'homepage' }, { replace: true });
      return;
    }
    replaceBrowserRouteWithBillingState('success');
  }, [authReady, navigateBrowserRoute, replaceBrowserRouteWithBillingState, runtimeMounted, verifiedUser]);

  const handleStartWorkflow = useCallback(() => {
    navigateBrowserRoute({ kind: 'upload-root' });
    launchWorkspace(verifiedUser ? 'workflow' : 'signin');
  }, [launchWorkspace, navigateBrowserRoute, verifiedUser]);

  const handleStartDemo = useCallback(() => {
    launchWorkspace('demo');
  }, [launchWorkspace]);

  const handleSignIn = useCallback(() => {
    launchWorkspace('signin');
  }, [launchWorkspace]);

  const handleOpenProfile = useCallback(() => {
    navigateBrowserRoute({ kind: 'profile' });
    launchWorkspace(verifiedUser ? 'profile' : 'signin');
  }, [launchWorkspace, navigateBrowserRoute, verifiedUser]);

  const handleSignOut = useCallback(async () => {
    try {
      await Auth.signOut();
      clearWorkspaceResumeState();
      setAuthToken(null);
      setAuthUser(null);
      setAuthSignInProvider(null);
      navigateBrowserRoute({ kind: 'homepage' }, { replace: true });
    } catch (error) {
      debugLog('Failed to sign out from lightweight shell', error);
    }
  }, [navigateBrowserRoute]);

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

  const workspaceLoadingScreen = (
    <div className="auth-loading-screen">
      <div className="auth-loading-card">Loading workspace…</div>
    </div>
  );

  if (!authReady && browserRoute.kind !== 'homepage') {
    return workspaceLoadingScreen;
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
          <div>{runtimeStarting ? 'Loading workspace…' : 'Unable to load workspace.'}</div>
          {!runtimeStarting && runtimeStartError ? <div>{runtimeStartError}</div> : null}
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
        fallback={workspaceLoadingScreen}
      >
        <WorkspaceRuntime
          initialShowHomepage={launchIntent !== 'workflow' && launchIntent !== 'demo'}
          launchIntent={launchIntent}
          assumeAuthReady={authReady}
          bootstrapHasVerifiedUser={Boolean(verifiedUser)}
          bootstrapAuthUser={authUser}
          browserRoute={browserRoute}
          onBrowserRouteChange={navigateBrowserRoute}
        />
      </Suspense>
    );
  }

  if (browserRoute.kind !== 'homepage') {
    return workspaceLoadingScreen;
  }

  const showHomepageSplash = browserRoute.kind === 'homepage' && !homepageInitialRenderReady;

  return (
    <>
      <div className="homepage-shell" aria-hidden={showHomepageSplash}>
      <LegacyHeader
        currentView="homepage"
        onNavigateHome={() => {}}
        showBackButton={false}
        userEmail={userEmail}
        authPending={!authReady}
        onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        onSignIn={!verifiedUser ? handleSignIn : undefined}
      />
      <main className="landing-main">
        <Homepage
          onStartWorkflow={handleStartWorkflow}
          onStartDemo={handleStartDemo}
          userEmail={userEmail}
          authPending={!authReady}
          onSignIn={!verifiedUser ? handleSignIn : undefined}
          onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
          onInitialRenderReady={() => {
            setHomepageInitialRenderReady(true);
          }}
        />
      </main>
      </div>
      {showHomepageSplash ? (
        <div className="homepage-loading-overlay" aria-hidden="true" />
      ) : null}
    </>
  );
}

export default App;
