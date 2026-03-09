import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const firebaseAuthRef = vi.hoisted(() => ({
  currentUser: null as any,
}));

const firebaseMocks = vi.hoisted(() => ({
  applyActionCode: vi.fn(),
  confirmPasswordReset: vi.fn(),
  createUserWithEmailAndPassword: vi.fn(),
  onAuthStateChanged: vi.fn(),
  onIdTokenChanged: vi.fn(),
  sendEmailVerification: vi.fn(),
  sendPasswordResetEmail: vi.fn(),
  signInWithEmailAndPassword: vi.fn(),
  signOut: vi.fn(),
  updateProfile: vi.fn(),
  verifyPasswordResetCode: vi.fn(),
}));

const tokenStoreMocks = vi.hoisted(() => ({
  setAuthToken: vi.fn(),
}));

vi.mock('../../../src/services/firebaseClient', () => ({
  firebaseAuth: firebaseAuthRef,
}));

vi.mock('../../../src/services/authTokenStore', () => ({
  setAuthToken: tokenStoreMocks.setAuthToken,
}));

vi.mock('firebase/auth', () => ({
  applyActionCode: firebaseMocks.applyActionCode,
  confirmPasswordReset: firebaseMocks.confirmPasswordReset,
  createUserWithEmailAndPassword: firebaseMocks.createUserWithEmailAndPassword,
  onAuthStateChanged: firebaseMocks.onAuthStateChanged,
  onIdTokenChanged: firebaseMocks.onIdTokenChanged,
  sendEmailVerification: firebaseMocks.sendEmailVerification,
  sendPasswordResetEmail: firebaseMocks.sendPasswordResetEmail,
  signInWithEmailAndPassword: firebaseMocks.signInWithEmailAndPassword,
  signOut: firebaseMocks.signOut,
  updateProfile: firebaseMocks.updateProfile,
  verifyPasswordResetCode: firebaseMocks.verifyPasswordResetCode,
}));

const importAuthModule = async () => {
  vi.resetModules();
  return import('../../../src/services/auth');
};

