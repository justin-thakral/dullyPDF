import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { UserProfile } from '../services/api';
import { Auth } from '../services/auth';
import { setAuthToken } from '../services/authTokenStore';
import { ApiService } from '../services/api';
import { AUTH_READY_FALLBACK_MS, DEFAULT_PROFILE_LIMITS } from '../config/appConstants';
import { debugLog } from '../utils/debug';

export function useAuth(deps: {
  clearSavedFormsRetry: () => void;
  clearSavedForms: () => void;
  refreshSavedForms: (options?: { allowRetry?: boolean }) => Promise<void>;
}) {
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authSignInProvider, setAuthSignInProvider] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileLoadError, setProfileLoadError] = useState<string | null>(null);
  const authUserRef = useRef<User | null>(null);
  const depsRef = useRef(deps);

  useEffect(() => {
    depsRef.current = deps;
  }, [deps]);

  const requiresEmailVerification = useMemo(
    () => Boolean(authUser && authSignInProvider === 'password' && !authUser.emailVerified),
    [authSignInProvider, authUser],
  );
  const verifiedUser = useMemo(
    () => (requiresEmailVerification ? null : authUser),
    [authUser, requiresEmailVerification],
  );
  const profileLimits = useMemo(
    () => userProfile?.limits ?? DEFAULT_PROFILE_LIMITS,
    [userProfile],
  );
  const userEmail = useMemo(() => verifiedUser?.email ?? undefined, [verifiedUser]);

  useEffect(() => {
    authUserRef.current = verifiedUser;
  }, [verifiedUser]);

  const loadUserProfile = useCallback(async () => {
    if (!authUserRef.current) return null;
    setProfileLoading(true);
    try {
      const profile = await ApiService.getProfile();
      setUserProfile(profile);
      setProfileLoadError(null);
      return profile;
    } catch (error) {
      debugLog('Failed to load profile', error);
      const message =
        error instanceof Error && error.message.trim()
          ? error.message
          : 'Failed to refresh profile details.';
      setProfileLoadError(message);
      return null;
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const syncAuthSession = useCallback(
    async (user: User | null, options?: { forceTokenRefresh?: boolean; deferSavedForms?: boolean }) => {
      authUserRef.current = null;
      setAuthUser(user);
      setAuthSignInProvider(null);
      setProfileLoadError(null);

      if (!user) {
        depsRef.current.clearSavedFormsRetry();
        depsRef.current.clearSavedForms();
        setUserProfile(null);
        setProfileLoadError(null);
        setShowProfile(false);
        return;
      }

      try {
        const tokenResult = await user.getIdTokenResult(options?.forceTokenRefresh ?? true);
        setAuthToken(tokenResult.token);
        const provider =
          tokenResult.signInProvider ??
          (user.providerData.length === 1 ? user.providerData[0]?.providerId ?? null : null);
        setAuthSignInProvider(provider);
        const needsVerification = provider === 'password' && !user.emailVerified;
        if (needsVerification) {
          depsRef.current.clearSavedFormsRetry();
          depsRef.current.clearSavedForms();
          setUserProfile(null);
          setProfileLoadError(null);
          setShowProfile(false);
          return;
        }
        authUserRef.current = user;
        if (options?.deferSavedForms) {
          void depsRef.current.refreshSavedForms({ allowRetry: true });
          void loadUserProfile();
        } else {
          await depsRef.current.refreshSavedForms({ allowRetry: true });
          await loadUserProfile();
        }
      } catch (error) {
        console.error('Failed to initialize session', error);
      }
    },
    [loadUserProfile],
  );

  useEffect(() => {
    let isActive = true;
    const markReady = () => {
      if (!isActive) return;
      setAuthReady(true);
    };
    const readyTimer = setTimeout(markReady, AUTH_READY_FALLBACK_MS);
    const unsubscribe = Auth.onAuthStateChanged(async (user) => {
      await syncAuthSession(user, { forceTokenRefresh: true, deferSavedForms: true });
      markReady();
    });
    return () => {
      isActive = false;
      clearTimeout(readyTimer);
      depsRef.current.clearSavedFormsRetry();
      unsubscribe();
    };
  }, [syncAuthSession]);

  useEffect(() => {
    if (!showProfile || !verifiedUser) return;
    void loadUserProfile();
  }, [loadUserProfile, showProfile, verifiedUser]);

  const handleSignOut = useCallback(async () => {
    await Auth.signOut();
  }, []);

  const handleRefreshVerification = useCallback(async () => {
    const user = await Auth.refreshCurrentUser();
    await syncAuthSession(user, { forceTokenRefresh: true });
  }, [syncAuthSession]);

  const handleOpenProfile = useCallback(() => {
    if (!verifiedUser) return;
    setShowProfile(true);
  }, [verifiedUser]);

  const handleCloseProfile = useCallback(() => {
    setShowProfile(false);
  }, []);

  return {
    authReady,
    authUser,
    authSignInProvider,
    showLogin,
    setShowLogin,
    showProfile,
    setShowProfile,
    userProfile,
    profileLoading,
    profileLoadError,
    authUserRef,
    requiresEmailVerification,
    verifiedUser,
    profileLimits,
    userEmail,
    loadUserProfile,
    syncAuthSession,
    handleSignOut,
    handleRefreshVerification,
    handleOpenProfile,
    handleCloseProfile,
  };
}
