/**
 * API configuration utilities with auth token handling.
 */
import { Auth, getFreshIdToken } from './auth';

const DEFAULT_API_BASE = 'http://localhost:8000';
const DEFAULT_BACKEND_READY_MAX_WAIT_MS = 90000;
const MAX_BACKEND_READY_MAX_WAIT_MS = 300000;
const BACKEND_READY_REQUEST_TIMEOUT_MS = 4000;
const CLOUD_RUN_NO_INSTANCE_MARKER = 'no available instance';

let cachedBase: string | null = null;
const backendReadyPromisesByHealthUrl = new Map<string, Promise<void>>();
let authFailureRecoveryPromise: Promise<void> | null = null;

type ApiErrorPayload = {
  message?: string;
  error?: string;
  detail?: string | { message?: string };
  code?: string;
  error_code?: string;
};

const DEFAULT_STATUS_MESSAGES: Record<number, string> = {
  400: 'Request could not be completed. Check the provided details and try again.',
  401: 'Please sign in again to continue.',
  403: 'You do not have access to this resource.',
  404: 'We could not find that resource.',
  413: 'The uploaded file is too large. Please upload a smaller PDF.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'Something went wrong on our side. Please try again.',
};

export class ApiError extends Error {
  status: number;
  code?: string;
  payload?: unknown;

