import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  onIdTokenChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  updateProfile,
} from 'firebase/auth';
import type { User } from 'firebase/auth';
import { firebaseAuth } from './firebaseClient';
import { setAuthToken } from './authTokenStore';

/**
 * Centralized authentication helper built on Firebase Identity Platform.
 * Exposes thin wrappers used across the application to sign users in/out
 * and listen for state changes.
 */

export type AuthStateListener = (user: User | null) => void;

let idTokenListenerInitialised = false;

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
  onAuthStateChanged(callback: AuthStateListener) {
    ensureIdTokenListener();
    return onAuthStateChanged(firebaseAuth, callback);
  },

  async signIn(email: string, password: string): Promise<User> {
    ensureIdTokenListener();
    const credential = await signInWithEmailAndPassword(firebaseAuth, email, password);
    const token = await credential.user.getIdToken();
    setAuthToken(token);
    return credential.user;
  },

  async signUp(email: string, password: string, displayName?: string): Promise<User> {
    ensureIdTokenListener();
    const credential = await createUserWithEmailAndPassword(firebaseAuth, email, password);
    if (displayName && displayName.trim().length) {
      await updateProfile(credential.user, { displayName: displayName.trim() });
    }
    const token = await credential.user.getIdToken();
    setAuthToken(token);
    return credential.user;
  },

  async sendPasswordReset(email: string): Promise<void> {
    await sendPasswordResetEmail(firebaseAuth, email);
  },

  async signOut(): Promise<void> {
    await firebaseSignOut(firebaseAuth);
    setAuthToken(null);
  },

  getCurrentUser(): User | null {
    return firebaseAuth.currentUser;
  },
};
