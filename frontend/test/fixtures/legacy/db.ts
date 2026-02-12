/**
 * API helpers for database connection workflows.
 */
import { buildApiUrl, apiFetch, apiJsonFetch } from '../../../src/services/apiConfig';

export type DbType = 'postgres' | 'sqlserver';

/**
 * Resolve an admin token from override, env, or localStorage.
 */
function resolveAdminToken(override?: string): string | null {
  const env = (import.meta as any)?.env;
  const isDev = Boolean(env?.DEV);
  if (!isDev) return null;
  const disableRaw = typeof env?.VITE_DISABLE_ADMIN_OVERRIDE === 'string'
    ? env.VITE_DISABLE_ADMIN_OVERRIDE.trim().toLowerCase()
    : '';
  if (disableRaw && ['1', 'true', 'yes'].includes(disableRaw)) {
    return null;
  }
  if (override && override.trim()) return override.trim();
  const raw = typeof env?.VITE_ADMIN_TOKEN === 'string' ? env.VITE_ADMIN_TOKEN.trim() : '';
  if (raw) return raw;
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage?.getItem('dullypdf_admin_token');
    return stored && stored.trim() ? stored.trim() : null;
  } catch {
    return null;
  }
}

export interface DbConnectionConfig {
  type: DbType;
  host: string;
  port?: number | string;
  database: string;
  schema?: string;
  view: string;
  user: string;
  password: string;
  ssl?: boolean;
  encrypt?: boolean;
  trustServerCertificate?: boolean;
}

export const DB = {
  /**
   * Test a database connection and create a temporary connection record.
   */
  async testAndCreate(
    config: DbConnectionConfig,
    adminToken?: string,
  ): Promise<{ connId: string; columns: string[]; identifierKey?: string }> {
    const resolvedToken = resolveAdminToken(adminToken);
    const res = await apiFetch('POST', buildApiUrl('api', 'connections', 'test'), {
      headers: {
        'Content-Type': 'application/json',
        ...(resolvedToken ? { 'x-admin-token': resolvedToken } : {}),
      },
      body: JSON.stringify(config),
    });
    const data = await apiJsonFetch<{
      success?: boolean;
      connId: string;
      columns?: string[];
      identifierKey?: string;
    }>(res);
    if (!data?.success) {
      throw new Error('Connection test failed');
    }
    return { connId: data.connId, columns: data.columns || [], identifierKey: data.identifierKey };
  },

  /**
   * Fetch column names for a stored connection.
   */
  async fetchColumns(connId: string): Promise<string[]> {
    const resolvedToken = resolveAdminToken();
    const url = new URL(buildApiUrl('api', 'db', 'columns'));
    url.searchParams.set('connId', connId);
    const res = await apiFetch('GET', url.toString(), {
      headers: resolvedToken ? { 'x-admin-token': resolvedToken } : undefined,
    });
    const data = await apiJsonFetch<{ columns?: string[] }>(res);
    return Array.isArray(data?.columns) ? data.columns : [];
  },

  /**
   * Search rows in the configured view using a key/query pair.
   */
  async searchRows(
    connId: string,
    key: string,
    query: string,
    options?: { mode?: 'equals' | 'contains'; limit?: number },
  ): Promise<Array<Record<string, unknown>>> {
    const resolvedToken = resolveAdminToken();
    const url = new URL(buildApiUrl('api', 'db', 'search'));
    url.searchParams.set('connId', connId);
    url.searchParams.set('key', key);
    url.searchParams.set('query', query);
    url.searchParams.set('mode', options?.mode || 'contains');
    url.searchParams.set('limit', String(options?.limit ?? 25));
    const res = await apiFetch('GET', url.toString(), {
      headers: resolvedToken ? { 'x-admin-token': resolvedToken } : undefined,
    });
    const data = await apiJsonFetch<{ rows?: Array<Record<string, unknown>> }>(res);
    return Array.isArray(data?.rows) ? data.rows : [];
  },

  /**
   * Disconnect and remove a stored connection record.
   */
  async disconnect(connId: string, adminToken?: string): Promise<void> {
    const resolvedToken = resolveAdminToken(adminToken);
    await apiFetch('DELETE', buildApiUrl('api', 'connections', connId), {
      headers: {
        ...(resolvedToken ? { 'x-admin-token': resolvedToken } : {}),
      },
    });
  },
};
