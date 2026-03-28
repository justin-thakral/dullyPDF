import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  getFreshIdToken: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('../../../src/services/auth', () => ({
  Auth: {
    signOut: authMocks.signOut,
  },
  getFreshIdToken: authMocks.getFreshIdToken,
}));

const importApiConfig = async () => {
  vi.resetModules();
  return import('../../../src/services/apiConfig');
};

describe('apiConfig', () => {
  beforeEach(() => {
    authMocks.getFreshIdToken.mockReset().mockResolvedValue(null);
    authMocks.signOut.mockReset().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('resolves and caches API base URL and joins segments via buildApiUrl', async () => {
    vi.stubEnv('VITE_API_URL', ' https://backend.local/ ');
    const { getApiBaseUrl, buildApiUrl } = await importApiConfig();

    expect(getApiBaseUrl()).toBe('https://backend.local');
    expect(buildApiUrl('api', '/saved-forms/', 'abc')).toBe('https://backend.local/api/saved-forms/abc');

    vi.stubEnv('VITE_API_URL', 'https://changed.local');
    expect(getApiBaseUrl()).toBe('https://backend.local');
  });

  it('removes repeated trailing slashes from API base URL env values', async () => {
    vi.stubEnv('VITE_API_URL', ' https://backend.local/// ');
    const { getApiBaseUrl, buildApiUrl, resolveApiUrl } = await importApiConfig();

    expect(getApiBaseUrl()).toBe('https://backend.local');
    expect(buildApiUrl('api', 'health')).toBe('https://backend.local/api/health');
    expect(resolveApiUrl('/api/v1/fill/tep-1.pdf')).toBe('https://backend.local/api/v1/fill/tep-1.pdf');
  });

  it('prefers the current site origin for production builds', async () => {
    vi.stubEnv('PROD', '1');
    vi.stubEnv('VITE_API_URL', 'https://broken-backend.run.app');
    vi.stubGlobal('window', { location: { origin: 'https://dullypdf.web.app' } });

    const { getApiBaseUrl, buildApiUrl } = await importApiConfig();

    expect(getApiBaseUrl()).toBe('https://dullypdf.web.app');
    expect(buildApiUrl('api', 'profile')).toBe('https://dullypdf.web.app/api/profile');
  });

  it('attaches bearer auth and retries once on 401 with refreshed token', async () => {
    authMocks.getFreshIdToken
      .mockResolvedValueOnce('token-initial')
      .mockResolvedValueOnce('token-refreshed');

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'expired' }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await importApiConfig();
    const response = await apiFetch('GET', '/api/protected');

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const firstHeaders = fetchMock.mock.calls[0][1].headers as Headers;
    const retryHeaders = fetchMock.mock.calls[1][1].headers as Headers;
    expect(firstHeaders.get('Authorization')).toBe('Bearer token-initial');
    expect(retryHeaders.get('Authorization')).toBe('Bearer token-refreshed');
    expect(authMocks.signOut).not.toHaveBeenCalled();
  });

  it('clears the auth session after a repeated 401 on an authenticated request', async () => {
    authMocks.getFreshIdToken
      .mockResolvedValueOnce('token-initial')
      .mockResolvedValueOnce('token-refreshed');

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Invalid Authorization token' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Invalid Authorization token' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await importApiConfig();

    await expect(apiFetch('GET', '/api/profile')).rejects.toMatchObject({
      message: 'Please sign in again to continue.',
      status: 401,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(authMocks.signOut).toHaveBeenCalledTimes(1);
  });

  it('polls backend health and retries transient Cloud Run cold-start GET failures', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response('The request was aborted because there was no available instance.', {
          status: 429,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ groups: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await importApiConfig();
    const response = await apiFetch('GET', '/api/groups');

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/health$/);
    expect(fetchMock.mock.calls[2][0]).toBe('/api/groups');
  });

  it('shares one backend warmup loop across concurrent readiness checks', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_API_URL', 'http://localhost:8000');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response('Rate exceeded.', {
          status: 429,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { ensureBackendReady } = await importApiConfig();
    const pending = Promise.all([ensureBackendReady(), ensureBackendReady()]);

    await vi.advanceTimersByTimeAsync(1000);
    await pending;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/health');
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8000/api/health');
  });

  it('keeps polling backend readiness beyond the initial cold-start window', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn();
    for (let attempt = 0; attempt < 6; attempt += 1) {
      fetchMock.mockResolvedValueOnce(
        new Response('Rate exceeded.', {
          status: 429,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }),
      );
    }
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { ensureBackendReady } = await importApiConfig();
    const pending = ensureBackendReady();

    await vi.runAllTimersAsync();
    await expect(pending).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it('injects dev admin token unless explicitly disabled', async () => {
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', 'admin-token');

    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await importApiConfig();
    await apiFetch('GET', '/api/admin-probe');

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get('x-admin-token')).toBe('admin-token');

    vi.unstubAllEnvs();
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', 'admin-token');
    vi.stubEnv('VITE_DISABLE_ADMIN_OVERRIDE', 'true');
    fetchMock.mockClear();

    const disabledModule = await importApiConfig();
    await disabledModule.apiFetch('GET', '/api/admin-probe');

    const disabledHeaders = fetchMock.mock.calls[0][1].headers as Headers;
    expect(disabledHeaders.get('x-admin-token')).toBeNull();
  });

  it('handles timeout aborts and external signal propagation', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await importApiConfig();
    const timedOut = apiFetch('GET', '/api/slow', { timeoutMs: 1000 });
    const timedOutAssertion = expect(timedOut).rejects.toThrow('Request timed out.');
    await vi.advanceTimersByTimeAsync(1000);
    await timedOutAssertion;

    vi.useRealTimers();
    fetchMock.mockResolvedValue(new Response('', { status: 200 }));
    const controller = new AbortController();
    await apiFetch('GET', '/api/with-signal', { signal: controller.signal });

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/with-signal',
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it('normalizes ApiError message/code and honors allowStatuses', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ message: 'Detailed failure', code: 'E_DETAILED' }), {
          status: 400,
          statusText: 'Bad Request',
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ message: 'token expired' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: 'not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response('', { status: 409, statusText: 'Conflict' }));

    vi.stubGlobal('fetch', fetchMock);

    const { ApiError, apiFetch } = await importApiConfig();

    const detailedError = apiFetch('GET', '/api/error-1');
    await expect(detailedError).rejects.toBeInstanceOf(ApiError);
    await expect(detailedError).rejects.toMatchObject({
      message: 'Detailed failure',
      status: 400,
      code: 'E_DETAILED',
    });

    await expect(apiFetch('GET', '/api/error-2')).rejects.toMatchObject({
      message: 'Please sign in again to continue.',
      status: 401,
    });

    await expect(apiFetch('GET', '/api/error-3')).rejects.toMatchObject({
      message: 'We could not find that resource.',
      status: 404,
    });

    const allowed = await apiFetch('GET', '/api/allowed', { allowStatuses: [409] });
    expect(allowed.status).toBe(409);
  });
});
