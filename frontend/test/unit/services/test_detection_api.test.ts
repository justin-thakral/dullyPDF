import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiJsonFetch: vi.fn(),
}));

vi.mock('../../../src/services/apiConfig', () => ({
  apiFetch: apiMocks.apiFetch,
  apiJsonFetch: apiMocks.apiJsonFetch,
}));

const importDetectionApi = async () => {
  vi.resetModules();
  return import('../../../src/services/detectionApi');
};

describe('detectionApi', () => {
  beforeEach(() => {
    apiMocks.apiFetch.mockReset();
    apiMocks.apiJsonFetch.mockReset();
    vi.stubEnv('VITE_DETECTION_API_URL', '');
    vi.stubEnv('VITE_SANDBOX_API_URL', '');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it('selects detection API base from env and falls back to localhost', async () => {
    vi.stubEnv('VITE_DETECTION_API_URL', ' https://detect.local/ ');
    let module = await importDetectionApi();
    expect(module.getDetectionApiBase()).toBe('https://detect.local');

    vi.stubEnv('VITE_DETECTION_API_URL', '');
    vi.stubEnv('VITE_SANDBOX_API_URL', ' https://sandbox.local/// ');
    module = await importDetectionApi();
    expect(module.getDetectionApiBase()).toBe('https://sandbox.local');

    vi.stubEnv('VITE_DETECTION_API_URL', '');
    vi.stubEnv('VITE_SANDBOX_API_URL', '');
    module = await importDetectionApi();
    expect(module.getDetectionApiBase()).toBe('http://localhost:8000');
  });

  it('builds detect request form data and returns immediate payloads when polling is unnecessary', async () => {
    const module = await importDetectionApi();
    apiMocks.apiFetch
      .mockResolvedValueOnce({ id: 'start-1' })
      .mockResolvedValueOnce({ id: 'start-2' });
    apiMocks.apiJsonFetch
      .mockResolvedValueOnce({ status: 'complete', sessionId: 's-1', fields: [{ name: 'A' }] })
      .mockResolvedValueOnce({ status: 'accepted' });

    const file = new File(['pdf'], 'a.pdf', { type: 'application/pdf' });

    const complete = await module.detectFields(file, {
      pipeline: 'commonforms',
      prewarmRename: true,
      prewarmRemap: true,
    });
    const accepted = await module.detectFields(file);

    expect(complete.status).toBe('complete');
    expect(complete.fields).toHaveLength(1);
    expect(accepted).toEqual({ status: 'accepted' });

    const firstCall = apiMocks.apiFetch.mock.calls[0];
    expect(firstCall[0]).toBe('POST');
    expect(firstCall[1]).toBe('http://localhost:8000/detect-fields');

    const formData = firstCall[2].body as FormData;
    expect((formData.get('file') as File).name).toBe('a.pdf');
    expect(formData.get('pipeline')).toBe('commonforms');
    expect(formData.get('prewarmRename')).toBe('true');
    expect(formData.get('prewarmRemap')).toBe('true');

    const secondCall = apiMocks.apiFetch.mock.calls[1];
    const secondFormData = secondCall[2].body as FormData;
    expect(secondFormData.get('prewarmRename')).toBeNull();
    expect(secondFormData.get('prewarmRemap')).toBeNull();
  });

  it('polls running sessions to completion and emits status updates', async () => {
    vi.useFakeTimers();
    const module = await importDetectionApi();

    apiMocks.apiFetch.mockResolvedValue({});
    apiMocks.apiJsonFetch
      .mockResolvedValueOnce({ sessionId: 'sess-1', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-1', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-1', status: 'complete', fields: [{ name: 'A' }] });

    const onStatus = vi.fn();
    const resultPromise = module.detectFields(new File(['pdf'], 'poll.pdf', { type: 'application/pdf' }), {
      onStatus,
    });

    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(result.status).toBe('complete');
    expect(onStatus).toHaveBeenNthCalledWith(1, { sessionId: 'sess-1', status: 'running' });
    expect(onStatus).toHaveBeenNthCalledWith(2, { sessionId: 'sess-1', status: 'running' });
    expect(onStatus).toHaveBeenNthCalledWith(3, {
      sessionId: 'sess-1',
      status: 'complete',
      fields: [{ name: 'A' }],
    });
  });

  it('throws on failed status and returns timedOut payload after deadline', async () => {
    vi.useFakeTimers();
    const module = await importDetectionApi();

    apiMocks.apiFetch.mockResolvedValue({});
    apiMocks.apiJsonFetch
      .mockResolvedValueOnce({ sessionId: 'sess-fail', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-fail', status: 'failed', error: 'detector failed' });

    const failedPromise = module.detectFields(new File(['pdf'], 'fail.pdf', { type: 'application/pdf' }));
    await expect(failedPromise).rejects.toThrow('detector failed');

    const timedOut = await module.pollDetectionStatus('sess-timeout', { timeoutMs: 0 });
    expect(timedOut).toEqual({
      sessionId: 'sess-timeout',
      status: 'running',
      timedOut: true,
    });
  });

  it('applies backoff waits and keeps polling even when session touch fails', async () => {
    vi.useFakeTimers();
    const module = await importDetectionApi();

    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    apiMocks.apiFetch.mockImplementation((method: string, url: string) => {
      if (method === 'POST' && url.startsWith('/api/sessions/')) {
        return Promise.reject(new Error('touch failed'));
      }
      return Promise.resolve({});
    });

    apiMocks.apiJsonFetch
      .mockResolvedValueOnce({ sessionId: 'sess-2', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-2', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-2', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-2', status: 'complete', fields: [] });

    const resultPromise = module.detectFields(new File(['pdf'], 'backoff.pdf', { type: 'application/pdf' }));
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(result.status).toBe('complete');
    expect(
      apiMocks.apiFetch.mock.calls.some(
        (call) => call[0] === 'POST' && String(call[1]).includes('/api/sessions/sess-2/touch'),
      ),
    ).toBe(true);

    const timeoutDurations = timeoutSpy.mock.calls
      .map((call) => Number(call[1]))
      .filter((duration) => Number.isFinite(duration));
    expect(timeoutDurations).toContain(1500);
    expect(timeoutDurations).toContain(3000);

    timeoutSpy.mockRestore();
  });

  it('uses detection API base for session touch calls', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_DETECTION_API_URL', 'https://detect.example.com/');
    const module = await importDetectionApi();

    apiMocks.apiFetch.mockImplementation((method: string, url: string) => {
      if (method === 'POST' && String(url).includes('/api/sessions/')) {
        return Promise.reject(new Error('touch failed'));
      }
      return Promise.resolve({});
    });

    apiMocks.apiJsonFetch
      .mockResolvedValueOnce({ sessionId: 'sess-touch', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-touch', status: 'running' })
      .mockResolvedValueOnce({ sessionId: 'sess-touch', status: 'complete', fields: [] });

    const resultPromise = module.detectFields(new File(['pdf'], 'touch.pdf', { type: 'application/pdf' }));
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(result.status).toBe('complete');

    const touchCall = apiMocks.apiFetch.mock.calls.find(
      (call) => call[0] === 'POST' && String(call[1]).includes('/api/sessions/sess-touch/touch'),
    );
    expect(touchCall).toBeDefined();
    expect(String(touchCall?.[1])).toBe('https://detect.example.com/api/sessions/sess-touch/touch');
  });

  it('exposes polling and fetch wrappers for explicit status checks', async () => {
    const module = await importDetectionApi();

    apiMocks.apiFetch.mockResolvedValueOnce({ id: 'fetch-status' });
    apiMocks.apiJsonFetch.mockResolvedValueOnce({ sessionId: 'sess-3', status: 'running' });

    const status = await module.fetchDetectionStatus('sess-3');
    expect(status).toEqual({ sessionId: 'sess-3', status: 'running' });
    expect(apiMocks.apiFetch).toHaveBeenCalledWith(
      'GET',
      'http://localhost:8000/detect-fields/sess-3',
    );

    const timedOut = await module.pollDetectionStatus('sess-4', { timeoutMs: 0 });
    expect(timedOut.timedOut).toBe(true);
  });
});
