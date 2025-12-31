import { getFreshIdToken } from './auth';

const DEFAULT_API_BASE = 'http://localhost:8000';

let cachedBase: string | null = null;

// Resolve the backend base URL once to avoid repeated env parsing.
export function getApiBaseUrl(): string {
  if (cachedBase) return cachedBase;
  const env = (import.meta as any)?.env;
  const raw = env?.VITE_API_URL || env?.VITE_SANDBOX_API_URL || env?.VITE_DETECTION_API_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const normalised = trimmed ? trimmed.replace(/\/$/, '') : DEFAULT_API_BASE;
  cachedBase = normalised || DEFAULT_API_BASE;
  return cachedBase;
}

// Build a normalized URL from path segments to keep callers concise.
export function buildApiUrl(...segments: Array<string>): string {
  const base = getApiBaseUrl();
  if (!segments.length) return base;
  const path = segments
    .filter(Boolean)
    .map((segment) => segment.replace(/^\/+|\/+$/g, ''))
    .filter(Boolean)
    .join('/');
  return path ? `${base}/${path}` : base;
}

export interface ApiFetchOptions extends RequestInit {
  allowStatuses?: number[];
}

async function attachAuthHeader(headers: Headers, forceRefresh = false): Promise<string | null> {
  if (headers.has('Authorization')) return null;
  const token = await getFreshIdToken(forceRefresh);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return token;
}

// Wrap fetch to inject auth headers and standardize error handling.
export async function apiFetch(
  method: string,
  url: string,
  options: ApiFetchOptions = {},
): Promise<Response> {
  const { allowStatuses, headers, ...requestInit } = options;
  const requestHeaders = new Headers(headers || {});
  const managedAuth = !requestHeaders.has('Authorization');
  const initialToken = await attachAuthHeader(requestHeaders, false);
  let response = await fetch(url, { method, headers: requestHeaders, ...requestInit });

  if (response.status === 401 && managedAuth) {
    const refreshedToken = await getFreshIdToken(true);
    if (refreshedToken && refreshedToken !== initialToken) {
      const retryHeaders = new Headers(requestHeaders);
      retryHeaders.set('Authorization', `Bearer ${refreshedToken}`);
      response = await fetch(url, { method, headers: retryHeaders, ...requestInit });
    }
  }

  const allowed = allowStatuses?.includes(response.status);
  if (!response.ok && !allowed) {
    let message = `${response.status}`;
    try {
      const data = await response.clone().json();
      if (data?.message) message = data.message;
      else if (data?.error) message = data.error;
      else if (data?.detail) message = data.detail;
    } catch {
      if (response.statusText) message = response.statusText;
    }
    throw new Error(message);
  }
  return response;
}

export async function apiJsonFetch<T = any>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}
