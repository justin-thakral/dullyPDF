import { afterEach, describe, expect, it, vi } from 'vitest';

const VALID_ENV: Record<string, string> = {
  VITE_FIREBASE_API_KEY: 'api-key',
  VITE_FIREBASE_AUTH_DOMAIN: 'example.firebaseapp.com',
  VITE_FIREBASE_PROJECT_ID: 'project-id',
  VITE_FIREBASE_APP_ID: 'app-id',
  VITE_FIREBASE_STORAGE_BUCKET: 'project-id.appspot.com',
  VITE_FIREBASE_MESSAGING_SENDER_ID: '1234567890',
};

const importConfigModule = async () => {
  vi.resetModules();
  return import('../../../src/config/firebaseConfig');
};

describe('firebaseConfig env parsing', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('parses and trims all required VITE_FIREBASE_* values', async () => {
    for (const [key, value] of Object.entries(VALID_ENV)) {
      vi.stubEnv(key, `   ${value}   `);
    }

    const { firebaseConfig } = await importConfigModule();

    expect(firebaseConfig).toEqual({
      apiKey: VALID_ENV.VITE_FIREBASE_API_KEY,
      authDomain: VALID_ENV.VITE_FIREBASE_AUTH_DOMAIN,
      projectId: VALID_ENV.VITE_FIREBASE_PROJECT_ID,
      appId: VALID_ENV.VITE_FIREBASE_APP_ID,
      storageBucket: VALID_ENV.VITE_FIREBASE_STORAGE_BUCKET,
      messagingSenderId: VALID_ENV.VITE_FIREBASE_MESSAGING_SENDER_ID,
    });
  });

  it.each(Object.keys(VALID_ENV))('throws a clear error when %s is missing or blank', async (missingKey) => {
    for (const [key, value] of Object.entries(VALID_ENV)) {
      vi.stubEnv(key, key === missingKey ? '   ' : value);
    }

    await expect(importConfigModule()).rejects.toThrow(
      `Missing ${missingKey}. Set it in your Vite env file.`,
    );
  });

  it('exports the expected firebase config shape', async () => {
    for (const [key, value] of Object.entries(VALID_ENV)) {
      vi.stubEnv(key, value);
    }

    const module = await importConfigModule();

    expect(Object.keys(module.firebaseConfig).sort()).toEqual([
      'apiKey',
      'appId',
      'authDomain',
      'messagingSenderId',
      'projectId',
      'storageBucket',
    ]);
  });
});
