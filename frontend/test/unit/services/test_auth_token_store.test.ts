import { describe, expect, it, vi } from 'vitest';

const importStoreModule = async () => {
  vi.resetModules();
  return import('../../../src/services/authTokenStore');
};

describe('authTokenStore', () => {
  it('starts with a null token and exposes reads via getAuthToken', async () => {
    const { getAuthToken } = await importStoreModule();
    expect(getAuthToken()).toBeNull();
  });

  it('notifies listeners when setAuthToken updates the store', async () => {
    const { onTokenChanged, setAuthToken } = await importStoreModule();

    const listener = vi.fn();
    const unsubscribe = onTokenChanged(listener);

    setAuthToken('token-1');
    setAuthToken(null);

    expect(listener).toHaveBeenNthCalledWith(1, 'token-1');
    expect(listener).toHaveBeenNthCalledWith(2, null);

    unsubscribe();
  });

  it('stops notifying listeners after unsubscribe', async () => {
    const { onTokenChanged, setAuthToken } = await importStoreModule();

    const listener = vi.fn();
    const unsubscribe = onTokenChanged(listener);
    unsubscribe();

    setAuthToken('token-1');

    expect(listener).not.toHaveBeenCalled();
  });

  it('isolates listener errors so remaining listeners still receive updates', async () => {
    const { onTokenChanged, setAuthToken } = await importStoreModule();

    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const badListener = vi.fn(() => {
      throw new Error('boom');
    });
    const goodListener = vi.fn();

    onTokenChanged(badListener);
    onTokenChanged(goodListener);

    setAuthToken('token-2');

    expect(badListener).toHaveBeenCalledWith('token-2');
    expect(goodListener).toHaveBeenCalledWith('token-2');
    expect(consoleSpy).toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});
