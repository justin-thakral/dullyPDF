/**
 * Firebase auth wrappers used across the UI.
 */
import {
  applyActionCode,
  confirmPasswordReset,
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  onIdTokenChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  updateProfile,
  verifyPasswordResetCode,
} from 'firebase/auth';
import type { User } from 'firebase/auth';
import { firebaseAuth } from './firebaseClient';
import { setAuthToken } from './authTokenStore';

export type AuthStateListener = (user: User | null) => void;

let idTokenListenerInitialised = false;

function resolveEmailActionSettings(pathname = '/'): { url: string; handleCodeInApp?: boolean } | undefined {
  if (typeof window === 'undefined' || !window.location?.origin) {
    return undefined;
  }
  // Keep users on the branded app domain after clicking verification links.
  // This does not change the email sender (Firebase), but it improves UX and can help
  // deliverability compared to sending users to a generic Firebase-hosted handler page.
  const normalizedPath = pathname === '/' ? '' : pathname.startsWith('/') ? pathname : `/${pathname}`;
  return { url: `${window.location.origin}${normalizedPath}`, handleCodeInApp: false };
}

/**
 * Register a token refresh listener once per app session.
 */
function ensureIdTokenListener() {
  if (idTokenListenerInitialised) return;
  idTokenListenerInitialised = true;
  onIdTokenChanged(firebaseAuth, async (user) => {
    if (!user) {
      setAuthToken(null);
      return;
    }
    try {
      const token = await user.getIdToken();
      setAuthToken(token);
    } catch (error) {
      console.error('[auth] Failed to refresh ID token', error);
      setAuthToken(null);
    }
  });
}

ensureIdTokenListener();

/**
 * Fetch the current user's ID token, optionally forcing a refresh.
 */
export async function getFreshIdToken(forceRefresh = false): Promise<string | null> {
  ensureIdTokenListener();
  const user = firebaseAuth.currentUser;
  if (!user) {
    setAuthToken(null);
    return null;
  }
  try {
    const token = await user.getIdToken(forceRefresh);
    setAuthToken(token);
    return token;
  } catch (error) {
    console.error('[auth] Failed to fetch ID token', error);
    setAuthToken(null);
    return null;
  }
}

export const Auth = {
  /**
   * Subscribe to auth state changes.
   */
  onAuthStateChanged(callback: AuthStateListener) {
    ensureIdTokenListener();
    return onAuthStateChanged(firebaseAuth, callback);
  },

  /**
   * Sign a user in with email/password and cache the token.
   */
  async signIn(email: string, password: string): Promise<User> {
    ensureIdTokenListener();
    const credential = await signInWithEmailAndPassword(firebaseAuth, email, password);
    const token = await credential.user.getIdToken();
    setAuthToken(token);
    return credential.user;
  },

  /**
   * Register a new user and optionally set display name.
   */
  async signUp(email: string, password: string, displayName?: string): Promise<User> {
    ensureIdTokenListener();
    const credential = await createUserWithEmailAndPassword(firebaseAuth, email, password);
    if (displayName && displayName.trim().length) {
      await updateProfile(credential.user, { displayName: displayName.trim() });
    }
    if (!credential.user.emailVerified) {
      const actionSettings = resolveEmailActionSettings('/upload');
      if (actionSettings) {
        await sendEmailVerification(credential.user, actionSettings);
      } else {
        await sendEmailVerification(credential.user);
      }
    }
    const token = await credential.user.getIdToken();
    setAuthToken(token);
    return credential.user;
  },

  /**
   * Send a password reset email.
   */
  async sendPasswordReset(email: string): Promise<void> {
    const actionSettings = resolveEmailActionSettings();
    if (actionSettings) {
      await sendPasswordResetEmail(firebaseAuth, email, actionSettings);
    } else {
      await sendPasswordResetEmail(firebaseAuth, email);
    }
  },

  /**
   * Sign the current user out and clear tokens.
   */
  async signOut(): Promise<void> {
    await firebaseSignOut(firebaseAuth);
    setAuthToken(null);
  },

  /**
   * Send a verification email to the current user.
   */
  async sendVerificationEmail(): Promise<void> {
    const user = firebaseAuth.currentUser;
    if (!user) {
      throw new Error('No authenticated user found.');
    }
    const actionSettings = resolveEmailActionSettings('/upload');
    if (actionSettings) {
      await sendEmailVerification(user, actionSettings);
    } else {
      await sendEmailVerification(user);
    }
  },

  /**
   * Complete an out-of-band email verification action code.
   */
  async applyEmailVerificationCode(oobCode: string): Promise<void> {
    await applyActionCode(firebaseAuth, oobCode);
    const user = firebaseAuth.currentUser;
    if (!user) {
      return;
    }
    try {
      await user.reload();
      const token = await user.getIdToken(true);
      setAuthToken(token);
    } catch (error) {
      console.error('[auth] Failed to refresh user after email verification', error);
    }
  },

  /**
   * Validate a password-reset action code and return the target email.
   */
  async verifyPasswordResetActionCode(oobCode: string): Promise<string> {
    return verifyPasswordResetCode(firebaseAuth, oobCode);
  },

  /**
   * Complete a password reset with a validated action code.
   */
  async confirmPasswordReset(oobCode: string, newPassword: string): Promise<void> {
    await confirmPasswordReset(firebaseAuth, oobCode, newPassword);
  },

  /**
   * Reload the current user and refresh the ID token.
   */
  async refreshCurrentUser(): Promise<User | null> {
    const user = firebaseAuth.currentUser;
    if (!user) {
      setAuthToken(null);
      return null;
    }
    await user.reload();
    const token = await user.getIdToken(true);
    setAuthToken(token);
    return user;
  },

  /**
   * Return the current authenticated user, if any.
   */
  getCurrentUser(): User | null {
    return firebaseAuth.currentUser;
  },
};
