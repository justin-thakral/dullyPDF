import { describe, expect, it, vi } from 'vitest';

const firebaseAppMocks = vi.hoisted(() => ({
  initializeApp: vi.fn(),
  getApps: vi.fn(),
  getApp: vi.fn(),
  getAuth: vi.fn(),
  firebaseConfig: {
    apiKey: 'k',
    authDomain: 'd',
    projectId: 'p',
    appId: 'a',
    storageBucket: 's',
    messagingSenderId: 'm',
  },
}));

vi.mock('../../../src/config/firebaseConfig', () => ({
  firebaseConfig: firebaseAppMocks.firebaseConfig,
}));

vi.mock('firebase/app', () => ({
  initializeApp: firebaseAppMocks.initializeApp,
  getApps: firebaseAppMocks.getApps,
  getApp: firebaseAppMocks.getApp,
}));

vi.mock('firebase/auth', () => ({
  getAuth: firebaseAppMocks.getAuth,
}));

const importFirebaseClient = async () => {
  vi.resetModules();
  return import('../../../src/services/firebaseClient');
};

describe('firebaseClient', () => {
  it('initializes a new app when no Firebase app exists', async () => {
    firebaseAppMocks.getApps.mockReturnValue([]);

    const createdApp = { name: 'created-app' };
    const authInstance = { kind: 'auth-instance' };
    firebaseAppMocks.initializeApp.mockReturnValue(createdApp);
    firebaseAppMocks.getAuth.mockReturnValue(authInstance);

    const module = await importFirebaseClient();

    expect(firebaseAppMocks.initializeApp).toHaveBeenCalledWith(firebaseAppMocks.firebaseConfig);
    expect(firebaseAppMocks.getApp).not.toHaveBeenCalled();
    expect(firebaseAppMocks.getAuth).toHaveBeenCalledWith(createdApp);
    expect(module.firebaseApp).toBe(createdApp);
    expect(module.firebaseAuth).toBe(authInstance);
  });

  it('reuses the existing app when one is already initialized', async () => {
    firebaseAppMocks.getApps.mockReturnValue([{}]);

    const existingApp = { name: 'existing-app' };
    const authInstance = { kind: 'auth-instance' };
    firebaseAppMocks.getApp.mockReturnValue(existingApp);
    firebaseAppMocks.getAuth.mockReturnValue(authInstance);

    const module = await importFirebaseClient();

    expect(firebaseAppMocks.initializeApp).not.toHaveBeenCalled();
    expect(firebaseAppMocks.getApp).toHaveBeenCalledTimes(1);
    expect(firebaseAppMocks.getAuth).toHaveBeenCalledWith(existingApp);
    expect(module.firebaseApp).toBe(existingApp);
    expect(module.firebaseAuth).toBe(authInstance);
  });
});
