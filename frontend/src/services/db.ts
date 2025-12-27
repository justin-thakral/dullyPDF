import { buildApiUrl, apiFetch, apiJsonFetch } from './apiConfig';

export type DbType = 'postgres' | 'sqlserver';

function resolveAdminToken(override?: string): string | null {
  if (override && override.trim()) return override.trim();
  const env = (import.meta as any)?.env;
  const isDev = Boolean(env?.DEV);
  const raw = typeof env?.VITE_ADMIN_TOKEN === 'string' ? env.VITE_ADMIN_TOKEN.trim() : '';
  if (!raw) return null;
  return isDev ? raw : null;
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

  async disconnect(connId: string, adminToken?: string): Promise<void> {
    const resolvedToken = resolveAdminToken(adminToken);
    await apiFetch('DELETE', buildApiUrl('api', 'connections', connId), {
      headers: {
        ...(resolvedToken ? { 'x-admin-token': resolvedToken } : {}),
      },
    });
  },
};