describe('auth service', () => {
  beforeEach(() => {
    firebaseAuthRef.currentUser = null;
    for (const mock of Object.values(firebaseMocks)) {
      mock.mockReset();
    }
    tokenStoreMocks.setAuthToken.mockReset();

    firebaseMocks.onAuthStateChanged.mockImplementation((_auth, callback) => {
      callback(null);
      return vi.fn();
    });
    firebaseMocks.onIdTokenChanged.mockImplementation(() => vi.fn());
    firebaseMocks.signOut.mockResolvedValue(undefined);
    firebaseMocks.sendPasswordResetEmail.mockResolvedValue(undefined);
    firebaseMocks.sendEmailVerification.mockResolvedValue(undefined);
    firebaseMocks.updateProfile.mockResolvedValue(undefined);
    firebaseMocks.applyActionCode.mockResolvedValue(undefined);
    firebaseMocks.verifyPasswordResetCode.mockResolvedValue('reset@example.com');
    firebaseMocks.confirmPasswordReset.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('registers ID token listener once and updates token store on auth token changes', async () => {
    let onIdTokenChangedCallback: ((user: any) => Promise<void> | void) | null = null;
    firebaseMocks.onIdTokenChanged.mockImplementation((_auth, callback) => {
      onIdTokenChangedCallback = callback;
      return vi.fn();
    });

    const { Auth, getFreshIdToken } = await importAuthModule();

    expect(firebaseMocks.onIdTokenChanged).toHaveBeenCalledTimes(1);

    Auth.onAuthStateChanged(vi.fn());
    await getFreshIdToken();
    expect(firebaseMocks.onIdTokenChanged).toHaveBeenCalledTimes(1);

    await onIdTokenChangedCallback?.(null);
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith(null);

    const tokenUser = {
      getIdToken: vi.fn().mockResolvedValue('id-token-1'),
    };
    await onIdTokenChangedCallback?.(tokenUser);
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith('id-token-1');
  });

  it('returns fresh token when current user exists and null on missing/failure cases', async () => {
    const { getFreshIdToken } = await importAuthModule();

    firebaseAuthRef.currentUser = null;
    await expect(getFreshIdToken()).resolves.toBeNull();
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith(null);

    const user = {
      getIdToken: vi.fn().mockResolvedValue('fresh-token'),
    };
    firebaseAuthRef.currentUser = user;
    await expect(getFreshIdToken(true)).resolves.toBe('fresh-token');
    expect(user.getIdToken).toHaveBeenCalledWith(true);
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith('fresh-token');

    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    firebaseAuthRef.currentUser = {
      getIdToken: vi.fn().mockRejectedValue(new Error('token failed')),
    };
    await expect(getFreshIdToken()).resolves.toBeNull();
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith(null);
    consoleSpy.mockRestore();
  });

  it('handles sign-in and sign-up flows including profile update, verification email, and token persistence', async () => {
    const signInUser = {
      getIdToken: vi.fn().mockResolvedValue('signin-token'),
      emailVerified: true,
    };
    firebaseMocks.signInWithEmailAndPassword.mockResolvedValue({ user: signInUser });

    const signUpUser = {
      getIdToken: vi.fn().mockResolvedValue('signup-token'),
      emailVerified: false,
    };
    firebaseMocks.createUserWithEmailAndPassword.mockResolvedValue({ user: signUpUser });

    const { Auth } = await importAuthModule();

    const signedIn = await Auth.signIn('user@example.com', 'secret');
    expect(signedIn).toBe(signInUser);
    expect(firebaseMocks.signInWithEmailAndPassword).toHaveBeenCalledWith(
      firebaseAuthRef,
      'user@example.com',
      'secret',
    );
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith('signin-token');

    const signedUp = await Auth.signUp('new@example.com', 'secret', '  Jane Smith  ');
    expect(signedUp).toBe(signUpUser);
    expect(firebaseMocks.updateProfile).toHaveBeenCalledWith(signUpUser, { displayName: 'Jane Smith' });
    expect(firebaseMocks.sendEmailVerification).toHaveBeenCalledWith(signUpUser, {
      url: window.location.origin,
      handleCodeInApp: false,
    });
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith('signup-token');
  });

  it('uses fallback email action settings in non-browser environments', async () => {
    const signUpUser = {
      getIdToken: vi.fn().mockResolvedValue('signup-token'),
      emailVerified: false,
    };
    firebaseMocks.createUserWithEmailAndPassword.mockResolvedValue({ user: signUpUser });

    vi.stubGlobal('window', undefined as unknown as Window & typeof globalThis);

    const { Auth } = await importAuthModule();
    await Auth.signUp('new@example.com', 'secret');

    expect(firebaseMocks.sendEmailVerification).toHaveBeenCalledWith(signUpUser);
  });

  it('supports password reset, sign-out, verification resend, reset helpers, action-code apply, and refresh helpers', async () => {
    const { Auth } = await importAuthModule();

    await Auth.sendPasswordReset('reset@example.com');
    expect(firebaseMocks.sendPasswordResetEmail).toHaveBeenCalledWith(firebaseAuthRef, 'reset@example.com');

    await Auth.signOut();
    expect(firebaseMocks.signOut).toHaveBeenCalledWith(firebaseAuthRef);
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith(null);

    firebaseAuthRef.currentUser = null;
    await expect(Auth.sendVerificationEmail()).rejects.toThrow('No authenticated user found.');
    await expect(Auth.verifyPasswordResetActionCode('reset-code')).resolves.toBe('reset@example.com');
    expect(firebaseMocks.verifyPasswordResetCode).toHaveBeenCalledWith(firebaseAuthRef, 'reset-code');
    await Auth.confirmPasswordReset('reset-code', 'new-secret-123');
    expect(firebaseMocks.confirmPasswordReset).toHaveBeenCalledWith(
      firebaseAuthRef,
      'reset-code',
      'new-secret-123',
    );

    await Auth.applyEmailVerificationCode('verify-code');
    expect(firebaseMocks.applyActionCode).toHaveBeenCalledWith(firebaseAuthRef, 'verify-code');

    const verifiedUser = {
      reload: vi.fn().mockResolvedValue(undefined),
      getIdToken: vi.fn().mockResolvedValue('refresh-token'),
    };
    firebaseAuthRef.currentUser = verifiedUser;

    await Auth.sendVerificationEmail();
    expect(firebaseMocks.sendEmailVerification).toHaveBeenCalledWith(verifiedUser, {
      url: window.location.origin,
      handleCodeInApp: false,
    });

    await Auth.applyEmailVerificationCode('verify-code-2');
    expect(firebaseMocks.applyActionCode).toHaveBeenCalledWith(firebaseAuthRef, 'verify-code-2');
    expect(verifiedUser.reload).toHaveBeenCalledTimes(1);
    expect(verifiedUser.getIdToken).toHaveBeenCalledWith(true);

    const refreshed = await Auth.refreshCurrentUser();
    expect(refreshed).toBe(verifiedUser);
    expect(verifiedUser.reload).toHaveBeenCalledTimes(2);
    expect(verifiedUser.getIdToken).toHaveBeenLastCalledWith(true);
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith('refresh-token');

    firebaseAuthRef.currentUser = null;
    await expect(Auth.refreshCurrentUser()).resolves.toBeNull();
    expect(tokenStoreMocks.setAuthToken).toHaveBeenCalledWith(null);
    expect(Auth.getCurrentUser()).toBeNull();
  });
});
