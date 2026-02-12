import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiConfigMocks = vi.hoisted(() => ({
  buildApiUrl: vi.fn(),
  apiFetch: vi.fn(),
  apiJsonFetch: vi.fn(),
}));

vi.mock('../../../src/services/apiConfig', () => ({
  buildApiUrl: apiConfigMocks.buildApiUrl,
  apiFetch: apiConfigMocks.apiFetch,
  apiJsonFetch: apiConfigMocks.apiJsonFetch,
}));

import { DB } from '../../fixtures/legacy/db';

const baseConfig = {
  type: 'postgres' as const,
  host: 'localhost',
  port: 5432,
  database: 'healthdb',
  schema: 'public',
  view: 'vw_form_fields',
  user: 'readonly',
  password: 'pw',
};

describe('legacy DB service', () => {
  beforeEach(() => {
    apiConfigMocks.buildApiUrl.mockReset();
    apiConfigMocks.apiFetch.mockReset();
    apiConfigMocks.apiJsonFetch.mockReset();

    apiConfigMocks.buildApiUrl.mockImplementation((...segments: string[]) => {
      const path = segments.filter(Boolean).join('/');
      return `https://api.test/${path}`;
    });

    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it('uses admin token precedence override -> env -> localStorage in dev mode', async () => {
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', ' env-token ');
    window.localStorage.setItem('dullypdf_admin_token', ' local-token ');

    apiConfigMocks.apiFetch.mockResolvedValue({ ok: true } as Response);
    apiConfigMocks.apiJsonFetch.mockResolvedValue({
      success: true,
      connId: 'conn-1',
      columns: ['mrn', 'first_name'],
      identifierKey: 'mrn',
    });

    await DB.testAndCreate(baseConfig, '  override-token  ');
    expect(apiConfigMocks.apiFetch).toHaveBeenLastCalledWith(
      'POST',
      'https://api.test/api/connections/test',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          'x-admin-token': 'override-token',
        },
      }),
    );

    apiConfigMocks.apiJsonFetch.mockResolvedValue({ columns: ['id'] });
    await DB.fetchColumns('conn-2');
    expect(apiConfigMocks.apiFetch).toHaveBeenLastCalledWith(
      'GET',
      'https://api.test/api/db/columns?connId=conn-2',
      { headers: { 'x-admin-token': 'env-token' } },
    );

    vi.stubEnv('VITE_ADMIN_TOKEN', '');
    apiConfigMocks.apiJsonFetch.mockResolvedValue({ rows: [{ id: 1 }] });
    await DB.searchRows('conn-3', 'mrn', 'abc', { mode: 'equals', limit: 10 });
    expect(apiConfigMocks.apiFetch).toHaveBeenLastCalledWith(
      'GET',
      'https://api.test/api/db/search?connId=conn-3&key=mrn&query=abc&mode=equals&limit=10',
      { headers: { 'x-admin-token': 'local-token' } },
    );
  });

  it('builds expected endpoints and query params for db helpers', async () => {
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', 'token');

    apiConfigMocks.apiFetch.mockResolvedValue({ ok: true } as Response);
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ success: true, connId: 'conn-1', columns: ['mrn'] })
      .mockResolvedValueOnce({ columns: ['mrn', 'last_name'] })
      .mockResolvedValueOnce({ rows: [{ mrn: '123' }] });

    await DB.testAndCreate(baseConfig);
    await DB.fetchColumns('conn-1');
    await DB.searchRows('conn-1', 'mrn', '123');
    await DB.disconnect('conn-1');

    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'connections', 'test');
    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'db', 'columns');
    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'db', 'search');
    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'connections', 'conn-1');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      'GET',
      'https://api.test/api/db/search?connId=conn-1&key=mrn&query=123&mode=contains&limit=25',
      { headers: { 'x-admin-token': 'token' } },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      4,
      'DELETE',
      'https://api.test/api/connections/conn-1',
      { headers: { 'x-admin-token': 'token' } },
    );
  });

  it('throws when testAndCreate reports failure and normalizes empty column/row payloads', async () => {
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', '');
    window.localStorage.removeItem('dullypdf_admin_token');

    apiConfigMocks.apiFetch.mockResolvedValue({ ok: true } as Response);
    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({ success: false, connId: 'conn-x' });

    await expect(DB.testAndCreate(baseConfig)).rejects.toThrow('Connection test failed');
    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith(
      'POST',
      'https://api.test/api/connections/test',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
        },
      }),
    );

    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({ columns: null });
    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({ rows: null });
    await expect(DB.fetchColumns('conn-x')).resolves.toEqual([]);
    await expect(DB.searchRows('conn-x', 'id', '123')).resolves.toEqual([]);
  });

  it('omits admin headers entirely outside dev mode', async () => {
    vi.stubEnv('DEV', '');
    vi.stubEnv('VITE_ADMIN_TOKEN', 'env-token');
    window.localStorage.setItem('dullypdf_admin_token', 'local-token');

    apiConfigMocks.apiFetch.mockResolvedValue({ ok: true } as Response);
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ columns: ['id'] })
      .mockResolvedValueOnce({ rows: [{ id: 1 }] });

    await DB.fetchColumns('conn-no-admin');
    await DB.searchRows('conn-no-admin', 'id', '1');
    await DB.disconnect('conn-no-admin');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      1,
      'GET',
      'https://api.test/api/db/columns?connId=conn-no-admin',
      { headers: undefined },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      'GET',
      'https://api.test/api/db/search?connId=conn-no-admin&key=id&query=1&mode=contains&limit=25',
      { headers: undefined },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      'DELETE',
      'https://api.test/api/connections/conn-no-admin',
      { headers: {} },
    );
  });

  it('respects VITE_DISABLE_ADMIN_OVERRIDE in dev mode', async () => {
    vi.stubEnv('DEV', '1');
    vi.stubEnv('VITE_DISABLE_ADMIN_OVERRIDE', '1');
    vi.stubEnv('VITE_ADMIN_TOKEN', 'env-token');
    window.localStorage.setItem('dullypdf_admin_token', 'local-token');

    apiConfigMocks.apiFetch.mockResolvedValue({ ok: true } as Response);
    apiConfigMocks.apiJsonFetch.mockResolvedValue({ columns: ['id'] });

    await DB.fetchColumns('conn-disable-admin');

    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith(
      'GET',
      'https://api.test/api/db/columns?connId=conn-disable-admin',
      { headers: undefined },
    );
  });
});
