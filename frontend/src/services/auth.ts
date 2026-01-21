/**
 * Firebase auth wrappers used across the UI.
 */
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  onIdTokenChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  updateProfile,
} from 'firebase/auth';
import type { User } from 'firebase/auth';
import { firebaseAuth } from './firebaseClient';
import { setAuthToken } from './authTokenStore';

export type AuthStateListener = (user: User | null) => void;

let idTokenListenerInitialised = false;

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
      await sendEmailVerification(credential.user);
    }
    const token = await credential.user.getIdToken();
    setAuthToken(token);
    return credential.user;
  },

  /**
   * Send a password reset email.
   */
  async sendPasswordReset(email: string): Promise<void> {
    await sendPasswordResetEmail(firebaseAuth, email);
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
    await sendEmailVerification(user);
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