  constructor(message: string, status: number, code?: string, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

function extractErrorMessage(payload?: ApiErrorPayload | null): string | null {
  if (!payload) return null;
  if (typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim();
  if (typeof payload.error === 'string' && payload.error.trim()) return payload.error.trim();
  if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail.trim();
  if (payload.detail && typeof payload.detail === 'object') {
    const detailMessage = payload.detail.message;
    if (typeof detailMessage === 'string' && detailMessage.trim()) return detailMessage.trim();
  }
  return null;
}

function normalizeErrorMessage(status: number, payload: ApiErrorPayload | null, statusText?: string): string {
  const fallback = DEFAULT_STATUS_MESSAGES[status] || `Request failed (${status}).`;
  const raw = extractErrorMessage(payload);
  if (!raw || raw === String(status)) {
    return fallback;
  }
  if (status === 401) {
    return DEFAULT_STATUS_MESSAGES[401];
  }
  if (status === 404 && raw.toLowerCase() === 'not found') {
    return DEFAULT_STATUS_MESSAGES[404];
  }
  if (status === 403 && raw.toLowerCase() === 'session access denied') {
    return DEFAULT_STATUS_MESSAGES[403];
  }
  return raw || statusText || fallback;
}

function resolveRequestUrl(url: string): URL | null {
  const baseOrigin = typeof window !== 'undefined' && window.location?.origin
    ? window.location.origin
    : DEFAULT_API_BASE;
  try {
    return new URL(url, baseOrigin);
  } catch {
    return null;
  }
}

function resolveHostedOriginBase(): string | null {
  if (!import.meta.env?.PROD) {
    return null;
  }
  if (typeof window === 'undefined' || !window.location?.origin) {
    return null;
  }
  const origin = window.location.origin.trim().replace(/\/+$/, '');
  if (!origin) {
    return null;
  }
  const resolved = resolveRequestUrl(origin);
  const host = resolved?.hostname?.toLowerCase() ?? '';
  if (!host || host === 'localhost' || host === '127.0.0.1') {
    return null;
  }
  return origin;
}

function isBackendApiGet(method: string, url: string): boolean {
  if (method.trim().toUpperCase() !== 'GET') {
    return false;
  }
  const resolved = resolveRequestUrl(url);
  return Boolean(resolved?.pathname.startsWith('/api/'));
}

function isCloudRunColdStart429(response: Response, bodyText: string): boolean {
  if (response.status !== 429) {
    return false;
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const normalizedBody = bodyText.trim().toLowerCase();
  if (normalizedBody.includes(CLOUD_RUN_NO_INSTANCE_MARKER)) {
    return true;
  }
  return !contentType.includes('application/json') && normalizedBody.length > 0;
}

function resolveBackendReadyMaxWaitMs(): number {
  const raw = import.meta.env?.VITE_BACKEND_READY_MAX_WAIT_MS;
  const parsed = Number.parseInt(typeof raw === 'string' ? raw.trim() : '', 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_BACKEND_READY_MAX_WAIT_MS;
  }
  return Math.min(parsed, MAX_BACKEND_READY_MAX_WAIT_MS);
}

function backendReadyDelayMsForAttempt(attempt: number): number {
  if (attempt <= 0) {
    return 0;
  }
  return Math.min(1000 * (2 ** (attempt - 1)), 8000);
}

async function delayWithSignal(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) {
    if (signal?.aborted) {
      throw new TypeError('Request timed out.');
    }
    return;
  }
  await new Promise<void>((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onAbort);
      reject(new TypeError('Request timed out.'));
    };
    if (signal) {
      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

function resolveBackendHealthUrl(url?: string): string {
  const fallbackHealthUrl = buildApiUrl('api', 'health');
  if (!url) {
    return fallbackHealthUrl;
  }
  const resolved = resolveRequestUrl(url);
  if (!resolved) {
    return fallbackHealthUrl;
  }
  if (resolved.pathname === '/api/health') {
    return resolved.toString();
  }
  return new URL('/api/health', `${resolved.origin}/`).toString();
}

async function waitForBackendHealthUrlReady(healthUrl: string, signal?: AbortSignal): Promise<void> {
  const existing = backendReadyPromisesByHealthUrl.get(healthUrl);
  if (existing) {
    return existing;
  }

  // Share a single backend warmup loop per health endpoint so concurrent shell requests
  // do not all hammer `/api/health` while Cloud Run is still starting.
  const warmupPromise = (async () => {
    const deadline = Date.now() + resolveBackendReadyMaxWaitMs();
    let attempt = 0;

    while (Date.now() <= deadline) {
      const delayMs = backendReadyDelayMsForAttempt(attempt);
      await delayWithSignal(delayMs, signal);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), BACKEND_READY_REQUEST_TIMEOUT_MS);
      const onAbort = () => controller.abort();
      if (signal) {
        if (signal.aborted) {
          controller.abort();
        } else {
          signal.addEventListener('abort', onAbort, { once: true });
        }
      }

      try {
        const response = await fetch(healthUrl, {
          method: 'GET',
          cache: 'no-store',
          signal: controller.signal,
        });
        if (response.ok) {
          return;
        }
      } catch {
        if (signal?.aborted) {
          throw new TypeError('Request timed out.');
        }
      } finally {
        clearTimeout(timeoutId);
        signal?.removeEventListener('abort', onAbort);
      }

      attempt += 1;
    }
    throw new TypeError('Backend is still starting. Please wait a moment and try again.');
  })().finally(() => {
    backendReadyPromisesByHealthUrl.delete(healthUrl);
  });

  backendReadyPromisesByHealthUrl.set(healthUrl, warmupPromise);
  return warmupPromise;
}

export async function ensureBackendReady(options?: {
  healthUrl?: string;
  signal?: AbortSignal;
}): Promise<void> {
  await waitForBackendHealthUrlReady(resolveBackendHealthUrl(options?.healthUrl), options?.signal);
}

async function retryIfCloudRunColdStart(params: {
  method: string;
  url: string;
  response: Response;
  runFetch: (headersToUse: Headers) => Promise<Response>;
  requestHeaders: Headers;
  signal?: AbortSignal;
}): Promise<Response> {
  if (!isBackendApiGet(params.method, params.url)) {
    return params.response;
  }

  const resolvedUrl = resolveRequestUrl(params.url);
  if (!resolvedUrl) {
    return params.response;
  }

  let current = params.response;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const bodyText = await current.clone().text().catch(() => '');
    if (!isCloudRunColdStart429(current, bodyText)) {
      return current;
    }
    await waitForBackendHealthUrlReady(resolveBackendHealthUrl(resolvedUrl.toString()), params.signal);
    current = await params.runFetch(new Headers(params.requestHeaders));
  }

  return current;
}

/**
 * Resolve an admin token from env or localStorage in dev.
 */
function resolveAdminToken(): string | null {
  const env = import.meta.env;
  const isDev = Boolean(env?.DEV);
  if (!isDev) return null;
  const disableRaw = typeof env?.VITE_DISABLE_ADMIN_OVERRIDE === 'string'
    ? env.VITE_DISABLE_ADMIN_OVERRIDE.trim().toLowerCase()
    : '';
  if (disableRaw && ['1', 'true', 'yes'].includes(disableRaw)) {
    return null;
  }
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

/**
 * Resolve and cache the API base URL.
 */
export function getApiBaseUrl(): string {
  if (cachedBase) return cachedBase;
  const hostedOriginBase = resolveHostedOriginBase();
  if (hostedOriginBase) {
    cachedBase = hostedOriginBase;
    return cachedBase;
  }
  const env = import.meta.env;
  const raw = env?.VITE_API_URL || env?.VITE_SANDBOX_API_URL || env?.VITE_DETECTION_API_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const normalised = trimmed ? trimmed.replace(/\/+$/, '') : DEFAULT_API_BASE;
  cachedBase = normalised || DEFAULT_API_BASE;
  return cachedBase;
}

/**
 * Build a URL by joining path segments onto the API base.
 */
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
  authMode?: 'default' | 'anonymous';
  timeoutMs?: number;
}

async function recoverFromAuthFailure(): Promise<void> {
  if (authFailureRecoveryPromise) {
    return authFailureRecoveryPromise;
  }
  authFailureRecoveryPromise = Auth.signOut()
    .catch((error) => {
      console.error('[api] Failed to clear invalid auth session', error);
    })
    .finally(() => {
      authFailureRecoveryPromise = null;
    });
  return authFailureRecoveryPromise;
}

/**
 * Attach a Bearer token header if one is available.
 */
async function attachAuthHeader(headers: Headers, forceRefresh = false): Promise<string | null> {
  if (headers.has('Authorization')) return null;
  const token = await getFreshIdToken(forceRefresh);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return token;
}

/**
 * Fetch wrapper that handles auth refresh and error normalization.
 */
export async function apiFetch(
  method: string,
  url: string,
  options: ApiFetchOptions = {},
): Promise<Response> {
  const { allowStatuses, authMode = 'default', headers, timeoutMs, signal: inputSignal, ...requestInit } = options;
  const requestHeaders = new Headers(headers || {});
  if (authMode === 'anonymous') {
    requestHeaders.delete('Authorization');
    requestHeaders.delete('x-admin-token');
  }
  const managedAuth = authMode !== 'anonymous' && !requestHeaders.has('Authorization');
  const initialToken = managedAuth ? await attachAuthHeader(requestHeaders, false) : null;
  if (authMode !== 'anonymous' && !requestHeaders.has('Authorization')) {
    const adminToken = resolveAdminToken();
    if (adminToken && !requestHeaders.has('x-admin-token')) {
      requestHeaders.set('x-admin-token', adminToken);
    }
  }
  const runFetch = async (headersToUse: Headers) => {
    if (timeoutMs && timeoutMs > 0) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
      if (inputSignal) {
        if (inputSignal.aborted) {
          controller.abort();
        } else {
          inputSignal.addEventListener('abort', () => controller.abort(), { once: true });
        }
      }
      try {
        return await fetch(url, {
          method,
          headers: headersToUse,
          signal: controller.signal,
          ...requestInit,
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          throw new TypeError('Request timed out.');
        }
        throw error;
      } finally {
        clearTimeout(timeoutId);
      }
    }
    return fetch(url, { method, headers: headersToUse, signal: inputSignal, ...requestInit });
  };

  let response = await runFetch(requestHeaders);
  response = await retryIfCloudRunColdStart({
    method,
    url,
    response,
    runFetch,
    requestHeaders,
    signal: inputSignal ?? undefined,
  });

  if (response.status === 401 && managedAuth) {
    const refreshedToken = await getFreshIdToken(true);
    if (refreshedToken && refreshedToken !== initialToken) {
      const retryHeaders = new Headers(requestHeaders);
      retryHeaders.set('Authorization', `Bearer ${refreshedToken}`);
      response = await runFetch(retryHeaders);
    }
    if (response.status === 401) {
      await recoverFromAuthFailure();
    }
  }

  const allowed = allowStatuses?.includes(response.status);
  if (!response.ok && !allowed) {
    let payload: ApiErrorPayload | null = null;
    try {
      payload = (await response.clone().json()) as ApiErrorPayload;
    } catch {
      payload = null;
    }
    const message = normalizeErrorMessage(response.status, payload, response.statusText);
    const code =
      (payload && typeof payload.code === 'string' && payload.code.trim()) ||
      (payload && typeof payload.error_code === 'string' && payload.error_code.trim())
        ? (payload?.code || payload?.error_code)
        : undefined;
    throw new ApiError(message, response.status, code, payload ?? undefined);
  }
  return response;
}

/**
 * Parse a JSON response into a typed payload.
 */
export async function apiJsonFetch<T = any>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}
