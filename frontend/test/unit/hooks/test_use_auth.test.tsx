import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '../../../src/hooks/useAuth';

const onAuthStateChangedMock = vi.hoisted(() => vi.fn(() => vi.fn()));
const signOutMock = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const refreshCurrentUserMock = vi.hoisted(() => vi.fn());
const setAuthTokenMock = vi.hoisted(() => vi.fn());
const getProfileMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/auth', () => ({
  Auth: {
    onAuthStateChanged: onAuthStateChangedMock,
    signOut: signOutMock,
    refreshCurrentUser: refreshCurrentUserMock,
  },
}));

vi.mock('../../../src/services/authTokenStore', () => ({
  setAuthToken: setAuthTokenMock,
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    getProfile: getProfileMock,
  },
}));

function makeAuthUser() {
  return {
    uid: 'user-1',
    email: 'user@example.com',
    emailVerified: true,
    providerData: [{ providerId: 'google.com' }],
    getIdTokenResult: vi.fn().mockResolvedValue({
      token: 'token-1',
      signInProvider: 'google.com',
    }),
  } as any;
}

function renderHookHarness() {
  let latest: ReturnType<typeof useAuth> | null = null;
  const clearSavedFormsRetry = vi.fn();
  const clearSavedForms = vi.fn();
  const refreshSavedForms = vi.fn().mockResolvedValue([]);

  function Harness() {
    latest = useAuth({
      clearSavedFormsRetry,
      clearSavedForms,
      refreshSavedForms,
    });
    return null;
  }

  const rendered = render(<Harness />);

  return {
    clearSavedFormsRetry,
    clearSavedForms,
    refreshSavedForms,
    unmount: rendered.unmount,
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useAuth', () => {
  beforeEach(() => {
    onAuthStateChangedMock.mockClear();
    signOutMock.mockClear();
    refreshCurrentUserMock.mockReset();
    setAuthTokenMock.mockClear();
    getProfileMock.mockReset().mockResolvedValue(null);
  });

  it('shares one in-flight profile refresh request across repeated callers', async () => {
    const hook = renderHookHarness();

    await act(async () => {
      await hook.current.syncAuthSession(makeAuthUser(), {
        forceTokenRefresh: false,
        deferSavedForms: true,
      });
    });

    getProfileMock.mockClear();
    let resolveProfile: ((value: null) => void) | null = null;
    getProfileMock.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProfile = resolve as (value: null) => void;
    }));

    let firstPromise: Promise<unknown> | null = null;
    let secondPromise: Promise<unknown> | null = null;
    act(() => {
      firstPromise = hook.current.loadUserProfile();
      secondPromise = hook.current.loadUserProfile();
    });

    expect(getProfileMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveProfile?.(null);
      await Promise.all([firstPromise, secondPromise]);
    });

    expect(hook.current.profileLoading).toBe(false);
  });
});
